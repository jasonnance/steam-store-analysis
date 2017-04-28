import requests
import dataset
import os
import sys
import re
import datetime as dt
import time
import traceback
from tqdm import tqdm
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, ElementNotVisibleException
from dateutil.parser import parse as dtparse

# Number of seconds to sleep between crawls
CRAWL_TIMEOUT = 10

THIRTY_DAY_REVIEW_REGEX = re.compile(r'^([0-9]+)% of the ([,0-9]+) user reviews in the last 30 days')
ALL_TIME_REVIEW_REGEX = re.compile(r'^([0-9]+)% of the ([,0-9]+) user reviews for this game')
DETAILS_BOX_REGEX = re.compile(r'^Title: ([^\n]+)(?:\nGenre: ([^\n]+))?(?:\nDeveloper: ([^\n]+))?(?:\nPublisher: ([^\n]+))?')
NUM_ACHIEVEMENTS_REGEX = re.compile(r'Includes ([,[0-9]+) Steam Achievements')

FREE_TO_PLAY_PHRASES = frozenset(('free to play', 'free', 'play for free!', 'free demo', 'play for free'))
FREE_TO_PLAY_REGEXES = frozenset((re.compile('Play .* Demo'),))

COMING_SOON_PHRASES = frozenset(('coming soon', 'to be announced', 'to be announced.',
                                 'tbd', 'when you least expect it', 'tba'))

# Some release dates are vague ex. "Summer 2017" or "Q2 2016"; map a season/quarter to a month so Python
# can parse the date
SEASON_MONTH_MAPPING = {
    "summer": "july",
    "spring": "april",
    "winter": "january",
    "fall": "october",
    "q1": "february",
    "q2": "may",
    "q3": "august",
    "q4": "november",
}

YEAR_REGEX = re.compile(r'(\d{4})')

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

def scrape_store_page(driver, app_id):
    '''
    Extract all the information we can from the store page for a given app ID.

    Use the given driver so we don't have to worry about closing it when we exit.
    '''
    # TODO (maybe): add "ignore_reason" field to track why we skipped an app
    results = {'steam_app_id': app_id}
    store_base_url = "http://store.steampowered.com"
    app_url = "{}/app/{}".format(store_base_url, app_id)
    driver.get(app_url)

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

    try:
        # If this succeeds, we need to click on the "continue" button to tell
        # steam we're okay with seeing NSFW content.
        driver.find_element_by_class_name('agegate_tags')

        # Click the "Continue" button
        (driver.find_element_by_css_selector(
                '.agegate_text_container.btns > a.btn_grey_white_innerfade:first-child'
            )
            .click())
    except NoSuchElementException:
        # No NSFW gate; we're good to continue
        pass

    if driver.current_url in (store_base_url, '{}/'.format(store_base_url)):
        # We were redirected; the app doesn't have a store page.
        return results
    elif 'store.steampowered.com/video' in driver.current_url:
        # This is a trailer for something else; we'll get the actual app later.
        return results

    try:
        # If this succeeds, the app has no store page; its store page
        # redirects to its community hub instead.  Skip it.
        driver.find_element_by_id('AppHubCards')
        return results
    except NoSuchElementException:
        pass

    try:
        # If this succeeds, we've got a steam store error
        error_element = driver.find_element_by_id('error_box')
        error_text = error_element.find_element_by_class_name('error')
        if error_text.text == 'This item is currently unavailable in your region':
            # We can't see this app; ignore it
            return results
    except NoSuchElementException:
        pass

    try:
        # If this succeeds, Chrome is showing us an error
        error_element = driver.find_element_by_class_name('error-code')
        if error_element.text == 'ERR_TOO_MANY_REDIRECTS':
            # Something wonky with the server response for this store page;
            # it's redirecting infinitely to itself.  Ignore it
            return results
    except NoSuchElementException:
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
            return results
        elif description.text.startswith('ABOUT THIS SOFTWARE'):
            # This is computer software; ignore it
            return results
        elif description.text.startswith('ABOUT THIS VIDEO'):
            # Video content; ignore it
            return results
    if 'long_description' not in results and len(descriptions) > 0:
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

    try:
        raw_date = driver.find_element_by_css_selector('.release_date .date').text

        # Replace seasons with months if needed
        for season, month in SEASON_MONTH_MAPPING.items():
            if season in raw_date.lower():
                raw_date = raw_date.lower().replace(season, month)

        try:
            results['release_date'] = dtparse(raw_date)
        except ValueError:
            # Failed to parse the date; match it or raise an error
            if raw_date.lower() in COMING_SOON_PHRASES:
                # Don't really have a better way to represent a missing
                # release date than None
                results['release_date'] = None
            # Failing everything else, try to just parse a year out and use that
            elif YEAR_REGEX.search(raw_date):
                results['release_date'] = dtparse(YEAR_REGEX.search(raw_date).group(1))
            else:
                raise ValueError('Unable to parse release date for app {}: {}'.format(
                    app_id, raw_date))
    except NoSuchElementException:
        # This app doesn't have a release date for some reason
        pass

    # There's additional detail about VR stuff here, but we're not worried about that for now
    details_text = driver.find_elements_by_css_selector('.details_block:not(.vrsupport)')[0].text
    details_match = DETAILS_BOX_REGEX.match(details_text)
    results['title'] = details_match.group(1)
    raw_genre = details_match.group(2)
    if raw_genre is not None:
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
        raw_metacritic_score = driver.find_element_by_class_name('score').text
        if raw_metacritic_score != 'NA':
            results['metacritic_score'] = int(raw_metacritic_score)
    except NoSuchElementException:
        # Some games don't have metascores
        pass

    try:
        # Look for prices
        # NOTE: we'll take the first price available on the page (since
        # it's impossible to tell which one is for the actual game), so
        # if a game is only available in a package, we'll record its price
        # as the price of the package
        game_area = driver.find_element_by_class_name(
            'game_area_purchase_game'
        )
    except NoSuchElementException:
        # No price on the page
        game_area = None

    if game_area is not None:
        try:
            # Check within the "game_area" to avoid getting a DLC price
            raw_price = game_area.find_element_by_class_name('game_purchase_price').text
            if raw_price.lower() in FREE_TO_PLAY_PHRASES:
                price = 0
            elif any(regex.match(raw_price) for regex in FREE_TO_PLAY_REGEXES):
                price = 0
            elif raw_price == 'Third-party':
                # For all examples thus far, this has meant "free", but I don't think
                # we can assume that if the source is a 3rd party
                price = None
            else:
                price = float(raw_price.replace('$', ''))
            results['full_price'] = price
        except NoSuchElementException:
            # On sale
            try:
                raw_price = game_area.find_element_by_class_name('discount_original_price').text
                results['full_price'] = float(raw_price.replace('$', ''))
            except NoSuchElementException:
                # There's a "game area" block, but it doesn't have a price
                # in it (the game is free)
                pass

    results['game_details'] = []
    game_details_elements = driver.find_elements_by_class_name('game_area_details_specs')
    for element in game_details_elements:
        results['game_details'].append(element.find_element_by_css_selector('.name').text)

    results['tags'] = []
    try:
        # Try to get the big list of tags if it's there
        driver.find_element_by_css_selector('.app_tag.add_button').click()
        tag_elements = driver.find_elements_by_css_selector('#app_tagging_modal a.app_tag')
    except (NoSuchElementException, ElementNotVisibleException):
        # Settle for the short list if not
        tag_elements = driver.find_elements_by_css_selector('a.app_tag')
    for element in tag_elements:
        results['tags'].append(element.text)


    return results


