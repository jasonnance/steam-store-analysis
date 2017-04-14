from selenium import webdriver
import requests
import dataset
import os
import re

# Number of seconds to sleep between crawls
CRAWL_TIMEOUT = 10

THIRTY_DAY_REVIEW_REGEX = re.compile(r'^([0-9]+)% of the ([,0-9]+) user reviews in the last 30 days')
ALL_TIME_REVIEW_REGEX = re.compile(r'^([0-9]+)% of the ([,0-9]+) user reviews for this game')
DETAILS_BOX_REGEX = re.compile(r'^Title: ([^\n]+)\nGenre: ([^\n]+)\nDeveloper: ([^\n]+)\nPublisher: ([^\n]+)')
NUM_ACHIEVEMENTS_REGEX = re.compile(r'Includes ([,[0-9]+) Steam Achievements')

def upsert_all_apps():
    '''
    Get the full list of steam apps and upsert them in our database
    on the basis of steam's app ID.
    '''
    json = requests.get('http://api.steampowered.com/ISteamApps/GetAppList/v0001/').json()

    apps = json['applist']['apps']['app']

    for app in apps:
        db['game'].upsert({
            'steam_app_id': app['appid'],
            'game_name': app['name'],
        }, keys=['app_id'])

def scrape_store_page(app_id):
    '''
    Extract all the information we can from the store page for a given app ID.
    '''
    results = {}
    driver = webdriver.Chrome()
    driver.get("http://store.steampowered.com/app/{}".format(app_id))

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

    # TODO
    # - full_price
    # - long_description
    # - game_details (ex. "Single-player", "Multi-player", etc)
    # - tags (ex. "Strategy", "4X", "Space", etc)

    return results

def do_crawl(app_ids, db):
    '''
    Given a list of steam app IDs and a db connection, do a crawl for the app IDs
    and append the results to our list of crawls in the database.
    '''
    for app_id in app_ids:
        results = scrape_store_page(app_id)

        db['game_crawl'].insert(results)

        time.sleep(CRAWL_TIMEOUT)


def run():
    db = dataset.connect(os.environ['POSTGRES_URI'], ensure_schema=False)

    # Since we're not super worried about having an up-to-date list of apps,
    # run this only if the table is empty
    if db['game'].count() == 0:
        upsert_all_apps()

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

    do_crawl(missing_app_ids)


if __name__ == '__main__':
    run()

