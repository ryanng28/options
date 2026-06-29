# Options Tracker — Step 1: Questrade Connection Test

This is the first piece of the build: confirm we can authenticate with
Questrade and pull a live options chain with volume/OI/greeks.

## Setup

1. **Activate the API on your Questrade account:**
   - Log in to Questrade
   - Click your name (top right) → **API Centre**
   - Click **Activate API**, agree to the terms
   - Click **Generate new token** (manual authorization)
   - Copy the token shown — this is your one-time refresh token (it's only
     valid for a short window and is single-use, so don't generate it until
     you're ready to use it immediately)

2. **Install dependencies:**
   ```bash
   pip install requests pandas --break-system-packages
   ```

3. **Set your refresh token as an environment variable:**
   ```bash
   export QT_REFRESH_TOKEN=paste_your_token_here
   ```

4. **Test the connection:**
   ```bash
   python qt_auth.py
   ```
   If this prints your account info (status 200 + JSON), auth works.
   It will also create a `qt_token.json` file — **keep this file private**,
   it contains your live access/refresh tokens. After this first run you
   don't need to set QT_REFRESH_TOKEN again; the script reads from this file.

5. **Test the options chain fetch:**
   ```bash
   python qt_chain.py AAPL
   ```
   This pulls the full chain for AAPL, prints the top 15 contracts by volume,
   and saves everything to `AAPL_chain_snapshot.csv`.

## Notes / things to watch for

- **Refresh token rotation:** Questrade issues a brand-new refresh token every
  time the old one is redeemed. `qt_auth.py` handles this automatically by
  saving the new one to `qt_token.json` each time — but if that file ever
  gets out of sync (e.g. you run the script from two places at once), you'll
  need to generate a fresh manual token from the API Centre.
- **Market data delay:** depending on your account's market data subscriptions,
  quotes may be delayed rather than real-time. If `volume`/`openInterest`
  come back as `None` or look stale, that's the most likely cause — worth
  checking your Questrade market data permissions.
- **Rate limits:** Questrade allows a generous but finite number of requests
  per account per period. For a single ticker's chain this is a non-issue;
  if we later scan many tickers we'll want to throttle/batch carefully.

## Once this works

Next steps once you confirm the connection:
1. Wrap this into a scheduled snapshot script that appends to a SQLite db
2. Build the strike × expiration volume heatmap (your original ask)
3. Layer on the GEX/exposure calculation
4. Build the Streamlit dashboard on top

Let me know what happens when you run steps 4 and 5 above — especially if
you hit an error, paste it back and I'll fix it.
