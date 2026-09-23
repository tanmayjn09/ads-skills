"""
Weekly Portco + VC + ROI report writer.

Usage:
    python3 weekly_report.py --week-ending 2026-09-18

Fetches LinkedIn data for the week ending on the given date (Mon-Sun),
finds the matching column in the Weekly Report tab by date header,
and writes Spend / Impressions / Clicks / Engagement rate for:
  - Portco LinkedIn ads  (rows 5-8)
  - VC brand ads         (rows 10-13)
  - ROI-report-derived   (rows 15-18)
"""

import sys
import argparse
from datetime import datetime, timedelta
from urllib.parse import quote
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from client import get_session, BASE_URL

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ── Config ────────────────────────────────────────────────────────────────────

ACCOUNT = '509954586'
SHEET_ID = '1vfDHU6jm5fulAD1Zxs8YBUeSG2ppvteAqQyUTkn7LcM'
TAB = 'Weekly Report'
HEADER_ROW = 3       # row with "Week ending XX-Sep" headers
DATA_START_COL = 9   # column I = index 9 (1-based)

PORTCO_IDS = [
    '757702203','810050083','811051903','812056653','757101503',
    '757202383','757302423','757602173','758001463','809904993',
    '810353093','810735453','811435133',
]
VC_IDS = [
    '729009523','727609963','769602503','823613073','823813133','848313313','888510303',
]
ROI_CREATIVE_IDS = ['1521301163','1521361633','1521391413','1448077033']

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid',
]
TOKEN_PATH = Path(__file__).parent / 'sheets_token.json'

# ── Auth ──────────────────────────────────────────────────────────────────────

def get_sheets_service():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            sys.path.insert(0, str(Path(__file__).parents[4] / '.claude/skills/google-ads/scripts'))
            from config import get_config
            cfg = get_config()
            client_config = {'installed': {
                'client_id': cfg['client_id'], 'client_secret': cfg['client_secret'],
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token',
                'redirect_uris': ['urn:ietf:wg:oauth:2.0:oob', 'http://localhost'],
            }}
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=3001, login_hint='tanmayj@sprinto.com')
        with open(TOKEN_PATH, 'w') as f:
            f.write(creds.to_json())
    return build('sheets', 'v4', credentials=creds)

# ── LinkedIn fetch ────────────────────────────────────────────────────────────

def fetch_metrics(session, ids, start, end, pivot='CAMPAIGN'):
    encoded_account = quote(f'urn:li:sponsoredAccount:{ACCOUNT}', safe='')
    if pivot == 'CREATIVE':
        id_param = ','.join(quote(f'urn:li:sponsoredCreative:{i}', safe='') for i in ids)
        id_key = 'creatives'
    else:
        id_param = ','.join(quote(f'urn:li:sponsoredCampaign:{i}', safe='') for i in ids)
        id_key = 'campaigns'

    date_range = (
        f'(start:(year:{start.year},month:{start.month},day:{start.day}),'
        f'end:(year:{end.year},month:{end.month},day:{end.day}))'
    )
    query = (
        f'q=analytics&pivot={pivot}&timeGranularity=ALL'
        f'&dateRange={date_range}'
        f'&accounts=List({encoded_account})'
        f'&{id_key}=List({id_param})'
        f'&fields=impressions,clicks,costInLocalCurrency,totalEngagements,pivotValues'
    )
    r = session.get(f'{BASE_URL}/adAnalytics?{query}')
    if r.status_code != 200:
        print(f'  WARNING: {pivot} fetch returned {r.status_code}')
        return {'spend': 0.0, 'impressions': 0, 'clicks': 0, 'engagements': 0}

    total = {'spend': 0.0, 'impressions': 0, 'clicks': 0, 'engagements': 0}
    for d in r.json().get('elements', []):
        total['spend']       += float(d.get('costInLocalCurrency', 0) or 0)
        total['impressions'] += int(d.get('impressions', 0) or 0)
        total['clicks']      += int(d.get('clicks', 0) or 0)
        total['engagements'] += int(d.get('totalEngagements', 0) or 0)
    return total

