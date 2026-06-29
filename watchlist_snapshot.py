"""
Snapshot a fixed watchlist of tickers in one run. Designed to be triggered
on a schedule (e.g. via cron) so your database builds daily history
automatically without you running qt_chain.py by hand for each ticker.

Edit WATCHLIST below to whatever tickers you want tracked.

Usage (manual test):
    python3 watchlist_snapshot.py

Usage (cron — see bottom of this file for setup instructions):
    runs automatically once scheduled
"""

from __future__ import annotations

import time
import traceback
from datetime import datetime

from qt_chain import get_full_chain
from qt_db import init_db, save_snapshot

# Edit this list to whatever tickers you want tracked daily.
WATCHLIST = [
    "AAPL",
    "NBIS",
]

NUM_EXPIRATIONS = 12  # how many upcoming expirations to pull per ticker

# Small delay between tickers to avoid hammering the API back-to-back.
DELAY_BETWEEN_TICKERS_SECONDS = 3


def run_watchlist_snapshot():
    init_db()
    print(f"=== Watchlist snapshot run started: {datetime.now().isoformat()} ===")

    results = {}
    for symbol in WATCHLIST:
        print(f"\n--- {symbol} ---")
        try:
            df = get_full_chain(symbol, num_expirations=NUM_EXPIRATIONS)
            save_snapshot(df, symbol=symbol)
            results[symbol] = f"OK — {len(df)} rows"
        except Exception as e:
            # Don't let one bad ticker kill the whole run — log it and
            # keep going so the rest of the watchlist still gets saved.
            print(f"FAILED for {symbol}: {e}")
            traceback.print_exc()
            results[symbol] = f"FAILED — {e}"

        time.sleep(DELAY_BETWEEN_TICKERS_SECONDS)

    print(f"\n=== Run summary ({datetime.now().isoformat()}) ===")
    for symbol, status in results.items():
        print(f"  {symbol}: {status}")


if __name__ == "__main__":
    run_watchlist_snapshot()


# -----------------------------------------------------------------------
# CRON SETUP (Mac):
#
# 1. Find the full path to python3 and this script:
#      which python3
#      pwd   (run this while inside the options_tracker folder)
#
# 2. Open your crontab for editing:
#      crontab -e
#
# 3. Add a line like this (runs every weekday at 4:15pm, after market close):
#      15 16 * * 1-5 cd /full/path/to/options_tracker && /full/path/to/python3 watchlist_snapshot.py >> snapshot_log.txt 2>&1
#
#    Adjust the time (minute hour * * weekday) to whatever schedule you want.
#    "1-5" means Monday-Friday only.
#
# 4. Save and exit. Cron will now run this automatically. Check
#    snapshot_log.txt in the options_tracker folder to confirm it's running
#    and to debug if something fails (cron jobs run with limited environment,
#    so if it fails when scheduled but works manually, it's often a PATH issue —
#    using full paths as shown above avoids that).
#
# 5. IMPORTANT: your QT_REFRESH_TOKEN auth is handled automatically via
#    qt_token.json (created the first time you ran qt_auth.py), so cron
#    doesn't need the env var set — it'll read/refresh from that file.
#    Just make sure qt_token.json stays in this folder and isn't deleted.
# -----------------------------------------------------------------------
