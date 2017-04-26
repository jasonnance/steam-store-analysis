# steam-store-analysis
Analysis of data scraped from the Steam store.

# Analysis caveats

## Known data issues

Initial price checking code was off; prices may be inaccurate in some cases for apps with app_id >= 48950 and <= 202240 (when the apps were contained in packages with reduced prices but the apps' prices weren't reduced).  Price checking code may still have issues.
