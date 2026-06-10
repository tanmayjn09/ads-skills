# Reddit Ads API v3 — Reference

## Auth

- App type: **web app** (NOT script — client_credentials doesn't work for web apps)
- Flow: authorization_code → exchange for access + refresh token
- Authorize URL: `https://www.reddit.com/api/v1/authorize?client_id=CLIENT_ID&response_type=code&state=STATE&redirect_uri=REDIRECT_URI&duration=permanent&scope=adsread`
- Token URL: `POST https://www.reddit.com/api/v1/access_token`
- Refresh: `grant_type=refresh_token&refresh_token=REFRESH_TOKEN` with Basic auth (client_id:client_secret)
- Access token expires in 24h; use refresh token for subsequent runs

## Base URL

```
https://ads-api.reddit.com/api/v3
```

## Hierarchy

```
/me  →  /me/businesses  →  /businesses/{id}/ad_accounts  →  /ad_accounts/{id}/campaigns  →  /ad_accounts/{id}/ads
```

## Sprinto Account IDs

| Item | ID |
|------|----|
| Business | `31afc9de-6bc2-4ec0-9dbe-af923e177ed8` |
| Ad Account | `a2_hddc02ztvwoo` (SprintoGRC) |

## Key Endpoints

| Endpoint | Method | Notes |
|----------|--------|-------|
| `/me` | GET | Returns user identity |
| `/me/businesses` | GET | Lists businesses |
| `/businesses/{id}/ad_accounts` | GET | Lists ad accounts |
| `/ad_accounts/{id}/campaigns` | GET | `page.size` up to 1000 |
| `/ad_accounts/{id}/ads` | GET | `page.size` up to 1000 |
| `/ad_accounts/{id}/reports` | POST | Reporting API |

## Reporting API

**Request body:**
```json
{
  "data": {
    "starts_at": "2026-01-01T00:00:00Z",
    "ends_at": "2026-06-01T00:00:00Z",
    "fields": ["CLICKS", "IMPRESSIONS", "SPEND"],
    "breakdowns": ["CAMPAIGN_ID", "DATE"]
  }
}
```

**Critical quirks:**
- Datetime format must be `YYYY-MM-DDTHH:00:00Z` (ISO 8601 with Z, hourly boundary only)
- `2026-06-10` (date-only) → 400 error; `2026-06-10T23:59:59Z` → 400 error; `2026-06-10T00:00:00Z` → works
- SPEND field is in **microdollars** — divide by 1,000,000 for USD
- ECPM field is also in microdollars — divide by 1,000,000
- Conversion total values: divide by 100
- `CAMPAIGN_NAME` is NOT a valid breakdown — fetch campaign names separately via `/campaigns`
- Valid breakdowns: `AD_ACCOUNT_ID`, `AD_GROUP_ID`, `AD_ID`, `CAMPAIGN_ID`, `COUNTRY`, `DATE`, `HOUR`, `GENDER`, `AGE`, `KEYWORD`, `PLACEMENT`, `OS_TYPE`, `SUBREDDIT`, etc.
- DATE breakdown returns both `date` (YYYY-MM-DD) and `hour` fields

## Conversion Fields

Reddit has 533 valid reporting fields. For B2B use (Sprinto):
- `KEY_CONVERSION_TOTAL_COUNT` — total key conversions (works, has real data for Sprinto)
- `KEY_CONVERSION_ECPA` — cost per key conversion in microdollars (÷1,000,000)
- `CONVERSION_LEAD_CLICKS` — click-through lead conversions (0 for Sprinto)
- `REDDIT_LEADS` — native Reddit lead gen (0 for Sprinto)

Compute CPA manually: `spend_usd / key_conversion_total_count`

**Note:** Reddit `key_conversion_ecpa` is also in microdollars, so compute CPA from spend/conv instead.

## Creative Thumbnails

Reddit ads are promoted posts — creative images live in the Reddit post, not in the Ads API:
- `preview_url` is always `null` in the ads endpoint
- No `/creatives` endpoint exists (404)
- Public API (`reddit.com/by_id/{post_id}.json`) returns 403 for promoted posts
- OAuth API with `adsread` scope returns 403 for `/api/info`
- Adding `read` scope to refresh request is ignored (scope is fixed at auth time)
- **Resolution**: Re-auth with `scope=adsread+read`. Use `oauth.reddit.com/api/info?id={post_id}` to fetch post data. New refresh token in `.env`.

**CRITICAL — CDN auth:** Do NOT send the OAuth Bearer token when downloading from `i.redd.it`, `preview.redd.it`, or `external-preview.redd.it`. These are public CDNs — the auth header causes `400 Bad Request`. Use empty `{}` headers for all CDN fetches.

**Thumbnail candidate priority (best → fallback):**
1. `post.url` if starts with `https://i.redd.it/` — stable, full-res, no auth, no expiry
2. `https://i.redd.it/{filename}` extracted from `src_url` or `thumb` via regex — full-res for Reddit-hosted images
3. Signed resolutions largest→smallest — download immediately (external-preview signed URLs expire fast)
4. `post.thumbnail` (140px) — final fallback

## Rate Limits

- Campaign read endpoints: 400 req/60s
- Reporting API: 60 req/60s

## Pagination

- `page.size` must be a **query parameter on the POST URL** (`?page.size=1000`), NOT in the request body — putting it in the body silently returns 0 results
- `next_url` pagination via GET returns 404 for ad-level + DATE breakdowns (broken)
- **Workaround**: use per-preset queries without DATE breakdown (no pagination needed)
  - Campaign-level + DATE: 770 rows for full history, fits in `page.size=1000` ✓
  - Ad-level + DATE: fails pagination → use per-preset totals without DATE instead

## Credentials Storage

Store in `.claude/skills/google-ads/scripts/.env` (loaded first before linkedin env which has placeholder Google values):
```
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_REFRESH_TOKEN=...
REDDIT_AD_ACCOUNT_ID=...
```

## Known Bugs Fixed

- **App type**: Creating app as "script" type fails — must use "web app" type with authorization_code flow
- **Redirect URI typo**: App had `hhtps://sprinto.com` (typo) — corrected to `https://sprinto.com`
- **Wrong version**: Was calling `/api/v2.0/` — correct is `/api/v3/`
- **Wrong first endpoint**: `/businesses` doesn't exist — use `/me/businesses`