def insert_with_mapping(*, db, descrs, entity_table, pk_name, join_table, mapping, app_id, crawl_time):
    '''
    Given a db connection, some list of description data, a table of entities, the name of the PK,
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
            entity_id = db[entity_table].insert({'descr': descr})
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

    # Add a handler here to allow us to gracefully save our work and quit
    # if the user halts a crawl early via Ctrl + C.
    # NOTE: since background jobs ignore SIGINT, this has no effect if
    # the script is launched in the background; see
    # http://stackoverflow.com/questions/1112343/how-do-i-capture-sigint-in-python#comment68802096_1112357
    should_quit = False

    # Set up a driver and re-use it so we don't have to worry about
    # closing it for each app
    driver = webdriver.Chrome()

    for app_id in tqdm(app_ids):
        try:
            db.begin()
            if should_quit:
                break

            time.sleep(CRAWL_TIMEOUT)
            results = scrape_store_page(driver, app_id)

            crawl_time = dt.datetime.now()
            results['crawl_time'] = crawl_time

            # Default to empty list if the results don't contain any of these
            tags, details, genres = [], [], []

            # Pull the lists off before we insert the main crawl record.
            # Use sets so we don't try to insert duplicates, if there are any.
            if 'tags' in results:
                tags = set(results['tags'])
                del results['tags']
            if 'game_details' in results:
                details = set(results['game_details'])
                del results['game_details']
            if 'genres' in results:
                genres = set(results['genres'])
                del results['genres']

            db['game_crawl'].insert(results)

            if len(tags) > 0:
                insert_with_mapping(
                    db=db,
                    descrs=tags,
                    entity_table='steam_tag',
                    pk_name='tag_id',
                    join_table='game_crawl_tag',
                    mapping=tag_mapping,
                    app_id=app_id,
                    crawl_time=crawl_time
                )

            if len(details) > 0:
                insert_with_mapping(
                    db=db,
                    descrs=details,
                    entity_table='steam_game_detail',
                    pk_name='detail_id',
                    join_table='game_crawl_detail',
                    mapping=detail_mapping,
                    app_id=app_id,
                    crawl_time=crawl_time
                )

            if len(genres) > 0:
                insert_with_mapping(
                    db=db,
                    descrs=genres,
                    entity_table='steam_genre',
                    pk_name='genre_id',
                    join_table='game_crawl_genre',
                    mapping=genre_mapping,
                    app_id=app_id,
                    crawl_time=crawl_time
                )
            db.commit()
        except Exception as e:
            # Problem app; pass along our failure and continue to the next one
            print('Failed to load app ID {}; continuing'.format(app_id), file=sys.stderr)
            traceback.print_exc()

            # Ensure Postgres lets us continue by rolling back the current transaction
            db.rollback()
    driver.close()


def run():
    db = dataset.connect(os.environ['POSTGRES_URI'], ensure_schema=False)

    # Since we're not super worried about having an up-to-date list of apps,
    # run this only if the table is empty
    if db['game'].count() == 0:
        upsert_all_apps(db)

    # For now, just crawl the apps we don't already have
    missing_crawl_query = '''
    SELECT g.steam_app_id
    FROM game g
      LEFT JOIN game_crawl gc
        USING (steam_app_id)
    WHERE gc.steam_app_id IS NULL;
    '''

    missing_app_ids = [r['steam_app_id'] for r in db.query(missing_crawl_query)]

    do_crawl(missing_app_ids, db)


if __name__ == '__main__':
    run()
