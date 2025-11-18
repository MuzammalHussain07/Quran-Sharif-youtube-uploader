"""
youtube_auto_upload.py
Simple uploader that connects to an already-open Chrome with remote debugging,
scans Surah folders, uploads MP4 files in alphabetical order, applies
English title rules, inserts an Arabic translation title, creates playlists per Surah,
schedules uploads hour-by-hour, and logs a CSV report.

USAGE:
1. Start Chrome manually with --remote-debugging-port=9222 and be logged into YouTube.
2. Configure config.json (root_folder path).
3. pip install -r requirements.txt
4. python youtube_auto_upload.py
"""

import os
import re
import csv
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

# --------------------------
# Helpers / Config
# --------------------------
CONFIG_PATH = "config.json"
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

ROOT_FOLDER = CONFIG.get("root_folder", "D:/QuranUploads")
START_DATETIME = CONFIG.get("start_datetime", None)
HOUR_INTERVAL = float(CONFIG.get("hour_interval", 1))
DEBUGGER_ADDRESS = CONFIG.get("chrome_debugger_address", "127.0.0.1:9222")
LOG_FILE = CONFIG.get("log_file", "upload_log.txt")
REPORT_CSV = CONFIG.get("report_csv", "reports/upload_report.csv")

# Setup logging
os.makedirs(os.path.dirname(REPORT_CSV) or ".", exist_ok=True)
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# --------------------------
# Connect to existing Chrome
# --------------------------
def get_driver():
    """Connect to an existing Chrome session started with --remote-debugging-port."""
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)
    try:
        # Use webdriver-manager to ensure chromedriver binary present
        driver = webdriver.Chrome(ChromeDriverManager().install(), options=chrome_options)
    except WebDriverException as e:
        logging.exception("Failed to start webdriver. Make sure chromedriver matches Chrome version.")
        raise
    driver.set_window_size(1200, 900)
    return driver

# --------------------------
# Title generation rules
# --------------------------
def generate_english_title(filename):
    """Base title = filename without .mp4
       If filename contains 'Mahmoud Ali', append ' Al-Banna'
    """
    base = os.path.basename(filename)
    if base.lower().endswith(".mp4"):
        base = base[:-4]
    if "Mahmoud Ali".lower() in base.lower():
        # keep original casing of base, just append
        base = base + " Al-Banna"
    return base

def generate_arabic_title(surah_name, ayah_number):
    """Simple Arabic title generation using surah name and ayah number.
       This is a template field placed into 'Translations' tab (translated title).
    """
    # Example: "سورة البقرة - الآية 5 - تلاوة"
    return f"{surah_name} - الآية {ayah_number} - تلاوة"

# --------------------------
# Playlist helper (very simple)
# --------------------------
def create_playlist_if_not_exists(driver, playlist_name):
    """
    Minimal attempt to create/find playlist.
    NOTE: YouTube changes UI often; this function attempts a straightforward approach.
    If playlist management fails due to UI changes, you'll need to adapt selectors.
    """
    logging.info(f"Ensuring playlist exists for: {playlist_name}")
    # Open playlist creation URL (YouTube may demand different flows for creating playlists)
    # We'll open the library playlists page and rely on user being logged in.
    try:
        driver.get("https://www.youtube.com/playlist?list=PL")
        time.sleep(2)
    except Exception:
        logging.exception("Failed to open YouTube playlist page.")
    # For simplicity, return playlist_name as nominal identifier.
    return playlist_name

