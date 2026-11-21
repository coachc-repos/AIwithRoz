#!/usr/bin/env python3
"""
One-shot Perfect Game tournament scrape + Azure Data Lake upload.

Replicates the console UI's "Perfect Game Tournament Search" → run search →
auto-upload, but with FIXED filters and NO prompts, so it can be launched by a
double-clickable .command on the Desktop.

Filters (edit the constants below if you want different defaults):
    State: TX | City: Houston | Radius: 50 mi | Age: 11U | Sport: Baseball

Upload target: linedrivestorage / tournament-data  (Azure Data Lake).
Requires: Chrome installed, `az login` active (for the upload), and the
selenium + beautifulsoup4 packages (already in venv314).
"""

import os
import sys
from pathlib import Path

# --- Fixed search filters (change here if needed) --------------------------
STATE = "TX"
CITY = "Houston"
RADIUS = 50
AGE_GROUP = "11U"
SPORT_TYPE = "Baseball"
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent
os.chdir(REPO)
# Make the project + the azure storage module importable (same as the menu does)
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "linedrive_azure" / "storage"))

try:
    from batch_scrapers.perfect_game.perfect_game_scraper import PerfectGameScraper
    from batch_scrapers.perfect_game.filters import FilterBuilder
    from azure_storage import AzureDataLakeUploader
except Exception as e:  # pragma: no cover - surfaced to the user in Terminal
    print(f"❌ Could not import scraper modules: {e}")
    sys.exit(3)


def main() -> int:
    print("=" * 60)
    print("🏆 PERFECT GAME TOURNAMENT SCRAPE  (automated, no prompts)")
    print("=" * 60)
    print(f"📍 {CITY}, {STATE}  ({RADIUS} miles)   👥 {AGE_GROUP} {SPORT_TYPE}")
    print("-" * 60)

    # Build filters exactly like the console menu (FilterBuilder).
    fb = FilterBuilder()
    fb.set_location(STATE, CITY, RADIUS)
    fb.set_age_group(AGE_GROUP)
    fb.set_sport(SPORT_TYPE)
    filters = fb.get_filters()

    # Run the search (headless Chrome).
    print("⏳ Searching Perfect Game (headless browser)…")
    scraper = PerfectGameScraper(headless=True, debug=True)
    results = scraper.search_tournaments(filters)

    if not results.get("success"):
        print(f"\n❌ Search failed after "
              f"{results.get('search_duration', 0)}s: {results.get('error')}")
        return 1

    tournaments = results.get("tournaments", []) or []
    print(f"\n✅ Found {len(tournaments)} tournaments "
          f"in {results.get('search_duration', 0)}s")

    if not tournaments:
        print("📭 No tournaments matched — nothing to upload.")
        return 0

    # Merge into the de-duplicated master (only NEW tournaments are stored).
    print("\n☁️  Merging into the de-duplicated master "
          "(linedrivestorage/tournament-data/curated)…")
    try:
        uploader = AzureDataLakeUploader()
    except Exception as e:
        print(f"❌ Azure Data Lake unavailable: {e}")
        print("   Fix: open Terminal and run  `az login`  then try again.")
        return 2

    res = uploader.upload_unique(tournaments, run_type="automated")
    new, skipped, total = res["new"], res["skipped"], res["total_unique"]
    if new > 0:
        print(f"✅ Added {new} new tournament(s); skipped {skipped} duplicate(s).")
        print(f"   Master now holds {total} unique tournaments.")
        print(f"   JSON: {res.get('raw_url')}")
        print(f"   CSV : {res.get('processed_url')}")
        return 0
    if res.get("raw_url") is None and skipped == 0 and total == 0 and not uploader.blob_service_client:
        print("❌ Upload failed — check the Azure connection (try `az login`).")
        return 2
    print(f"🟰 No new tournaments — all {skipped} already stored. "
          f"Master unchanged at {total} unique.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
