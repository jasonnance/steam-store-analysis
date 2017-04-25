import requests
import dataset
import os
import re
import datetime as dt
import time
from tqdm import tqdm
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException

# Number of seconds to sleep between crawls
CRAWL_TIMEOUT = 10

THIRTY_DAY_REVIEW_REGEX = re.compile(r'^([0-9]+)% of the ([,0-9]+) user reviews in the last 30 days')
ALL_TIME_REVIEW_REGEX = re.compile(r'^([0-9]+)% of the ([,0-9]+) user reviews for this game')
DETAILS_BOX_REGEX = re.compile(r'^Title: ([^\n]+)\nGenre: ([^\n]+)\nDeveloper: ([^\n]+)\nPublisher: ([^\n]+)')
NUM_ACHIEVEMENTS_REGEX = re.compile(r'Includes ([,[0-9]+) Steam Achievements')

def upsert_all_apps(db):
    '''
    Get the full list of steam apps and upsert them in our database
    on the basis of steam's app ID.
    '''
    json = requests.get('http://api.steampowered.com/ISteamApps/GetAppList/v0001/').json()

    apps = json['applist']['apps']['app']

    db.begin()

    for app in tqdm(apps):
        db['game'].upsert({
            'steam_app_id': app['appid'],
            'game_name': app['name'],
        }, keys=['app_id'])

    db.commit()

def scrape_store_page(app_id):
    '''
    Extract all the information we can from the store page for a given app ID.
    '''
    results = {'steam_app_id': app_id}
    driver = webdriver.Chrome()
    store_base_url = "http://store.steampowered.com"
    app_url = "{}/app/{}".format(store_base_url, app_id)
    driver.get(app_url)

    if driver.current_url in (store_base_url, '{}/'.format(store_base_url)):
        # We were redirected; the app doesn't have a store page.
        return results

    try:
        # If this succeeds, we need to pass through the age gate.
        driver.find_element_by_id('agegate_box')

        select_element = driver.find_element_by_id('ageYear')
        # open year dialog
        select_element.click()
        # select correct year
        select_element.find_element_by_css_selector('option[value="1993"]').click()
        # close year dialog
        select_element.click()
        # submit the form
        driver.find_element_by_id('agecheck_form').submit()
    except NoSuchElementException:
        # No age gate; we're good to continue
        pass

    # Get the description first, since it tells us whether the app is streaming video
    # (which means we don't care about it)
    descriptions = driver.find_elements_by_class_name('game_area_description')
    for description in descriptions:
        if description.text.startswith('ABOUT THIS GAME'):
            results['is_dlc'] = False
            results['long_description'] = description.text
        elif description.text.startswith('ABOUT THIS CONTENT'):
            results['is_dlc'] = True
            results['long_description'] = description.text
        elif description.text.startswith('ABOUT THIS SERIES'):
            # This is streaming video; we don't care about it, so just return
            driver.close()
            return results
    if 'long_description' not in results:
        raise RuntimeError('Unable to parse description for app_id {}'.format(app_id))

    results['game_name'] = (driver
                            .find_element_by_class_name('apphub_AppName')
                            .text)

    results['short_description'] = (driver
                                    .find_element_by_class_name('game_description_snippet')
                                    .text)

    reviews_texts = [element.get_attribute('data-store-tooltip')
                     for element in (driver
                                     .find_elements_by_class_name('user_reviews_summary_row')
                                     )]

    for text in reviews_texts:
        thirty_day_match = THIRTY_DAY_REVIEW_REGEX.match(text)

        if thirty_day_match:
            results['pct_positive_reviews_last_30_days'] = int(thirty_day_match.group(1))
            results['reviews_last_30_days'] = int(thirty_day_match.group(2).replace(',', ''))
        else:
            all_time_match = ALL_TIME_REVIEW_REGEX.match(text)

            if all_time_match:
                results['pct_positive_reviews_all_time'] = int(all_time_match.group(1))
                results['reviews_all_time'] = int(all_time_match.group(2).replace(',', ''))

    results['release_date'] = driver.find_element_by_css_selector('.release_date .date').text

    details_text = driver.find_elements_by_class_name('details_block')[0].text
    details_match = DETAILS_BOX_REGEX.match(details_text)
    results['title'] = details_match.group(1)
    results['genre'] = details_match.group(2)
    results['developer'] = details_match.group(3)
    results['publisher'] = details_match.group(4)

    block_titles_texts = [element.text
                          for element in (driver
                                          .find_elements_by_class_name('block_title')
                                          )]

    for text in block_titles_texts:
        num_achievements_match = NUM_ACHIEVEMENTS_REGEX.match(text)

        if num_achievements_match:
            results['num_achievements'] = int(num_achievements_match.group(1))

    results['metacritic_score'] = int(driver.find_element_by_class_name('score').text)

    try:
        # Not on sale or Free to Play
        raw_price = driver.find_element_by_class_name('game_purchase_price').text
        if raw_price == 'Free to Play':
            price = 0
        else:
            price = float(raw_price.replace('$', ''))
        results['full_price'] = price
    except NoSuchElementException:
        # On sale
        raw_price = driver.find_element_by_class_name('discount_original_price').text
        results['full_price'] = float(raw_price.replace('$', ''))

    results['long_description'] = driver.find_element_by_class_name('game_area_description').text

    results['game_details'] = []
    game_details_elements = driver.find_elements_by_class_name('game_area_details_specs')
    for element in game_details_elements:
        results['game_details'].append(element.find_element_by_css_selector('a.name').text)

    results['tags'] = []
    driver.find_element_by_css_selector('.app_tag.add_button').click()
    tag_elements = driver.find_elements_by_css_selector('#app_tagging_modal a.app_tag')
    for element in tag_elements:
        results['tags'].append(element.text)

    return results

