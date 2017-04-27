# steam-store-analysis
Analysis of data scraped from the Steam store.

# Analysis caveats

## Known data issues

### Prices

Initial price checking code was off; prices may be inaccurate in some cases for apps with app_id >= 48950 and <= 202240 (when the apps were contained in packages with reduced prices but the apps' prices weren't reduced).

Current price checking code still has some issues, which I don't care enough to fix (there are plenty of steam price analyzing tools out there); mainly, we always pull down the price for the first "game area" section on the page, which is a demo in some cases, so some games say "free" when they actually aren't.
