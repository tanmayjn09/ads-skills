"""
Write weekly Portco + VC data to the Google Sheet.
First run: opens browser for Google OAuth (Sheets scope). Token saved to sheets_token.json.
Subsequent runs: uses saved token, no browser needed.

Usage:
    python3 write_sheet.py
"""
import sys
import os
import json
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
TOKEN_PATH = Path(__file__).parent / 'sheets_token.json'
SHEET_ID = '1vfDHU6jm5fulAD1Zxs8YBUeSG2ppvteAqQyUTkn7LcM'  # native Sheets copy (l not I)
TAB = 'Weekly Report'

# Load Google Ads client_id/secret as the OAuth app
sys.path.insert(0, str(Path(__file__).parents[4] / '.claude/skills/google-ads/scripts'))
from config import get_config as get_ads_config

def get_credentials():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            cfg = get_ads_config()
            client_config = {
                'installed': {
                    'client_id': cfg['client_id'],
                    'client_secret': cfg['client_secret'],
                    'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                    'token_uri': 'https://oauth2.googleapis.com/token',
                    'redirect_uris': ['urn:ietf:wg:oauth:2.0:oob', 'http://localhost'],
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=3001)
        with open(TOKEN_PATH, 'w') as f:
            f.write(creds.to_json())
    return creds


def write_data(service, updates):
    data = [{'range': r, 'values': v} for r, v in updates]
    body = {'valueInputOption': 'USER_ENTERED', 'data': data}
    result = service.spreadsheets().values().batchUpdate(
        spreadsheetId=SHEET_ID, body=body
    ).execute()
    return result['totalUpdatedCells']


def main():
    print('Authenticating with Google Sheets...')
    creds = get_credentials()
    service = build('sheets', 'v4', credentials=creds)

    # Column H = Input (leave blank). Week columns: I=Sep11, J=Sep18, K=Sep25
    updates = [
        # Portco
        (f'{TAB}!I5:K5',  [[474.61,  546.04,  282.56]]),    # Spend
        (f'{TAB}!I6:K6',  [[6230,    6493,    3233]]),       # Impressions
        (f'{TAB}!I7:K7',  [[26,      25,      13]]),         # Clicks
        (f'{TAB}!I8:K8',  [['2.20%', '3.40%', '3.12%']]),  # Engagement rate
        # VC
        (f'{TAB}!I10:K10', [[408.32,  426.93,  274.89]]),   # Spend
        (f'{TAB}!I11:K11', [[463,     492,     348]]),       # Impressions
        (f'{TAB}!I12:K12', [[9,       13,      7]]),         # Clicks
        (f'{TAB}!I13:K13', [['1.94%', '2.64%', '2.01%']]), # Engagement rate
    ]

    print('Writing to sheet...')
    total = write_data(service, updates)
    print(f'Done. Updated {total} cells in "{TAB}" tab.')
    print(f'Sheet: https://docs.google.com/spreadsheets/d/{SHEET_ID}')


if __name__ == '__main__':
    main()
