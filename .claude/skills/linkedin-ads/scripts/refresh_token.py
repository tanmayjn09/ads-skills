"""
Refresh LinkedIn access token using saved refresh token.
Run this when you get a 401 — no browser required.
Refresh tokens last 365 days. Access tokens last 60 days.

Usage:
    python refresh_token.py
"""
import requests
import os
from pathlib import Path
from dotenv import load_dotenv

_root_env = Path(__file__).parents[4] / ".env"
_local_env = Path(__file__).parent / ".env"
load_dotenv(_root_env)
load_dotenv(_local_env)

CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("LINKEDIN_REFRESH_TOKEN")
ENV_PATH = _root_env


def refresh():
    if not REFRESH_TOKEN:
        print("ERROR: No LINKEDIN_REFRESH_TOKEN found in .env")
        print("Run oauth_server.py to do the full OAuth flow first.")
        return False

    resp = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if resp.status_code != 200:
        print(f"ERROR: {resp.status_code} {resp.text}")
        print("Refresh token may also be expired (>365 days). Run oauth_server.py.")
        return False

    data = resp.json()
    new_access_token = data.get("access_token", "")
    new_refresh_token = data.get("refresh_token", REFRESH_TOKEN)

    with open(ENV_PATH, "r") as f:
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

    with open(ENV_PATH, "w") as f:
        f.writelines(new_lines)

    print("Access token refreshed and saved.")
    expires_in = data.get("expires_in", 5183999)
    print(f"New token expires in ~{expires_in // 86400} days.")
    return True


if __name__ == "__main__":
    success = refresh()
    if not success:
        exit(1)
