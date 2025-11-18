# Quran YouTube Auto Uploader  

A simple Python script that connects to an already-open Chrome session (started with `--remote-debugging-port`) and uploads MP4 files structured in Surah folders to YouTube, applying simple English title rules, inserting Arabic translated title (best-effort), creating playlists per Surah (nominally), scheduling uploads hour-by-hour, and logging/reporting.

## Requirements
- Python 3.9+
- Google Chrome
- Chromedriver matching your Chrome version (webdriver-manager is used to auto-install)
- The Chrome instance must be started manually with `--remote-debugging-port=9222` and you must be logged into your YouTube account.

## Folder structure