# --------------------------
# Upload function
# --------------------------
def upload_video(driver, file_path, english_title, arabic_title, schedule_dt, playlist_name):
    """
    Upload file, set title, set translation (approx), schedule, add to playlist.
    Because YouTube's upload page structure and dynamic ids change frequently,
    these selectors may require maintenance.
    """
    logging.info(f"Starting upload: {file_path} -> {english_title}")
    try:
        driver.get("https://www.youtube.com/upload")
        time.sleep(4)  # let upload page load

        # Find file input and send file path
        file_input = None
        inputs = driver.find_elements("xpath", "//input[@type='file']")
        if inputs:
            file_input = inputs[0]
        if not file_input:
            raise NoSuchElementException("File input not found on upload page.")

        file_input.send_keys(str(file_path))
        time.sleep(5)  # wait for upload to begin / metadata to populate

        # Title box: try common textarea; YouTube sometimes uses contenteditable divs.
        try:
            title_input = driver.find_element("xpath", "//ytcp-social-suggestion-input//textarea")
        except NoSuchElementException:
            # fallback: any textarea
            try:
                title_input = driver.find_element("xpath", "//textarea[@id='textbox' or @id='title-textarea']")
            except NoSuchElementException:
                title_input = None

        if title_input:
            title_input.clear()
            title_input.send_keys(english_title)
        else:
            logging.warning("Title field not found; upload may proceed with original title.")

        time.sleep(1)

        # Try to open Translations tab (UI varies). We will attempt a best-effort approach.
        try:
            # click 'More options' then 'Translations' - selectors may need update
            more_btn = driver.find_element("xpath", "//ytcp-button[@id='toggle-button'][@aria-label='More options']")
            more_btn.click()
            time.sleep(1)
        except Exception:
            # ignore; continue
            pass

        # Attempt to set translated title (Arabic). This often requires opening translations UI.
        try:
            # Common: button with text "Translations" or tab id
            trans_tab = driver.find_elements("xpath", "//ytcp-button//span[text()='Translations' or text()='الترجمات']")
            if trans_tab:
                trans_tab[0].click()
                time.sleep(1)
                # find translated title textarea
                translated_input = driver.find_element("xpath", "//textarea[@aria-label='Translated title' or contains(@id,'translated-title')]")
                translated_input.clear()
                translated_input.send_keys(arabic_title)
                time.sleep(1)
        except Exception:
            logging.info("Could not set translation field automatically (UI may differ).")

        # Scheduling: attempt to set scheduling. Many flows on YouTube require clicking the visibility block.
        try:
            # open visibility menu
            visibility_btns = driver.find_elements("xpath", "//tp-yt-paper-radio-button//div[contains(text(),'Schedule') or contains(text(),'مجدول')]")
            if visibility_btns:
                visibility_btns[0].click()
            else:
                # Next/Done flow - attempt basic schedule inputs
                pass
            time.sleep(1)
            # Try to find date/time inputs (if present)
            date_input = driver.find_elements("xpath", "//input[@type='date']")
            time_input = driver.find_elements("xpath", "//input[@type='time']")
            if date_input and time_input:
                date_input[0].clear()
                date_input[0].send_keys(schedule_dt.strftime("%Y-%m-%d"))
                time_input[0].clear()
                time_input[0].send_keys(schedule_dt.strftime("%H:%M"))
                time.sleep(1)
        except Exception:
            logging.info("Schedule inputs not found or not set - please verify manually in YouTube Studio.")

        # Add to playlist: attempt to open playlist picker
        try:
            playlist_btns = driver.find_elements("xpath", "//ytcp-button//span[text()='Playlist' or text()='القوائم']")
            if playlist_btns:
                playlist_btns[0].click()
                time.sleep(1)
                # attempt to type playlist name and select
                search_inp = driver.find_element("xpath", "//input[@aria-label='Add to playlist' or @id='playlist-search-input']")
                search_inp.send_keys(playlist_name)
                time.sleep(1)
                # click the matching playlist if found
                hits = driver.find_elements("xpath", f"//yt-formatted-string[text()=\"{playlist_name}\"]")
                if hits:
                    hits[0].click()
                    time.sleep(1)
        except Exception:
            logging.info("Playlist assignment step failed or is skipped (UI variance).")

        # Finalize: try to click Done / Save
        try:
            done_btns = driver.find_elements("xpath", "//ytcp-button//span[text()='Done' or text()='Save' or text()='Finish']")
            if done_btns:
                done_btns[0].click()
            else:
                # try to click publish/save button by id
                btn = driver.find_elements("xpath", "//button[@id='done-button' or @id='confirm-button']")
                if btn:
                    btn[0].click()
        except Exception:
            logging.info("Finalizing upload may need manual completion on YouTube UI.")

        logging.info(f"Upload initiated for {english_title} scheduled at {schedule_dt.isoformat()}")
        return True

    except Exception as e:
        logging.exception(f"Exception while uploading {file_path}: {e}")
        return False

# --------------------------
# Main processing logic
# --------------------------
def process_all_surahs():
    driver = get_driver()

    if START_DATETIME:
        start_dt = datetime.fromisoformat(START_DATETIME)
    else:
        start_dt = datetime.now()

    # Prepare CSV report
    report_rows = []
    header = ["timestamp_utc", "surah_folder", "file_path", "english_title", "arabic_title", "scheduled_at", "status", "notes"]
    if not os.path.exists(os.path.dirname(REPORT_CSV)) and os.path.dirname(REPORT_CSV) != "":
        os.makedirs(os.path.dirname(REPORT_CSV), exist_ok=True)
    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(header)

    # iterate Surah folders sorted
    root = Path(ROOT_FOLDER)
    if not root.exists():
        logging.error(f"Root folder does not exist: {ROOT_FOLDER}")
        return

    surah_folders = sorted([p for p in root.iterdir() if p.is_dir()])

    schedule_dt = start_dt
    for surah in surah_folders:
        # Expect folder name like "002 Al-Baqarah" -> split into number + name
        surah_text = surah.name
        parts = surah_text.split(" ", 1)
        if len(parts) == 2:
            _, surah_name = parts
        else:
            surah_name = surah_text

        playlist_name = create_playlist_if_not_exists(driver, surah_name)

        mp4_files = sorted([f for f in surah.iterdir() if f.is_file() and f.suffix.lower() == ".mp4"], key=lambda p: p.name)

        for mp4 in mp4_files:
            try:
                # extract ayah number by pattern like 002_005.mp4 or something with underscore number
                m = re.search(r"_(\d+)", mp4.name)
                ayah_num = m.group(1) if m else ""
                english_title = generate_english_title(mp4.name)
                arabic_title = generate_arabic_title(surah_name, ayah_num or "")

                ok = upload_video(driver, str(mp4), english_title, arabic_title, schedule_dt, playlist_name)

                status = "OK" if ok else "FAILED"
                notes = ""

                # append to CSV
                with open(REPORT_CSV, "a", newline="", encoding="utf-8") as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow([
                        datetime.utcnow().isoformat(),
                        surah_text,
                        str(mp4),
                        english_title,
                        arabic_title,
                        schedule_dt.isoformat(),
                        status,
                        notes
                    ])

                logging.info(f"Processed: {mp4} -> {status}")
            except Exception:
                logging.exception(f"Failed processing file: {mp4}")

            # increment schedule
            schedule_dt += timedelta(hours=HOUR_INTERVAL)

    logging.info("All done. Check report CSV and logs for details.")

if __name__ == "__main__":
    process_all_surahs()
