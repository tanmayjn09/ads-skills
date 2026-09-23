"""
Shared LinkedIn Marketing API client.
All scripts import get_session() and get_account_id() from here.
Auto-refreshes the access token on 401 using the stored refresh token.
"""

import os
import sys
import requests
from pathlib import Path
from config import get_config, validate_config

BASE_URL = "https://api.linkedin.com/rest"
_ROOT_ENV = Path(__file__).parents[4] / ".env"


def _refresh_access_token() -> str:
    """Use the refresh token to get a new access token and save it to root .env."""
    config = get_config()
    refresh_token = os.getenv("LINKEDIN_REFRESH_TOKEN", "")
    if not refresh_token:
        print("ERROR: No refresh token found. Run: python oauth_server.py")
        sys.exit(1)

    resp = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if resp.status_code != 200:
        print(f"ERROR: Token refresh failed: {resp.status_code} {resp.text}")
        print("Run: python oauth_server.py  -- to re-authorize.")
        sys.exit(1)

    data = resp.json()
    new_access_token = data.get("access_token", "")
    new_refresh_token = data.get("refresh_token", refresh_token)

    # Update root .env with new tokens
    env_path = _ROOT_ENV
    with open(env_path, "r") as f:
        lines = f.readlines()

    updated = {"LINKEDIN_ACCESS_TOKEN": False, "LINKEDIN_REFRESH_TOKEN": False}
    new_lines = []
    for line in lines:
        if line.startswith("LINKEDIN_ACCESS_TOKEN="):
            new_lines.append(f"LINKEDIN_ACCESS_TOKEN={new_access_token}\n")
            updated["LINKEDIN_ACCESS_TOKEN"] = True
        elif line.startswith("LINKEDIN_REFRESH_TOKEN="):
            new_lines.append(f"LINKEDIN_REFRESH_TOKEN={new_refresh_token}\n")
            updated["LINKEDIN_REFRESH_TOKEN"] = True
        else:
            new_lines.append(line)

    for key, was_updated in updated.items():
        if not was_updated:
            value = new_access_token if key == "LINKEDIN_ACCESS_TOKEN" else new_refresh_token
            if value:
                new_lines.append(f"{key}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)

    # Update in-process env so subsequent calls in the same run use the new token
    os.environ["LINKEDIN_ACCESS_TOKEN"] = new_access_token
    os.environ["LINKEDIN_REFRESH_TOKEN"] = new_refresh_token

    print("Access token refreshed automatically.")
    return new_access_token


def _build_session(access_token: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": "202601",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    })
    return session


class _AutoRefreshSession:
    """Wraps requests.Session and silently refreshes the token on 401."""

    def __init__(self, access_token: str):
        self._session = _build_session(access_token)

    def _handle_response(self, resp, method, url, **kwargs):
        if resp.status_code == 401:
            new_token = _refresh_access_token()
            self._session = _build_session(new_token)
            resp = getattr(self._session, method)(url, **kwargs)
        return resp

    def get(self, url, **kwargs):
        resp = self._session.get(url, **kwargs)
        return self._handle_response(resp, "get", url, **kwargs)

    def post(self, url, **kwargs):
        resp = self._session.post(url, **kwargs)
        return self._handle_response(resp, "post", url, **kwargs)

    def patch(self, url, **kwargs):
        resp = self._session.patch(url, **kwargs)
        return self._handle_response(resp, "patch", url, **kwargs)

    def delete(self, url, **kwargs):
        resp = self._session.delete(url, **kwargs)
        return self._handle_response(resp, "delete", url, **kwargs)


def get_session() -> _AutoRefreshSession:
    """Return an auto-refreshing session with LinkedIn API headers."""
    config = get_config()

    missing = validate_config(config)
    if missing:
        print(f"ERROR: Missing credentials in .env: {', '.join(missing)}")
        print("Run: python oauth_server.py  -- to generate an access token.")
        sys.exit(1)

    return _AutoRefreshSession(config["access_token"])


def get_account_id() -> str:
    """Return the LinkedIn ad account ID from config."""
    config = get_config()
    return config["account_id"]
