"""
Questrade OAuth2 authentication handler.

How it works:
1. You generate a refresh token from Questrade's API Centre (one-time, manual).
2. This script exchanges it for an access token + api_server URL.
3. Questrade issues a NEW refresh token every time you redeem one (single-use).
   This script automatically saves the new refresh token to disk so you
   never have to manually generate one again, as long as you keep using
   this script to refresh.

Usage:
    from qt_auth import QuestradeAuth
    auth = QuestradeAuth()
    session = auth.get_session()  # returns a requests.Session with auth header set
    api_server = auth.api_server  # base URL for API calls
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

import requests

TOKEN_FILE = Path(__file__).parent / "qt_token.json"
TOKEN_URL = "https://login.questrade.com/oauth2/token"


class QuestradeAuth:
    def __init__(self, initial_refresh_token: Optional[str] = None):
        self.access_token = None
        self.api_server = None
        self.refresh_token = None
        self.expires_at = 0

        if TOKEN_FILE.exists():
            self._load_token_file()
        elif initial_refresh_token:
            self.refresh_token = initial_refresh_token
        else:
            env_token = os.environ.get("QT_REFRESH_TOKEN")
            if env_token:
                self.refresh_token = env_token
            else:
                raise RuntimeError(
                    "No token file found and no refresh token provided. "
                    "Either pass initial_refresh_token=, set QT_REFRESH_TOKEN "
                    "env var, or generate a token in Questrade's API Centre."
                )

        self._refresh()

    def _load_token_file(self):
        data = json.loads(TOKEN_FILE.read_text())
        self.refresh_token = data["refresh_token"]
        self.access_token = data.get("access_token")
        self.api_server = data.get("api_server")
        self.expires_at = data.get("expires_at", 0)

    def _save_token_file(self):
        TOKEN_FILE.write_text(
            json.dumps(
                {
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                    "api_server": self.api_server,
                    "expires_at": self.expires_at,
                },
                indent=2,
            )
        )

    def _refresh(self):
        """Exchange the current refresh token for a new access token.
        Questrade rotates the refresh token on every use, so we must
        save the new one immediately or we'll get locked out."""
        resp = requests.get(
            TOKEN_URL,
            params={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Questrade token refresh failed ({resp.status_code}): {resp.text}\n"
                "Your refresh token may be expired/used already. Generate a new "
                "one in Questrade's API Centre and delete qt_token.json, then retry."
            )

        data = resp.json()
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]  # rotated, must persist
        self.api_server = data["api_server"].rstrip("/")
        self.expires_at = time.time() + data["expires_in"] - 30  # 30s safety buffer
        self._save_token_file()

    def get_session(self) -> requests.Session:
        """Returns a requests.Session pre-configured with a valid auth header.
        Auto-refreshes if the access token has expired."""
        if time.time() >= self.expires_at:
            self._refresh()

        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {self.access_token}"})
        return session


if __name__ == "__main__":
    # Quick manual test: run this file directly after setting QT_REFRESH_TOKEN
    # to confirm auth works before building anything on top of it.
    token = os.environ.get("QT_REFRESH_TOKEN")
    if not token and not TOKEN_FILE.exists():
        print("Set QT_REFRESH_TOKEN env var first, e.g.:")
        print("  export QT_REFRESH_TOKEN=your_token_here")
        raise SystemExit(1)

    auth = QuestradeAuth(initial_refresh_token=token)
    session = auth.get_session()
    resp = session.get(f"{auth.api_server}/v1/accounts")
    print("Status:", resp.status_code)
    print(resp.json())