def do_crawl(app_ids, db):
    '''
    Given a list of steam app IDs and a db connection, do a crawl for the app IDs
    and append the results to our list of crawls in the database.
    '''
    tag_mapping = {r['descr']: r['tag_id'] for r in db['steam_tag'].find()}
    detail_mapping = {r['descr']: r['detail_id'] for r in db['steam_game_detail'].find()}

    db.begin()
    for app_id in tqdm(app_ids):
        try:
            results = scrape_store_page(app_id)
        except:
            db.commit()
            print("Failed crawl for ID {}".format(app_id))
            raise

        crawl_time = dt.datetime.now()
        results['crawl_time'] = crawl_time

        tags = results['tags']
        del results['tags']
        details = results['game_details']
        del results['game_details']

        db['game_crawl'].insert(results)

        for tag in tags:
            try:
                tag_id = tag_mapping[tag]
            except KeyError:
                tag_id = db['steam_tag'].insert({'descr': tag})
                tag_mapping[tag] = tag_id

            db['game_crawl_tag'].insert({
                'steam_app_id': app_id,
                'crawl_time': crawl_time,
                'tag_id': tag_id
            })

        for detail in details:
            try:
                detail_id = detail_mapping[detail]
            except KeyError:
                detail_id = db['steam_game_detail'].insert({'descr': detail})
                detail_mapping[detail] = detail_id

            db['game_crawl_detail'].insert({
                'steam_app_id': app_id,
                'crawl_time': crawl_time,
                'detail_id': detail_id
            })

        time.sleep(CRAWL_TIMEOUT)
    db.commit()


def run():
    db = dataset.connect(os.environ['POSTGRES_URI'], ensure_schema=False)

    # Since we're not super worried about having an up-to-date list of apps,
    # run this only if the table is empty
    if db['game'].count() == 0:
        upsert_all_apps(db)

    # For now, just crawl the apps we don't already have
    missing_crawl_query = '''
    SELECT steam_app_id
    FROM game g
      LEFT JOIN game_crawl gc
        USING (steam_app_id)
    WHERE gc.steam_app_id IS NULL;
    '''

    missing_app_ids = [r['steam_app_id'] for r in db.query(missing_crawl_query)]

    # TODO remove after we're done testing the crawl function
    missing_app_ids = missing_app_ids[:1]

    do_crawl(missing_app_ids, db)


if __name__ == '__main__':
    run()

