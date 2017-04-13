from selenium import webdriver
import requests
import dataset
import os

db = dataset.connect(os.environ['POSTGRES_URI'])

def upsert_all_apps():
    json = requests.get('http://api.steampowered.com/ISteamApps/GetAppList/v0001/').json()

    apps = json['applist']['apps']['app']

    for app in apps:
        db['game'].upsert({
            'steam_app_id': app['appid'],
            'game_name': app['name'],
        }, keys=['app_id'])

# Since we're not super worried about having an up-to-date list of apps,
# run this only if the table is empty
if db['game'].count() == 0:
    upsert_all_apps()

# driver = webdriver.Chrome()
# driver.get("http://store.steampowered.com")
