import requests
import dataset
import os
import re
import datetime as dt
import time
from tqdm import tqdm
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, ElementNotVisibleException

# Number of seconds to sleep between crawls
CRAWL_TIMEOUT = 10

THIRTY_DAY_REVIEW_REGEX = re.compile(r'^([0-9]+)% of the ([,0-9]+) user reviews in the last 30 days')
ALL_TIME_REVIEW_REGEX = re.compile(r'^([0-9]+)% of the ([,0-9]+) user reviews for this game')
DETAILS_BOX_REGEX = re.compile(r'^Title: ([^\n]+)\nGenre: ([^\n]+)\nDeveloper: ([^\n]+)(?:\nPublisher: ([^\n]+))?')
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
        driver.close()
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

    try:
        results['short_description'] = (driver
                                        .find_element_by_class_name('game_description_snippet')
                                        .text)
    except NoSuchElementException:
        # DLC doesn't have a short description
        pass

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

    # There's additional detail about VR stuff here, but we're not worried about that for now
    details_text = driver.find_elements_by_css_selector('.details_block:not(.vrsupport)')[0].text
    details_match = DETAILS_BOX_REGEX.match(details_text)
    results['title'] = details_match.group(1)
    raw_genre = details_match.group(2)
    results['genres'] = raw_genre.split(', ')
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

    try:
        results['metacritic_score'] = int(driver.find_element_by_class_name('score').text)
    except NoSuchElementException:
        # Some games don't have metascores
        pass

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

    results['game_details'] = []
    game_details_elements = driver.find_elements_by_class_name('game_area_details_specs')
    for element in game_details_elements:
        results['game_details'].append(element.find_element_by_css_selector('a.name').text)

    results['tags'] = []
    try:
        # Try to get the big list of tags if it's there
        driver.find_element_by_css_selector('.app_tag.add_button').click()
        tag_elements = driver.find_elements_by_css_selector('#app_tagging_modal a.app_tag')
    except ElementNotVisibleException:
        # Settle for the short list if not
        tag_elements = driver.find_elements_by_css_selector('a.app_tag')
    for element in tag_elements:
        results['tags'].append(element.text)

    driver.close()

    return results

def insert_with_mapping(*, descrs, entity_table, pk_name, join_table, mapping, app_id, crawl_time):
    '''
    Given some list of description data, a table of entities, the name of the PK,
    a many-to-many join table for the entities to game crawls,
    a mapping from descrs to entity table IDs, and an app_id/crawl_time,
    update the entity table/mapping if necessary and insert
    the entity in the many-to-many join table.

    Mutates the mapping.
    '''
    for descr in descrs:
        try:
            entity_id = mapping[descr]
        except KeyError:
            entity_id = db[entity_table]
            mapping[descr] = entity_id

        db[join_table].insert({
            'steam_app_id': app_id,
            'crawl_time': crawl_time,
            pk_name: entity_id,
        })

def do_crawl(app_ids, db):
    '''
    Given a list of steam app IDs and a db connection, do a crawl for the app IDs
    and append the results to our list of crawls in the database.
    '''
    tag_mapping = {r['descr']: r['tag_id'] for r in db['steam_tag'].find()}
    detail_mapping = {r['descr']: r['detail_id'] for r in db['steam_game_detail'].find()}
    genre_mapping = {r['descr']: r['genre_id'] for r in db['steam_genre'].find()}

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

        # Pull the lists off before we insert the main crawl record.
        tags = results['tags']
        del results['tags']
        details = results['game_details']
        del results['game_details']
        genres = results['genres']
        del results['genres']

        db['game_crawl'].insert(results)

        insert_with_mapping(
            descrs=tags,
            entity_table='steam_tag',
            pk_name='tag_id',
            join_table='game_crawl_tag',
            mapping=tag_mapping,
            app_id=app_id,
            crawl_time=crawl_time
        )

        insert_with_mapping(
            descrs=details,
            entity_table='steam_game_detail',
            pk_name='detail_id',
            join_table='game_crawl_detail',
            mapping=detail_mapping,
            app_id=app_id,
            crawl_time=crawl_time
        )

        insert_with_mapping(
            descrs=genres,
            entity_table='steam_genre',
            pk_name='genre_id',
            join_table='game_crawl_genre',
            mapping=genre_mapping,
            app_id=app_id,
            crawl_time=crawl_time
        )

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