# ── Sheet helpers ─────────────────────────────────────────────────────────────

def col_letter(n):
    """1-based column index to letter(s). 1=A, 9=I, 27=AA."""
    s = ''
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s

def find_column(service, week_ending: datetime) -> str:
    """Return column letter matching this week-ending date in the header row."""
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f'{TAB}!{col_letter(DATA_START_COL)}{HEADER_ROW}:Z{HEADER_ROW}'
    ).execute()
    headers = result.get('values', [[]])[0]

    # Header format: "Week ending\n11-Sep" or "Week ending 11-Sep" — match day+month
    target = week_ending.strftime('%-d-%b')  # e.g. "11-Sep"
    for i, h in enumerate(headers):
        if target in str(h):
            return col_letter(DATA_START_COL + i)

    raise ValueError(
        f'Column for week ending {target} not found in header row. '
        f'Headers found: {headers}'
    )

def eng_rate(t):
    if t['impressions']:
        return f'{t["engagements"] / t["impressions"] * 100:.2f}%'
    return '0%'

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--week-ending', required=True,
                        help='Last day of the week, e.g. 2026-09-18')
    args = parser.parse_args()

    week_end = datetime.strptime(args.week_ending, '%Y-%m-%d')
    week_start = week_end - timedelta(days=6)
    print(f'Week: {week_start.strftime("%b %d")} – {week_end.strftime("%b %d, %Y")}')

    print('Authenticating Google Sheets...')
    service = get_sheets_service()

    print('Finding column...')
    col = find_column(service, week_end)
    print(f'  Column: {col} (week ending {week_end.strftime("%-d-%b")})')

    print('Fetching LinkedIn data...')
    session = get_session()
    portco = fetch_metrics(session, PORTCO_IDS, week_start, week_end)
    vc     = fetch_metrics(session, VC_IDS,     week_start, week_end)
    roi    = fetch_metrics(session, ROI_CREATIVE_IDS, week_start, week_end, pivot='CREATIVE')

    print(f'  Portco: ${portco["spend"]:.2f}  {portco["impressions"]:,} impr  {portco["clicks"]} clicks  {eng_rate(portco)}')
    print(f'  VC:     ${vc["spend"]:.2f}  {vc["impressions"]:,} impr  {vc["clicks"]} clicks  {eng_rate(vc)}')
    print(f'  ROI:    ${roi["spend"]:.2f}  {roi["impressions"]:,} impr  {roi["clicks"]} clicks  {eng_rate(roi)}')

    print('Writing to sheet...')
    updates = [
        # Portco rows 5-8
        (f'{TAB}!{col}5', [[portco['spend']]]),
        (f'{TAB}!{col}6', [[portco['impressions']]]),
        (f'{TAB}!{col}7', [[portco['clicks']]]),
        (f'{TAB}!{col}8', [[eng_rate(portco)]]),
        # VC rows 10-13
        (f'{TAB}!{col}10', [[vc['spend']]]),
        (f'{TAB}!{col}11', [[vc['impressions']]]),
        (f'{TAB}!{col}12', [[vc['clicks']]]),
        (f'{TAB}!{col}13', [[eng_rate(vc)]]),
        # ROI rows 15-18
        (f'{TAB}!{col}15', [[roi['spend']]]),
        (f'{TAB}!{col}16', [[roi['impressions']]]),
        (f'{TAB}!{col}17', [[roi['clicks']]]),
        (f'{TAB}!{col}18', [[eng_rate(roi)]]),
    ]
    data = [{'range': r, 'values': v} for r, v in updates]
    result = service.spreadsheets().values().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={'valueInputOption': 'USER_ENTERED', 'data': data}
    ).execute()
    print(f'Done. {result["totalUpdatedCells"]} cells written to column {col}.')


if __name__ == '__main__':
    main()
