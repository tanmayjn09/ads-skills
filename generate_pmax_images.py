"""
Run anytime to regenerate PMax_Image_Performance.html with current active images.
  python generate_pmax_images.py
"""
import sys, io, base64, requests, json, os
from PIL import Image
from collections import defaultdict
from datetime import date, timedelta
from urllib.parse import quote
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path('.claude/skills/google-ads/scripts/.env'))
load_dotenv(Path('.claude/skills/linkedin-ads/scripts/.env'))

sys.path.insert(0, '.claude/skills/google-ads/scripts')
from client import get_client, get_customer_id

INR_TO_USD = 93.0
THUMB_W    = 360
OUT_FILE   = 'PMax_Image_Performance.html'

# Accounts: (customer_id, login_customer_id, usd_conversion)
ACCOUNTS = [
    ('1403356646', '1403356646', 1/INR_TO_USD),   # Sprinto INR → USD
    ('1960894839', '1960894839', 1.0),             # Sprinto Inc (already USD)
]

QUERY = """
    SELECT campaign.name, asset_group.name,
        asset_group_asset.field_type, asset_group_asset.performance_label,
        asset.id, asset.name,
        asset.image_asset.full_size.url,
        asset.image_asset.full_size.width_pixels,
        asset.image_asset.full_size.height_pixels,
        metrics.impressions, metrics.clicks,
        metrics.conversions, metrics.cost_micros
    FROM asset_group_asset
    WHERE campaign.advertising_channel_type = PERFORMANCE_MAX
    AND campaign.status       = ENABLED
    AND asset_group.status    = ENABLED
    AND asset_group_asset.status = ENABLED
    AND asset_group_asset.field_type IN (
        MARKETING_IMAGE, SQUARE_MARKETING_IMAGE, PORTRAIT_MARKETING_IMAGE
    )
    AND segments.date BETWEEN '2025-06-01' AND '2026-06-30'
"""

# ── Fetch both accounts ────────────────────────────────────────────────────────
from google.ads.googleads.client import GoogleAdsClient
from config import get_config

_cfg = get_config()
_base_creds = {
    "developer_token": _cfg["developer_token"],
    "client_id":       _cfg["client_id"],
    "client_secret":   _cfg["client_secret"],
    "refresh_token":   _cfg["refresh_token"],
    "use_proto_plus":  True,
}

by_asset = defaultdict(lambda: dict(url='', name='', w=0, h=0, field='',
    camps=defaultdict(lambda: dict(conv=0.0, clicks=0, impr=0, cost_usd=0.0, ag='', ags=set()))))
camp_order_conv = defaultdict(float)

for cid, login_id, fx in ACCOUNTS:
    print(f'Fetching account {cid} (login={login_id})…')
    client = GoogleAdsClient.load_from_dict(dict(_base_creds, login_customer_id=login_id))
    svc = client.get_service('GoogleAdsService', version='v21')
    rows = list(svc.search(customer_id=cid, query=QUERY))
    print(f'  {len(rows)} rows')

    for r in rows:
        m = r.metrics; a = r.asset; aga = r.asset_group_asset
        aid = str(a.id)
        d   = by_asset[aid]
        d['url']   = a.image_asset.full_size.url or ''
        d['name']  = a.name or f'Image {aid}'
        d['w']     = a.image_asset.full_size.width_pixels
        d['h']     = a.image_asset.full_size.height_pixels
        d['field'] = aga.field_type.name
        camp = r.campaign.name
        cd   = d['camps'][camp]
        cd['conv']     += m.conversions
        cd['clicks']   += m.clicks
        cd['impr']     += m.impressions
        cd['cost_usd'] += (m.cost_micros / 1e6) * fx
        cd['ag']        = r.asset_group.name
        camp_order_conv[camp] += m.conversions

print(f'PMax: {len(by_asset)} unique images across {len(camp_order_conv)} campaigns')

# ── Fetch PMax video assets ────────────────────────────────────────────────────
PMAX_VIDEO_QUERY = """
    SELECT campaign.name, asset_group.name,
        asset.id, asset.name,
        asset.youtube_video_asset.youtube_video_id,
        metrics.impressions, metrics.clicks,
        metrics.conversions, metrics.cost_micros
    FROM asset_group_asset
    WHERE campaign.advertising_channel_type = PERFORMANCE_MAX
    AND campaign.status       = ENABLED
    AND asset_group.status    = ENABLED
    AND asset_group_asset.status = ENABLED
    AND asset_group_asset.field_type = YOUTUBE_VIDEO
    AND segments.date BETWEEN '2025-06-01' AND '2026-06-30'
"""

for cid, login_id, fx in ACCOUNTS:
    client = GoogleAdsClient.load_from_dict(dict(_base_creds, login_customer_id=login_id))
    svc = client.get_service('GoogleAdsService', version='v21')
    rows = list(svc.search(customer_id=cid, query=PMAX_VIDEO_QUERY))
    print(f'PMax videos {cid}: {len(rows)} rows')
    for r in rows:
        m = r.metrics; a = r.asset; aga = r.asset_group_asset
        aid = str(a.id)
        d = by_asset[aid]
        d['vid_id']   = a.youtube_video_asset.youtube_video_id
        d['name']     = a.name or f'Video {aid}'
        d['field']    = 'YOUTUBE_VIDEO'
        d['is_video'] = True
        camp = r.campaign.name
        cd = d['camps'][camp]
        cd['conv']     += m.conversions
        cd['clicks']   += m.clicks
        cd['impr']     += m.impressions
        cd['cost_usd'] += (m.cost_micros / 1e6) * fx
        cd['ag']        = r.asset_group.name
        camp_order_conv[camp] += m.conversions

n_vids = sum(1 for d in by_asset.values() if d.get('is_video'))
print(f'PMax videos: {n_vids} unique across campaigns')

# ── Fetch Demand Gen campaigns (ad_group_ad_asset_view model) ─────────────────
DG_IMAGE_QUERY = """
    SELECT campaign.name, ad_group.name,
        asset.id, asset.name,
        asset.image_asset.full_size.url,
        asset.image_asset.full_size.width_pixels,
        asset.image_asset.full_size.height_pixels,
        ad_group_ad_asset_view.field_type,
        metrics.impressions, metrics.clicks, metrics.conversions, metrics.cost_micros
    FROM ad_group_ad_asset_view
    WHERE campaign.advertising_channel_type = DEMAND_GEN
    AND campaign.status = ENABLED
    AND ad_group_ad_asset_view.enabled = TRUE
    AND ad_group_ad_asset_view.field_type IN (MARKETING_IMAGE, SQUARE_MARKETING_IMAGE, PORTRAIT_MARKETING_IMAGE, TALL_PORTRAIT_MARKETING_IMAGE)
    AND segments.date BETWEEN '2025-06-01' AND '2026-06-30'
"""

for cid, login_id, fx in ACCOUNTS:
    client = GoogleAdsClient.load_from_dict(dict(_base_creds, login_customer_id=login_id))
    svc = client.get_service('GoogleAdsService', version='v21')
    rows = list(svc.search(customer_id=cid, query=DG_IMAGE_QUERY))
    print(f'Demand Gen {cid}: {len(rows)} image asset rows')
    for r in rows:
        m = r.metrics; a = r.asset; v = r.ad_group_ad_asset_view
        aid = str(a.id)
        d = by_asset[aid]
        if not d['url']:
            d['url']   = a.image_asset.full_size.url or ''
            d['name']  = a.name or f'DG Image {aid}'
            d['w']     = a.image_asset.full_size.width_pixels
            d['h']     = a.image_asset.full_size.height_pixels
            d['field'] = v.field_type.name
        d['is_dg'] = True
        camp = r.campaign.name
        cd = d['camps'][camp]
        # Keep data from the ad group with most impressions — deduplicates across ad groups
        # (same image in multiple ad groups should appear once, like Google Ads campaign view)
        if m.impressions >= cd['impr']:
            cd['conv']     = m.conversions
            cd['clicks']   = m.clicks
            cd['impr']     = m.impressions
            cd['cost_usd'] = (m.cost_micros / 1e6) * fx
            cd['ag']       = r.ad_group.name
        cd['ags'].add(r.ad_group.name)

# Recompute camp_order_conv for DG from deduplicated per-image data
for aid, d in by_asset.items():
    if d.get('is_dg'):
        for camp, cd in d['camps'].items():
            camp_order_conv[camp] += cd['conv']

dg_camp_totals = {}  # kept as empty dict for is_dg detection only

print(f'Total: {len(by_asset)} unique images across {len(camp_order_conv)} campaigns')

# ── Download & embed images ────────────────────────────────────────────────────
def is_blank(img_rgb, threshold=240, min_blank_pct=0.80):
    """Return True if >80% of pixels are near-white — simgad placeholder."""
    import numpy as np
    arr = np.array(img_rgb)
    bright = np.all(arr > threshold, axis=2).sum()
    return bright / arr.shape[0] / arr.shape[1] > min_blank_pct

print('Downloading images…')
import os
from pathlib import Path
STOCK_DIR = Path('stock_images')
STOCK_DIR.mkdir(exist_ok=True)

img_b64 = {}
blank_count = 0
sess = requests.Session()
sess.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1)'})
for i, (aid, d) in enumerate(by_asset.items()):
    # YouTube video thumbnail
    if d.get('is_video'):
        vid_id = d.get('vid_id', '')
        if vid_id:
            thumb_url = f'https://img.youtube.com/vi/{vid_id}/hqdefault.jpg'
            try:
                resp = sess.get(thumb_url, timeout=10); resp.raise_for_status()
                img  = Image.open(io.BytesIO(resp.content)).convert('RGB')
                ratio = THUMB_W / img.width if img.width > THUMB_W else 1
                img  = img.resize((min(THUMB_W, img.width), max(1, int(img.height * ratio))), Image.LANCZOS)
                buf  = io.BytesIO(); img.save(buf, 'JPEG', quality=82)
                img_b64[aid] = 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
            except Exception as e:
                img_b64[aid] = None
                print(f'  WARN: video thumb {aid} ({vid_id}): {e}')
        else:
            img_b64[aid] = None
        continue

    # Check stock_images/ directory first (screenshots from download_stock_images.py)
    stock_path = STOCK_DIR / f'{aid}.jpg'
    if stock_path.exists():
        try:
            img = Image.open(str(stock_path)).convert('RGB')
            ratio = THUMB_W / img.width if img.width > THUMB_W else 1
            img = img.resize((min(THUMB_W, img.width), max(1, int(img.height * ratio))), Image.LANCZOS)
            buf = io.BytesIO(); img.save(buf, 'JPEG', quality=82)
            img_b64[aid] = 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
            continue
        except Exception as e:
            print(f'  WARN: could not load stock image {aid}: {e}')

    url = d['url']
    if not url:
        img_b64[aid] = None
        continue
    try:
        resp = sess.get(url, timeout=10); resp.raise_for_status()
        img  = Image.open(io.BytesIO(resp.content)).convert('RGB')
        if is_blank(img):
            img_b64[aid] = None   # simgad returned a white placeholder
            blank_count += 1
            continue
        ratio = THUMB_W / img.width if img.width > THUMB_W else 1
        img  = img.resize((min(THUMB_W, img.width), max(1, int(img.height * ratio))), Image.LANCZOS)
        buf  = io.BytesIO(); img.save(buf, 'JPEG', quality=82)
        img_b64[aid] = 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        img_b64[aid] = None
        print(f'  WARN: could not download image {aid}: {e}')
    if (i + 1) % 20 == 0:
        print(f'  {i+1}/{len(by_asset)}')
stock_used = sum(1 for aid in img_b64 if img_b64[aid] and (STOCK_DIR / f'{aid}.jpg').exists())
ok = sum(1 for v in img_b64.values() if v)
print(f'Downloaded {ok}/{len(by_asset)} ({stock_used} from stock_images/, {blank_count} stock image placeholders skipped)')

# ── Config ─────────────────────────────────────────────────────────────────────
MULBERRY = '#650A41'
TEXAS    = '#DDF07E'
DARK_BG  = '#1F0214'
LIGHT_BG = '#F6F5F2'
GREY     = '#F5F4F5'

FIELD_SHORT = {
    'MARKETING_IMAGE':               'Landscape',
    'SQUARE_MARKETING_IMAGE':        'Square',
    'PORTRAIT_MARKETING_IMAGE':      'Portrait',
    'TALL_PORTRAIT_MARKETING_IMAGE': 'Vertical',
    'YOUTUBE_VIDEO':                 'Video',
}

camp_order  = sorted(camp_order_conv.keys(), key=lambda x: -camp_order_conv[x])
camp_assets = defaultdict(list)
for aid, d in by_asset.items():
    for camp in d['camps']:
        camp_assets[camp].append(aid)
shared_assets = {aid: d for aid, d in by_asset.items() if len(d['camps']) > 1}
shared_images = {aid: d for aid, d in shared_assets.items() if not d.get('is_video')}
shared_videos = {aid: d for aid, d in shared_assets.items() if d.get('is_video')}

def camp_anchor(camp):
    return 'c-' + camp.replace('|', '').replace(' ', '-').replace('/', '').lower()

# ── Preset datasets for date range controller ─────────────────────────────────
_today = date.today()
_yest  = _today - timedelta(days=1)
PRESETS = [
    ('All', date(2025, 6, 1),            _today),
    ('90D', _today - timedelta(days=90), _yest),
    ('30D', _today - timedelta(days=30), _yest),
    ('7D',  _today - timedelta(days=7),  _yest),
]

def _fetch_pmax_metrics(start, end):
    q = f"""
        SELECT asset.id, campaign.name,
            metrics.impressions, metrics.clicks, metrics.conversions, metrics.cost_micros
        FROM asset_group_asset
        WHERE campaign.advertising_channel_type = PERFORMANCE_MAX
        AND campaign.status = ENABLED AND asset_group.status = ENABLED
        AND asset_group_asset.status = ENABLED
        AND asset_group_asset.field_type IN (MARKETING_IMAGE, SQUARE_MARKETING_IMAGE, PORTRAIT_MARKETING_IMAGE)
        AND segments.date BETWEEN '{start}' AND '{end}'
    """
    res = defaultdict(lambda: defaultdict(lambda: dict(conv=0.0, clicks=0, impr=0, cost_usd=0.0)))
    for cid, login_id, fx in ACCOUNTS:
        client = GoogleAdsClient.load_from_dict(dict(_base_creds, login_customer_id=login_id))
        svc    = client.get_service('GoogleAdsService', version='v21')
        for r in svc.search(customer_id=cid, query=q):
            m = r.metrics; d = res[str(r.asset.id)][r.campaign.name]
            d['conv']     += m.conversions
            d['clicks']   += m.clicks
            d['impr']     += m.impressions
            d['cost_usd'] += (m.cost_micros / 1e6) * fx
    return {aid: dict(camps) for aid, camps in res.items()}

def _fetch_pmax_video_metrics(start, end):
    q = f"""
        SELECT asset.id, campaign.name,
            metrics.impressions, metrics.clicks, metrics.conversions, metrics.cost_micros
        FROM asset_group_asset
        WHERE campaign.advertising_channel_type = PERFORMANCE_MAX
        AND campaign.status = ENABLED AND asset_group.status = ENABLED
        AND asset_group_asset.status = ENABLED
        AND asset_group_asset.field_type = YOUTUBE_VIDEO
        AND segments.date BETWEEN '{start}' AND '{end}'
    """
    res = defaultdict(lambda: defaultdict(lambda: dict(conv=0.0, clicks=0, impr=0, cost_usd=0.0)))
    for cid, login_id, fx in ACCOUNTS:
        client = GoogleAdsClient.load_from_dict(dict(_base_creds, login_customer_id=login_id))
        svc    = client.get_service('GoogleAdsService', version='v21')
        for r in svc.search(customer_id=cid, query=q):
            m = r.metrics; d = res[str(r.asset.id)][r.campaign.name]
            d['conv']     += m.conversions
            d['clicks']   += m.clicks
            d['impr']     += m.impressions
            d['cost_usd'] += (m.cost_micros / 1e6) * fx
    return {aid: dict(camps) for aid, camps in res.items()}

def _fetch_dg_metrics(start, end):
    q = f"""
        SELECT asset.id, campaign.name,
            metrics.impressions, metrics.clicks, metrics.conversions, metrics.cost_micros
        FROM ad_group_ad_asset_view
        WHERE campaign.advertising_channel_type = DEMAND_GEN
        AND campaign.status = ENABLED
        AND ad_group_ad_asset_view.enabled = TRUE
        AND ad_group_ad_asset_view.field_type IN (MARKETING_IMAGE, SQUARE_MARKETING_IMAGE, PORTRAIT_MARKETING_IMAGE, TALL_PORTRAIT_MARKETING_IMAGE)
        AND segments.date BETWEEN '{start}' AND '{end}'
    """
    res = defaultdict(lambda: defaultdict(lambda: dict(conv=0.0, clicks=0, impr=0, cost_usd=0.0)))
    for cid, login_id, fx in ACCOUNTS:
        client = GoogleAdsClient.load_from_dict(dict(_base_creds, login_customer_id=login_id))
        svc    = client.get_service('GoogleAdsService', version='v21')
        for r in svc.search(customer_id=cid, query=q):
            m = r.metrics; d = res[str(r.asset.id)][r.campaign.name]
            if m.impressions >= d['impr']:
                d['conv']     = m.conversions
                d['clicks']   = m.clicks
                d['impr']     = m.impressions
                d['cost_usd'] = (m.cost_micros / 1e6) * fx
    return {aid: dict(camps) for aid, camps in res.items()}


def _fetch_daily_pmax(start, end):
    q = f"""
        SELECT asset.id, campaign.name, segments.date,
            metrics.impressions, metrics.clicks, metrics.conversions, metrics.cost_micros
        FROM asset_group_asset
        WHERE campaign.advertising_channel_type = PERFORMANCE_MAX
        AND campaign.status = ENABLED AND asset_group.status = ENABLED
        AND asset_group_asset.status = ENABLED
        AND asset_group_asset.field_type IN (MARKETING_IMAGE, SQUARE_MARKETING_IMAGE, PORTRAIT_MARKETING_IMAGE)
        AND segments.date BETWEEN '{start}' AND '{end}'
    """
    res = defaultdict(lambda: defaultdict(lambda: {}))
    for cid, login_id, fx in ACCOUNTS:
        client = GoogleAdsClient.load_from_dict(dict(_base_creds, login_customer_id=login_id))
        svc    = client.get_service('GoogleAdsService', version='v21')
        for r in svc.search(customer_id=cid, query=q):
            m  = r.metrics; dt = r.segments.date
            d  = res[str(r.asset.id)][r.campaign.name]
            if dt not in d: d[dt] = [0.0, 0, 0, 0.0]
            d[dt][0] += m.conversions
            d[dt][1] += m.clicks
            d[dt][2] += m.impressions
            d[dt][3] += (m.cost_micros / 1e6) * fx
    return {aid: dict(camps) for aid, camps in res.items()}

def _fetch_daily_pmax_video(start, end):
    q = f"""
        SELECT asset.id, campaign.name, segments.date,
            metrics.impressions, metrics.clicks, metrics.conversions, metrics.cost_micros
        FROM asset_group_asset
        WHERE campaign.advertising_channel_type = PERFORMANCE_MAX
        AND campaign.status = ENABLED AND asset_group.status = ENABLED
        AND asset_group_asset.status = ENABLED
        AND asset_group_asset.field_type = YOUTUBE_VIDEO
        AND segments.date BETWEEN '{start}' AND '{end}'
    """
    res = defaultdict(lambda: defaultdict(lambda: {}))
    for cid, login_id, fx in ACCOUNTS:
        client = GoogleAdsClient.load_from_dict(dict(_base_creds, login_customer_id=login_id))
        svc    = client.get_service('GoogleAdsService', version='v21')
        for r in svc.search(customer_id=cid, query=q):
            m  = r.metrics; dt = r.segments.date
            d  = res[str(r.asset.id)][r.campaign.name]
            if dt not in d: d[dt] = [0.0, 0, 0, 0.0]
            d[dt][0] += m.conversions
            d[dt][1] += m.clicks
            d[dt][2] += m.impressions
            d[dt][3] += (m.cost_micros / 1e6) * fx
    return {aid: dict(camps) for aid, camps in res.items()}

def _fetch_daily_dg(start, end):
    q = f"""
        SELECT asset.id, campaign.name, segments.date,
            metrics.impressions, metrics.clicks, metrics.conversions, metrics.cost_micros
        FROM ad_group_ad_asset_view
        WHERE campaign.advertising_channel_type = DEMAND_GEN
        AND campaign.status = ENABLED
        AND ad_group_ad_asset_view.enabled = TRUE
        AND ad_group_ad_asset_view.field_type IN (MARKETING_IMAGE, SQUARE_MARKETING_IMAGE, PORTRAIT_MARKETING_IMAGE, TALL_PORTRAIT_MARKETING_IMAGE)
        AND segments.date BETWEEN '{start}' AND '{end}'
    """
    res = defaultdict(lambda: defaultdict(lambda: {}))
    for cid, login_id, fx in ACCOUNTS:
        client = GoogleAdsClient.load_from_dict(dict(_base_creds, login_customer_id=login_id))
        svc    = client.get_service('GoogleAdsService', version='v21')
        for r in svc.search(customer_id=cid, query=q):
            m = r.metrics; dt = r.segments.date
            d = res[str(r.asset.id)][r.campaign.name]
            if dt not in d or m.impressions >= d[dt][2]:
                d[dt] = [m.conversions, m.clicks, m.impressions, (m.cost_micros / 1e6) * fx]
    return {aid: dict(camps) for aid, camps in res.items()}

print('Building preset datasets…')
preset_datasets = {}
preset_hints    = {}
for pname, pstart, pend in PRESETS:
    s, e = pstart.isoformat(), pend.isoformat()
    m = _fetch_pmax_metrics(s, e)
    for aid, camps in _fetch_pmax_video_metrics(s, e).items():
        for camp, cd in camps.items():
            if aid not in m: m[aid] = {}
            if camp not in m[aid]: m[aid][camp] = dict(conv=0.0, clicks=0, impr=0, cost_usd=0.0)
            for k in cd: m[aid][camp][k] += cd[k]
    for aid, camps in _fetch_dg_metrics(s, e).items():
        for camp, cd in camps.items():
            if aid not in m: m[aid] = {}
            if camp not in m[aid]: m[aid][camp] = dict(conv=0.0, clicks=0, impr=0, cost_usd=0.0)
            for k in cd: m[aid][camp][k] += cd[k]
    preset_datasets[pname] = m
    preset_hints[pname] = ('Jun 2025 – present' if pname == 'All'
                           else f'{pstart.strftime("%b %d")} – {pend.strftime("%b %d, %Y")}')
    print(f'  {pname}: {sum(len(v) for v in m.values())} asset-camp pairs')

datasets_js = json.dumps(preset_datasets)
hints_js    = json.dumps(preset_hints)

print('Fetching daily data for custom date range…')
_d_start = date(2025, 6, 1).isoformat()
_d_end   = _today.isoformat()
daily_data = _fetch_daily_pmax(_d_start, _d_end)
for aid, camps in _fetch_daily_pmax_video(_d_start, _d_end).items():
    for camp, dates in camps.items():
        if aid not in daily_data:       daily_data[aid] = {}
        if camp not in daily_data[aid]: daily_data[aid][camp] = {}
        for dt, vals in dates.items():
            if dt not in daily_data[aid][camp]: daily_data[aid][camp][dt] = [0.0, 0, 0, 0.0]
            for i in range(4): daily_data[aid][camp][dt][i] += vals[i]
for aid, camps in _fetch_daily_dg(_d_start, _d_end).items():
    for camp, dates in camps.items():
        if aid not in daily_data:         daily_data[aid] = {}
        if camp not in daily_data[aid]:   daily_data[aid][camp] = {}
        for dt, vals in dates.items():
            if dt not in daily_data[aid][camp]: daily_data[aid][camp][dt] = [0.0, 0, 0, 0.0]
            for i in range(4): daily_data[aid][camp][dt][i] += vals[i]
daily_js = json.dumps(daily_data)
print(f'  Daily entries: {sum(len(dates) for camps in daily_data.values() for dates in camps.values())}')

preset_dates_js = json.dumps({n: [s.isoformat(), e.isoformat()] for n, s, e in PRESETS})

# ── Reddit Ads ─────────────────────────────────────────────────────────────────
print('Fetching Reddit Ads data…')

REDDIT_CLIENT_ID      = os.getenv('REDDIT_CLIENT_ID', '')
REDDIT_CLIENT_SECRET  = os.getenv('REDDIT_CLIENT_SECRET', '')
REDDIT_REFRESH_TOKEN  = os.getenv('REDDIT_REFRESH_TOKEN', '')
REDDIT_AD_ACCOUNT_ID  = os.getenv('REDDIT_AD_ACCOUNT_ID', '')
REDDIT_BASE           = 'https://ads-api.reddit.com/api/v3'
REDDIT_UA             = 'SprintoAds/1.0'

def _reddit_access_token():
    r = requests.post(
        'https://www.reddit.com/api/v1/access_token',
        auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
        data={'grant_type': 'refresh_token', 'refresh_token': REDDIT_REFRESH_TOKEN},
        headers={'User-Agent': REDDIT_UA},
    )
    return r.json().get('access_token', '')

def _reddit_report(token, fields, breakdowns, starts_at, ends_at):
    # page.size must be a query param, NOT in the POST body
    hdr = {'Authorization': f'Bearer {token}', 'User-Agent': REDDIT_UA, 'Content-Type': 'application/json'}
    all_metrics = []
    r = requests.post(
        f'{REDDIT_BASE}/ad_accounts/{REDDIT_AD_ACCOUNT_ID}/reports?page.size=1000',
        headers=hdr,
        json={'data': {'starts_at': starts_at, 'ends_at': ends_at,
                       'fields': fields, 'breakdowns': breakdowns}},
    )
    resp = r.json()
    all_metrics.extend(resp.get('data', {}).get('metrics', []))
    next_url = resp.get('pagination', {}).get('next_url')
    while next_url:
        r = requests.get(next_url, headers={'Authorization': f'Bearer {token}', 'User-Agent': REDDIT_UA})
        resp = r.json()
        all_metrics.extend(resp.get('data', {}).get('metrics', []))
        next_url = resp.get('pagination', {}).get('next_url')
    return all_metrics

rd_token = _reddit_access_token()
if not rd_token:
    print('  Reddit: token refresh failed, skipping')
    rd_active_camps  = {}
    rd_active_groups = {}
    rd_active_ads    = {}
    rd_ad_media      = {}
    rd_camp_daily    = {}
    rd_preset_camps  = {}
    rd_preset_ads    = {}
else:
    hdr = {'Authorization': f'Bearer {rd_token}', 'User-Agent': REDDIT_UA}

    # Campaigns — active only
    rc = requests.get(f'{REDDIT_BASE}/ad_accounts/{REDDIT_AD_ACCOUNT_ID}/campaigns?page.size=200', headers=hdr)
    rd_active_camps = {c['id']: c for c in rc.json().get('data', []) if c.get('effective_status') == 'ACTIVE'}

    # Ad groups — active only
    rg = requests.get(f'{REDDIT_BASE}/ad_accounts/{REDDIT_AD_ACCOUNT_ID}/ad_groups?page.size=200', headers=hdr)
    rd_active_groups = {g['id']: g for g in rg.json().get('data', []) if g.get('effective_status') == 'ACTIVE'}

    # Ads — active only
    ra = requests.get(f'{REDDIT_BASE}/ad_accounts/{REDDIT_AD_ACCOUNT_ID}/ads?page.size=200', headers=hdr)
    rd_active_ads = {
        a['id']: {
            'name':        a.get('name', ''),
            'campaign_id': a.get('campaign_id', ''),
            'ad_group_id': a.get('ad_group_id', ''),
            'post_id':     a.get('post_id', ''),
            'post_url':    a.get('post_url', ''),
            'click_url':   a.get('click_url', ''),
        }
        for a in ra.json().get('data', []) if a.get('effective_status') == 'ACTIVE'
    }

    # Fetch post thumbnails and video URLs using read scope
    rd_ad_media = {}  # aid -> {b64, is_video, video_url}
    print(f'  Reddit: fetching thumbnails for {len(rd_active_ads)} ads…')
    for aid, info in rd_active_ads.items():
        post_id = info.get('post_id', '')
        if not post_id:
            continue
        try:
            rp = requests.get('https://oauth.reddit.com/api/info',
                              params={'id': post_id}, headers=hdr, timeout=10)
            if rp.status_code != 200:
                continue
            children = rp.json().get('data', {}).get('children', [])
            if not children:
                continue
            post = children[0]['data']
            # Build candidate list: full-res first, small thumbnail last
            import re as _re
            img_candidates = []
            previews = post.get('preview', {}).get('images', [])
            thumb    = post.get('thumbnail', '').replace('&amp;', '&')
            post_url = post.get('url', '').replace('&amp;', '&')

            # 1. post.url → i.redd.it direct (best: no signature, no auth, full-res)
            if post_url.startswith('https://i.redd.it/'):
                img_candidates.append(post_url)

            if previews:
                src_url = previews[0].get('source', {}).get('url', '').replace('&amp;', '&')
                # 2. i.redd.it via filename from any preview URL (catches external-preview posts)
                m = _re.search(r'(?:preview|external-preview)\.redd\.it/([^?/]+)', src_url)
                if m:
                    cand = f'https://i.redd.it/{m.group(1)}'
                    if cand not in img_candidates:
                        img_candidates.append(cand)
                # 3. i.redd.it from thumbnail URL (may differ for some post types)
                mt = _re.search(r'(?:preview|external-preview)\.redd\.it/([^?/]+)', thumb)
                if mt:
                    cand = f'https://i.redd.it/{mt.group(1)}'
                    if cand not in img_candidates:
                        img_candidates.append(cand)
                # 4. Signed resolutions largest→smallest (external-preview, download immediately)
                for res in reversed(previews[0].get('resolutions', [])):
                    u = res.get('url', '').replace('&amp;', '&')
                    if u and u not in img_candidates: img_candidates.append(u)
                # 5. Full source URL
                if src_url and src_url not in img_candidates:
                    img_candidates.append(src_url)
            # 6. Stable thumbnail (140px) as final fallback
            if thumb and thumb.startswith('http') and thumb not in img_candidates:
                img_candidates.append(thumb)
            # Video URL
            media   = post.get('media') or {}
            rv      = media.get('reddit_video') or {}
            vid_url = rv.get('fallback_url', '').replace('&amp;', '&') if rv else ''
            is_vid  = bool(vid_url)
            # Download first working thumbnail
            # CDN URLs (i.redd.it, preview.redd.it, external-preview.redd.it) must NOT
            # receive the OAuth Bearer token — it causes 400s on the CDN.
            b64 = None
            for img_url in img_candidates:
                cdn_hdr = {} if any(d in img_url for d in ['i.redd.it', 'preview.redd.it']) else hdr
                ir = requests.get(img_url, headers=cdn_hdr, timeout=10)
                if ir.status_code == 200:
                    ct  = ir.headers.get('content-type', 'image/jpeg').split(';')[0]
                    b64 = f'data:{ct};base64,{base64.b64encode(ir.content).decode()}'
                    break
            rd_ad_media[aid] = {'b64': b64, 'is_video': is_vid, 'video_url': vid_url}
        except Exception as e:
            print(f'    WARN thumbnail {aid}: {e}')
    n_thumbs = sum(1 for m in rd_ad_media.values() if m.get('b64'))
    n_vids   = sum(1 for m in rd_ad_media.values() if m.get('is_video'))
    print(f'  Reddit: {n_thumbs} thumbnails, {n_vids} videos')

    # Per-preset totals — one API call per preset, no DATE breakdown avoids pagination issues
    RD_PRESETS = [
        ('All', '2025-07-01', _today),
        ('90D', _today - timedelta(90), _today),
        ('30D', _today - timedelta(30), _today),
        ('7D',  _today - timedelta(7),  _today),
    ]
    rd_preset_camps = {}   # preset → {cid: {clicks, impr, spend_usd}}
    rd_preset_ads   = {}   # preset → {aid: {clicks, impr, spend_usd}}
    for pname, ps, pe in RD_PRESETS:
        s_str = ps if isinstance(ps, str) else ps.isoformat()
        e_str = pe.isoformat()
        camp_rows = _reddit_report(rd_token, ['CLICKS','IMPRESSIONS','SPEND','KEY_CONVERSION_TOTAL_COUNT'],
                                   ['CAMPAIGN_ID'], f'{s_str}T00:00:00Z', f'{e_str}T00:00:00Z')
        ad_rows   = _reddit_report(rd_token, ['CLICKS','IMPRESSIONS','SPEND','KEY_CONVERSION_TOTAL_COUNT'],
                                   ['AD_ID','CAMPAIGN_ID'], f'{s_str}T00:00:00Z', f'{e_str}T00:00:00Z')
        rd_preset_camps[pname] = {
            str(r['campaign_id']): {'clicks': r.get('clicks',0), 'impr': r.get('impressions',0),
                                    'spend':  r.get('spend',0) / 1_000_000,
                                    'conv':   r.get('key_conversion_total_count', 0)}
            for r in camp_rows
        }
        rd_preset_ads[pname] = {
            str(r['ad_id']): {'clicks': r.get('clicks',0), 'impr': r.get('impressions',0),
                               'spend':  r.get('spend',0) / 1_000_000,
                               'conv':   r.get('key_conversion_total_count', 0)}
            for r in ad_rows
        }

    # Campaign daily data (for custom date range — campaign table only)
    RD_START = '2025-07-01T00:00:00Z'
    RD_END   = f'{_today.isoformat()}T00:00:00Z'
    camp_daily_rows = _reddit_report(rd_token, ['CLICKS','IMPRESSIONS','SPEND'],
                                     ['CAMPAIGN_ID','DATE'], RD_START, RD_END)
    rd_camp_daily = {}
    for row in camp_daily_rows:
        cid       = str(row.get('campaign_id', ''))
        dt        = row.get('date', '')[:10]
        spend_usd = row.get('spend', 0) / 1_000_000
        rd_camp_daily.setdefault(cid, {})
        rd_camp_daily[cid][dt] = [row.get('clicks', 0), row.get('impressions', 0), spend_usd]

    print(f'  Reddit: {len(rd_active_camps)} active campaigns, {len(rd_active_groups)} active ad groups, {len(rd_active_ads)} active ads')

# Build Reddit sidebar — active campaigns sorted by all-time spend (from preset data)
def _rd_camp_total(cid):
    return rd_preset_camps.get('All', {}).get(cid, {}).get('spend', 0)

rd_camp_order  = sorted(rd_active_camps.keys(), key=_rd_camp_total, reverse=True)
rd_total_spend = sum(_rd_camp_total(c) for c in rd_camp_order)

rd_sb = ''
if rd_camp_order:
    rd_sb += (f'<a href="#rd-cross" class="sb-link" data-section="rd-cross">'
              f'Cross-Campaign Ads<span>${rd_total_spend:,.0f}</span></a>\n')
for cid in rd_camp_order:
    name  = rd_active_camps[cid]['name']
    spend = _rd_camp_total(cid)
    anc   = 'rd-' + cid
    n_ads = sum(1 for a in rd_active_ads.values() if a['campaign_id'] == cid)
    rd_sb += (f'<a href="#{anc}" class="sb-link" data-section="{anc}">'
              f'{name[:38]}<span>{n_ads} ads · ${spend:,.0f}</span></a>\n')

rd_preset_camps_js = json.dumps(rd_preset_camps)
rd_preset_ads_js   = json.dumps(rd_preset_ads)
rd_camp_daily_js   = json.dumps(rd_camp_daily)

# ── LinkedIn Creatives ─────────────────────────────────────────────────────────
print('Fetching LinkedIn creatives…')

LI_TOKEN = os.getenv('LINKEDIN_ACCESS_TOKEN', '')
LI_ACCT  = os.getenv('LINKEDIN_ACCOUNT_ID', '509954586')
LI_HDR_V2   = {"Authorization": f"Bearer {LI_TOKEN}", "X-Restli-Protocol-Version": "2.0.0"}
LI_HDR_REST = {**LI_HDR_V2, "LinkedIn-Version": "202601"}
LI_SESSION  = requests.Session()
LI_SESSION.headers.update(LI_HDR_V2)

def _li_analytics(start, end):
    enc = quote(f"urn:li:sponsoredAccount:{LI_ACCT}", safe="")
    s_y,s_m,s_d = start[:4], int(start[5:7]), int(start[8:])
    e_y,e_m,e_d = end[:4], int(end[5:7]), int(end[8:])
    dr = f"(start:(year:{s_y},month:{s_m},day:{s_d}),end:(year:{e_y},month:{e_m},day:{e_d}))"
    q  = (f"q=analytics&pivot=CREATIVE&timeGranularity=ALL&dateRange={dr}"
          f"&accounts=List({enc})"
          f"&fields=impressions,clicks,costInLocalCurrency,externalWebsiteConversions,pivotValues")
    try:
        r = requests.get(f"https://api.linkedin.com/rest/adAnalytics?{q}",
                         headers=LI_HDR_REST, timeout=30)
        out = {}
        for el in r.json().get('elements', []):
            pv = el.get('pivotValues', [])
            if not pv: continue
            cid = pv[0].split(':')[-1]
            out[cid] = dict(impr=el.get('impressions',0), clicks=el.get('clicks',0),
                            conv=el.get('externalWebsiteConversions',0),
                            spend=float(el.get('costInLocalCurrency','0')))
        return out
    except Exception as e:
        print(f'  WARN li_analytics: {e}')
        return {}

def _li_daily(start, end):
    enc = quote(f"urn:li:sponsoredAccount:{LI_ACCT}", safe="")
    s_y,s_m,s_d = start[:4], int(start[5:7]), int(start[8:])
    e_y,e_m,e_d = end[:4], int(end[5:7]), int(end[8:])
    dr = f"(start:(year:{s_y},month:{s_m},day:{s_d}),end:(year:{e_y},month:{e_m},day:{e_d}))"
    q  = (f"q=analytics&pivot=CREATIVE&timeGranularity=DAILY&dateRange={dr}"
          f"&accounts=List({enc})"
          f"&fields=impressions,clicks,costInLocalCurrency,externalWebsiteConversions,pivotValues,dateRange")
    out = defaultdict(dict)
    try:
        r = requests.get(f"https://api.linkedin.com/rest/adAnalytics?{q}",
                         headers=LI_HDR_REST, timeout=60)
        for el in r.json().get('elements', []):
            pv = el.get('pivotValues', [])
            if not pv: continue
            cid = pv[0].split(':')[-1]
            ds = el.get('dateRange', {}).get('start', {})
            dt = f"{ds.get('year',0)}-{ds.get('month',1):02d}-{ds.get('day',1):02d}"
            out[cid][dt] = [el.get('externalWebsiteConversions',0),
                             el.get('clicks',0), el.get('impressions',0),
                             float(el.get('costInLocalCurrency','0'))]
    except Exception as e:
        print(f'  WARN li_daily: {e}')
    return dict(out)

# Use last 7 days to identify currently active creatives only
_li_active_window = (_today - timedelta(days=7)).isoformat()
_li_active = _li_analytics(_li_active_window, _today.isoformat())
print(f'  LinkedIn analytics rows (last 7D): {len(_li_active)}')

# All creatives with any impressions in last 7 days = currently active
top_cids = [cid for cid, d in _li_active.items() if d['impr'] > 0]
print(f'  Active creatives (last 7D): {len(top_cids)}')

# Still fetch all-time data for those specific creatives (used in preset datasets)
_li_all = _li_analytics('2025-06-01', _today.isoformat())

# Fetch creative details + resolve images
_li_camp_cache = {}
li_creatives = {}  # {cid: {name, img_url, type, camp_name, conv, clicks, impr, spend}}

def _li_camp_name(camp_id):
    if camp_id not in _li_camp_cache:
        try:
            r = requests.get(f"https://api.linkedin.com/v2/adCampaignsV2/{camp_id}",
                             headers=LI_HDR_V2, timeout=10)
            _li_camp_cache[camp_id] = r.json().get('name', f'Campaign {camp_id}') if r.ok else f'Campaign {camp_id}'
        except:
            _li_camp_cache[camp_id] = f'Campaign {camp_id}'
    return _li_camp_cache[camp_id]

print(f'  Fetching details for top {len(top_cids)} creatives…')
for i, cid in enumerate(top_cids):
    try:
        r = requests.get(f"https://api.linkedin.com/v2/adCreativesV2/{cid}",
                         headers=LI_HDR_V2, timeout=10)
        if not r.ok: continue
        cr = r.json()
        ctype    = cr.get('type', '')
        camp_urn = cr.get('campaign', '')
        camp_id  = camp_urn.split(':')[-1]
        camp_name = _li_camp_name(camp_id)

        vdata         = cr.get('variables', {}).get('data', {})
        img_url       = None
        name          = None
        video_url     = None   # direct MP4 downloadUrl for SPONSORED_VIDEO
        post_url      = None   # LinkedIn post/article URL
        carousel_cards = []    # [{url, title, link}, ...] for CAROUSEL type

        if ctype == 'SPONSORED_STATUS_UPDATE':
            for vk, vv in vdata.items():
                share_urn = vv.get('share', '')
                if share_urn:
                    share_id = share_urn.split(':')[-1]
                    rs = requests.get(f"https://api.linkedin.com/v2/shares/{share_id}",
                                      headers=LI_HDR_V2, timeout=10)
                    if rs.ok:
                        sd = rs.json()
                        name = sd.get('subject') or (sd.get('text',{}).get('text','')[:60])
                        ents = sd.get('content',{}).get('contentEntities',[])
                        if ents:
                            thumbs = ents[0].get('thumbnails',[])
                            if thumbs: img_url = thumbs[0].get('resolvedUrl','')
                    break

        elif ctype == 'SPONSORED_VIDEO':
            ref_urn = cr.get('reference', '')
            if ref_urn:
                rp = requests.get(
                    f"https://api.linkedin.com/rest/posts/{quote(ref_urn, safe='')}",
                    headers=LI_HDR_REST, timeout=10)
                if rp.ok:
                    pd = rp.json()
                    name = pd.get('adContext',{}).get('dscName') or pd.get('commentary','')[:60]
                    vid_urn = pd.get('content',{}).get('media',{}).get('id','')
                    if vid_urn:
                        rv = requests.get(
                            f"https://api.linkedin.com/rest/videos/{quote(vid_urn, safe='')}",
                            headers=LI_HDR_REST, timeout=10)
                        if rv.ok:
                            img_url   = rv.json().get('thumbnail','')
                            video_url = rv.json().get('downloadUrl','')
            # Fallback: post was 403 — use mediaAsset from variables → urn:li:video:{id}
            if not img_url:
                for vk, vv in vdata.items():
                    media_asset = vv.get('mediaAsset', '')
                    act_urn     = vv.get('activity', '')
                    if media_asset:
                        vid_id  = media_asset.split(':')[-1]
                        vid_urn = f'urn:li:video:{vid_id}'
                        rv = requests.get(
                            f"https://api.linkedin.com/rest/videos/{quote(vid_urn, safe='')}",
                            headers=LI_HDR_REST, timeout=10)
                        if rv.ok:
                            img_url   = rv.json().get('thumbnail','')
                            video_url = rv.json().get('downloadUrl','')
                    if act_urn:
                        post_url = f"https://www.linkedin.com/feed/update/{act_urn}/"
                    break

        elif ctype == 'SPONSORED_UPDATE_CAROUSEL':
            ref_urn = cr.get('reference', '')
            if ref_urn:
                rp = requests.get(
                    f"https://api.linkedin.com/rest/posts/{quote(ref_urn, safe='')}",
                    headers=LI_HDR_REST, timeout=10)
                if rp.ok:
                    pd = rp.json()
                    cards = pd.get('content', {}).get('carousel', {}).get('cards', [])
                    name = pd.get('commentary', '')[:60] or (cards[0].get('media', {}).get('title', '') if cards else '')
                    for card in cards:
                        img_id     = card.get('media', {}).get('id', '')
                        card_title = card.get('media', {}).get('title', '')
                        card_link  = card.get('landingPage', '')
                        if img_id:
                            ri = requests.get(
                                f"https://api.linkedin.com/rest/images/{quote(img_id, safe='')}",
                                headers=LI_HDR_REST, timeout=10)
                            if ri.ok:
                                card_url = ri.json().get('downloadUrl', '')
                                carousel_cards.append({'url': card_url, 'title': card_title, 'link': card_link})
                    if carousel_cards:
                        img_url = carousel_cards[0]['url']

        elif ctype == 'SPONSORED_UPDATE_LINKEDIN_ARTICLE':
            for vk, vv in vdata.items():
                name     = vv.get('contentTitle', '') or 'LinkedIn Article'
                act_urn  = vv.get('activity', '')
                if act_urn:
                    post_url = f"https://www.linkedin.com/feed/update/{act_urn}/"
                break

        elif ctype == 'SPONSORED_UPDATE_NATIVE_DOCUMENT':
            ref_urn = cr.get('reference', '')
            if ref_urn:
                rp = requests.get(
                    f"https://api.linkedin.com/rest/posts/{quote(ref_urn, safe='')}",
                    headers=LI_HDR_REST, timeout=10)
                if rp.ok:
                    pd = rp.json()
                    name = (pd.get('adContext',{}).get('dscName') or
                            pd.get('content',{}).get('media',{}).get('title','') or
                            pd.get('commentary','')[:60])
        elif ctype == 'FOLLOW_COMPANY_V2':
            continue  # no creative image

        m = _li_all.get(cid) or _li_active.get(cid, {})
        li_creatives[cid] = dict(name=name or f'Creative {cid}', img_url=img_url or '',
                                  type=ctype, camp_name=camp_name,
                                  carousel_cards=carousel_cards,
                                  video_url=video_url or '',
                                  post_url=post_url or '',
                                  conv=m.get('conv', 0.0), clicks=m.get('clicks', 0),
                                  impr=m.get('impr', 0), spend=m.get('spend', 0.0))
    except Exception as e:
        print(f'  WARN creative {cid}: {e}')

    if (i+1) % 20 == 0:
        print(f'  {i+1}/{len(top_cids)} creatives processed…')

print(f'  LinkedIn: {len(li_creatives)} creatives resolved')

# Download LinkedIn creative thumbnails
li_img_b64 = {}
for cid, d in li_creatives.items():
    if not d['img_url']:
        li_img_b64[cid] = None
        continue
    try:
        resp = sess.get(d['img_url'], timeout=10); resp.raise_for_status()
        img  = Image.open(io.BytesIO(resp.content)).convert('RGB')
        ratio = THUMB_W / img.width if img.width > THUMB_W else 1
        img  = img.resize((min(THUMB_W, img.width), max(1, int(img.height * ratio))), Image.LANCZOS)
        buf  = io.BytesIO(); img.save(buf, 'JPEG', quality=82)
        li_img_b64[cid] = 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
    except:
        li_img_b64[cid] = None
li_ok = sum(1 for v in li_img_b64.values() if v)
print(f'  Downloaded {li_ok}/{len(li_creatives)} LinkedIn thumbnails')

# Download all carousel card images
li_carousel_b64 = {}  # {cid: [{b64, title, link}, ...]}
for cid, d in li_creatives.items():
    cards = d.get('carousel_cards', [])
    if not cards:
        continue
    card_b64s = []
    for card in cards:
        try:
            resp = sess.get(card['url'], timeout=10); resp.raise_for_status()
            img  = Image.open(io.BytesIO(resp.content)).convert('RGB')
            ratio = THUMB_W / img.width if img.width > THUMB_W else 1
            img  = img.resize((min(THUMB_W, img.width), max(1, int(img.height * ratio))), Image.LANCZOS)
            buf  = io.BytesIO(); img.save(buf, 'JPEG', quality=82)
            b64  = 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
            card_b64s.append({'b64': b64, 'title': card.get('title',''), 'link': card.get('link','')})
        except:
            pass
    li_carousel_b64[cid] = card_b64s
    print(f'  Carousel {cid}: {len(card_b64s)}/{len(cards)} cards downloaded')

# Build LinkedIn preset datasets (fast — just analytics calls)
print('Building LinkedIn preset datasets…')
li_preset = {}
for pname, pstart, pend in PRESETS:
    li_preset[pname] = _li_analytics(pstart.isoformat(), pend.isoformat())
li_preset_js = json.dumps(li_preset)

# LinkedIn daily data for custom date range
print('Fetching LinkedIn daily data…')
li_daily = _li_daily('2025-06-01', _today.isoformat())
li_daily_js = json.dumps(li_daily)
print(f'  LinkedIn daily entries: {sum(len(d) for d in li_daily.values())}')

# Group creatives by campaign, sorted by conv
li_by_camp = defaultdict(list)
for cid, d in li_creatives.items():
    li_by_camp[d['camp_name']].append(cid)
li_camp_order = sorted(li_by_camp.keys(),
    key=lambda c: -sum(li_creatives[cid]['conv'] for cid in li_by_camp[c]))

# LinkedIn sidebar HTML
TYPE_LABEL = {
    'SPONSORED_STATUS_UPDATE':          'Image',
    'SPONSORED_VIDEO':                  'Video',
    'SPONSORED_UPDATE_NATIVE_DOCUMENT': 'Document',
    'SPONSORED_UPDATE_CAROUSEL':        'Carousel',
    'SPONSORED_UPDATE_LINKEDIN_ARTICLE':'Article',
}
li_total_conv  = sum(li_creatives[cid]['conv']  for cid in li_creatives)
li_total_spend = sum(li_creatives[cid]['spend'] for cid in li_creatives)

# Group creatives by visual — same img_url = same creative running in multiple campaigns
_li_seen_key = {}   # dedup_key → first cid with a thumbnail
_li_groups   = {}   # dedup_key → [cid, ...]
for cid, d in li_creatives.items():
    key = d['img_url'] if d['img_url'] else f"__name__{d['name']}__{d['type']}"
    if key not in _li_groups:
        _li_groups[key] = []
    _li_groups[key].append(cid)
    if d['img_url'] and key not in _li_seen_key:
        _li_seen_key[key] = cid

# For each group, pick the representative cid (has thumbnail if possible) and list of campaign rows
li_cross_groups = []  # [{rep_cid, cids, name, type, img_url}]
for key, cids_in_group in _li_groups.items():
    rep_cid = _li_seen_key.get(key, cids_in_group[0])
    d0 = li_creatives[rep_cid]
    li_cross_groups.append(dict(
        rep=rep_cid,
        cids=sorted(cids_in_group, key=lambda c: -li_creatives[c]['impr']),
        name=d0['name'], ctype=d0['type'], img_url=d0['img_url'],
    ))
# Sort groups by total impressions
li_cross_groups.sort(key=lambda g: -sum(li_creatives[c]['impr'] for c in g['cids']))

li_sb = (f'<a href="#li-cross" class="sb-link" data-section="li-cross">'
         f'Cross-Campaign<span>{len(li_creatives)} creatives · ${li_total_spend:,.0f}</span></a>\n')
for camp in li_camp_order:
    cids = li_by_camp[camp]
    tc = sum(li_creatives[cid]['conv'] for cid in cids)
    ts = sum(li_creatives[cid]['spend'] for cid in cids)
    anc = 'li-' + camp.replace('|','').replace(' ','-').replace('/','-').lower()[:40]
    li_sb += (f'<a href="#{anc}" class="sb-link" data-section="{anc}">'
              f'{camp[:38]}<span>{tc:.0f} conv · ${ts:,.0f}</span></a>\n')

logo_b64    = open('.claude/skills/linkedin-ads/scripts/sprinto_logo_b64.txt').read().strip()
favicon_b64 = 'data:image/webp;base64,' + base64.b64encode(open('/Users/tanmayjn/Downloads/Icon Light.webp', 'rb').read()).decode()

def img_cell(aid, name, zoom=True):
    b64   = img_b64.get(aid)
    short = (name[:30] + '…') if len(name) > 30 else name
    if b64:
        cls = 'class="zoomable"' if zoom else ''
        cur = 'cursor:zoom-in;' if zoom else ''
        return f'<img src="{b64}" alt="{name}" {cls} style="{cur}width:100%;height:auto;display:block;max-width:100%">'
    # Placeholder for stock images whose CDN URL returns a blank
    is_stock = 'Free stock' in name or 'free stock' in name.lower()
    label = 'Google Stock Image' if is_stock else 'No preview'
    return (f'<div style="width:100%;min-height:80px;display:flex;flex-direction:column;'
            f'align-items:center;justify-content:center;text-align:center;'
            f'color:#bbb;font-size:10px;padding:16px;line-height:1.5;gap:6px">'
            f'<span style="font-size:22px">&#128247;</span>'
            f'<span>{label}</span>'
            f'<span style="font-size:9px;color:#ddd">{short}</span>'
            f'</div>')

def vid_cell(aid, vid_id, name):
    b64     = img_b64.get(aid)
    yt_url  = f'https://www.youtube.com/watch?v={vid_id}'
    play    = ('<div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);'
               'width:44px;height:44px;background:rgba(0,0,0,.65);border-radius:50%;'
               'display:flex;align-items:center;justify-content:center;'
               'color:#fff;font-size:18px;pointer-events:none">&#9654;</div>')
    if b64:
        return (f'<a href="{yt_url}" target="_blank" rel="noopener" '
                f'style="display:block;position:relative;text-decoration:none">'
                f'<img src="{b64}" alt="{name}" style="width:100%;height:auto;display:block">'
                f'{play}</a>')
    return (f'<a href="{yt_url}" target="_blank" rel="noopener" '
            f'style="display:block;min-height:80px;background:#f5f5f5;position:relative;'
            f'display:flex;align-items:center;justify-content:center;color:#bbb;font-size:11px">'
            f'No preview{play}</a>')

# ── Sidebar ────────────────────────────────────────────────────────────────────
n_shared_imgs = len(shared_images)
n_shared_vids = len(shared_videos)
shared_desc = f'{n_shared_imgs} images · {n_shared_vids} videos' if n_shared_vids else f'{n_shared_imgs} shared images'
sb = (f'<a href="#shared" class="sb-link" data-section="shared">'
      f'Cross-Campaign<span>{shared_desc}</span></a>\n')
for camp in camp_order:
    tc  = sum(by_asset[aid]['camps'][camp]['conv']     for aid in camp_assets[camp])
    ts  = sum(by_asset[aid]['camps'][camp]['cost_usd'] for aid in camp_assets[camp])
    anc = camp_anchor(camp)
    sb += (f'<a href="#{anc}" class="sb-link" data-section="{anc}">'
           f'{camp}<span>{tc:.2f} conv · ${ts:,.0f}</span></a>\n')

today = date.today().strftime('%b %d, %Y')

# ── HTML ───────────────────────────────────────────────────────────────────────
html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Google Ads Assets Performance — Sprinto</title>
<link rel="icon" type="image/webp" href="{favicon_b64}">
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=Lora:wght@600&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:"Instrument Sans",Arial,sans-serif;background:{LIGHT_BG};color:#1a1a1a;font-size:13px;display:flex;min-height:100vh}}

/* PLATFORM TOGGLE BAR */
#platform-bar{{position:fixed;top:0;left:0;right:0;height:44px;background:#fff;
    border-bottom:1px solid #e8e3e3;z-index:300;display:flex;align-items:center;
    padding:0 16px;gap:6px}}
.plat-btn{{padding:6px 18px;border-radius:4px;border:1px solid #e0dada;
    background:#fff;color:#555;font-size:12px;font-weight:600;cursor:pointer;
    transition:all .15s;font-family:inherit}}
.plat-btn:hover{{background:#fdf3f8;border-color:#c5658a;color:{MULBERRY}}}
.plat-btn.active{{background:{MULBERRY};color:#fff;border-color:{MULBERRY}}}
#platform-bar span.plat-divider{{width:1px;height:20px;background:#e8e3e3;margin:0 6px}}

/* SIDEBAR — light theme */
.sb{{position:fixed;left:0;top:44px;width:232px;height:calc(100vh - 44px);background:#fff;
    overflow-y:auto;z-index:200;border-right:1px solid #e8e3e3;
    display:flex;flex-direction:column}}
.sb-header{{padding:18px 16px 14px;border-bottom:1px solid #ede8e8;flex-shrink:0}}
.sb-header img{{height:22px;display:block;margin-bottom:10px}}
.sb-header h2{{color:#888;font-size:10px;font-weight:600;letter-spacing:.8px;text-transform:uppercase}}
.sb-link{{display:block;padding:8px 16px;color:#444;text-decoration:none;
    font-size:11px;font-weight:600;line-height:1.4;
    border-left:3px solid transparent;transition:all .15s}}
.sb-link span{{display:block;font-weight:400;color:#aaa;font-size:10px;margin-top:1px}}
.sb-link:hover{{background:{LIGHT_BG};color:{MULBERRY};border-left-color:#c5658a}}
.sb-link.active{{background:#fdf3f8;color:{MULBERRY};border-left-color:{MULBERRY}}}
.sb-link.active span{{color:#c07090}}
.sb-divider{{height:1px;background:#ede8e8;flex-shrink:0}}

/* MAIN */
.main-content{{margin-left:232px;padding:76px 32px 80px;max-width:1240px;width:100%}}
.page-header{{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:28px}}
.page-title{{font-family:"Lora",serif;font-size:24px;font-weight:600;color:{MULBERRY}}}
.page-subtitle{{color:#888;font-size:12px;margin-top:5px}}
.report-meta{{text-align:right;font-size:11px;color:#bbb;padding-top:4px}}

/* SECTION */
.sec-head{{display:flex;align-items:baseline;gap:10px;margin:40px 0 16px;scroll-margin-top:52px;
    padding-bottom:10px;border-bottom:2px solid {MULBERRY}}}
.sec-title{{font-size:15px;font-weight:700;color:{MULBERRY}}}
.sec-sub{{font-size:12px;color:#aaa}}

/* SHARED CARDS */
.shared-card{{background:#fff;border-radius:6px;margin-bottom:12px;
    display:grid;grid-template-columns:180px 1fr;overflow:hidden;border:1px solid #ede8e8}}
.s-img-wrap{{width:180px;background:{GREY};display:flex;
    align-items:center;justify-content:center;flex-shrink:0;
    overflow:hidden;border-right:1px solid #ede8e8}}
.s-data{{padding:14px 16px}}
.s-name{{font-size:12px;font-weight:600;color:#1a1a1a;margin-bottom:3px}}
.s-meta{{font-size:11px;color:#aaa;margin-bottom:10px}}

/* IMAGE GRID */
.img-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(195px,1fr));gap:12px}}
.card{{background:#fff;border-radius:6px;border:1px solid #ede8e8;overflow:hidden}}
.c-img{{background:{GREY};display:block;
    border-bottom:1px solid #ede8e8}}
.c-body{{padding:9px 10px}}
.c-name{{font-size:10px;color:#888;margin-bottom:6px;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.c-tags{{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:7px;align-items:center}}
.tag-dim{{font-size:9px;color:#bbb;background:#f5f5f5;padding:1px 5px;border-radius:3px}}
.tag-shared{{font-size:9px;color:{MULBERRY};background:#fce8f3;padding:1px 5px;
    border-radius:3px;font-weight:600}}

/* METRICS */
.mt{{width:100%;border-collapse:collapse;font-size:11px}}
.mt th{{background:{GREY};color:#aaa;font-weight:600;padding:4px 8px;
    text-align:left;border-bottom:1px solid #ede8e8}}
.mt td{{padding:4px 8px;border-bottom:1px solid #f8f5f5}}
.mt tr:last-child td{{border-bottom:none}}
.mt tr:hover td{{background:{LIGHT_BG}}}
.cv{{font-weight:700;color:{MULBERRY}}}
.zr{{color:#ccc}}
.dim-txt{{font-size:10px;color:#ccc;margin-top:5px}}

/* DATE BAR */
#date-bar{{display:flex;align-items:center;gap:8px;margin-bottom:20px;
    padding:10px 14px;background:#fff;border-radius:6px;border:1px solid #ede8e8;flex-wrap:wrap}}
.preset-btn{{padding:5px 14px;border-radius:4px;border:1px solid #e0dada;
    background:#fff;color:#555;font-size:11px;font-weight:600;cursor:pointer;
    transition:all .15s;font-family:inherit}}
.preset-btn:hover{{background:#fdf3f8;border-color:#c5658a;color:{MULBERRY}}}
.preset-btn.active{{background:{MULBERRY};color:#fff;border-color:{MULBERRY}}}
.date-lbl{{font-size:10px;color:#aaa;font-weight:600;letter-spacing:.6px;text-transform:uppercase;margin-right:4px}}
#date-hint{{font-size:11px;color:#bbb;margin-left:6px}}

/* VIDEO GRID */
.vid-section{{margin-top:14px}}
.vid-section-label{{font-size:10px;font-weight:600;color:#aaa;letter-spacing:.6px;text-transform:uppercase;margin-bottom:8px}}
.vid-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}}
.vid-card{{background:#fff;border-radius:6px;border:1px solid #ede8e8;overflow:hidden}}
.vid-thumb{{background:{GREY};display:block;border-bottom:1px solid #ede8e8}}

/* LIGHTBOX */
#lightbox{{display:none;position:fixed;inset:0;background:rgba(31,2,20,.88);
    z-index:9999;align-items:center;justify-content:center;cursor:zoom-out}}
#lightbox.open{{display:flex}}
#lightbox img{{max-width:88vw;max-height:88vh;object-fit:contain;
    border-radius:6px;box-shadow:0 8px 40px rgba(0,0,0,.5)}}
#lb-close{{position:fixed;top:20px;right:24px;color:rgba(255,255,255,.7);
    font-size:28px;cursor:pointer;line-height:1;user-select:none}}
#lb-close:hover{{color:#fff}}
</style>
</head>
<body>

<!-- PLATFORM TOGGLE -->
<div id="platform-bar">
  <button class="plat-btn active" id="btn-google" onclick="showPlatform('google')">Google Ads</button>
  <span class="plat-divider"></span>
  <button class="plat-btn" id="btn-linkedin" onclick="showPlatform('linkedin')">LinkedIn</button>
  <span class="plat-divider"></span>
  <button class="plat-btn" id="btn-reddit" onclick="showPlatform('reddit')">Reddit</button>
</div>

<!-- LIGHTBOX -->
<div id="lightbox">
  <span id="lb-close">&#x2715;</span>
  <img id="lb-img" src="" alt="">
</div>

<nav id="sb-google" class="sb">
  <div class="sb-header">
    <img src="{logo_b64}" alt="Sprinto">
    <h2>Google Ads</h2>
  </div>
  <div class="sb-divider"></div>
  {sb}
</nav>

<nav id="sb-linkedin" class="sb" style="display:none">
  <div class="sb-header">
    <img src="{logo_b64}" alt="Sprinto">
    <h2>LinkedIn</h2>
  </div>
  <div class="sb-divider"></div>
  {li_sb}
</nav>

<nav id="sb-reddit" class="sb" style="display:none">
  <div class="sb-header">
    <img src="{logo_b64}" alt="Sprinto">
    <h2>Reddit Ads</h2>
  </div>
  <div class="sb-divider"></div>
  {rd_sb}
</nav>

<div id="main-google" class="main-content">
  <div class="page-header">
    <div>
      <div class="page-title">Google Ads Assets Performance</div>
      <div class="page-subtitle">Active images in enabled asset groups &nbsp;·&nbsp; Costs in USD (INR ÷ 93) &nbsp;·&nbsp; Jun 2025 – Jun 2026</div>
    </div>
    <div class="report-meta">Generated {today}</div>
  </div>
  <div id="date-bar">
    <span class="date-lbl">Date range</span>
    <button class="preset-btn" data-preset="All" onclick="applyPreset('All')">All time</button>
    <button class="preset-btn" data-preset="90D" onclick="applyPreset('90D')">Last 90 days</button>
    <button class="preset-btn" data-preset="30D" onclick="applyPreset('30D')">Last 30 days</button>
    <button class="preset-btn active" data-preset="7D"  onclick="applyPreset('7D')">Last 7 days</button>
    <span id="date-hint">{preset_hints['7D']}</span>
    <span style="margin-left:8px;width:1px;height:16px;background:#e0dada;display:inline-block;vertical-align:middle"></span>
    <span class="date-lbl" style="margin-left:8px">Custom</span>
    <input type="date" id="custom-start" value="2025-06-01" min="2025-06-01" max="{_today.isoformat()}"
           style="border:1px solid #e0dada;border-radius:4px;padding:4px 8px;font-size:11px;font-family:inherit;color:#444;background:#fff;cursor:pointer">
    <span style="font-size:11px;color:#bbb">to</span>
    <input type="date" id="custom-end" value="{_today.isoformat()}" min="2025-06-01" max="{_today.isoformat()}"
           style="border:1px solid #e0dada;border-radius:4px;padding:4px 8px;font-size:11px;font-family:inherit;color:#444;background:#fff;cursor:pointer">
    <button class="preset-btn" onclick="applyCustom()" style="margin-left:2px">Apply</button>
  </div>
'''

# ── SHARED SECTION ─────────────────────────────────────────────────────────────
shared_sub = []
if shared_images: shared_sub.append(f'{len(shared_images)} images')
if shared_videos: shared_sub.append(f'{len(shared_videos)} videos')
html += (f'<div class="sec-head" id="shared">'
         f'<span class="sec-title">Cross-Campaign Creatives</span>'
         f'<span class="sec-sub">{" · ".join(shared_sub)} used in 2+ campaigns · sorted by total conv</span>'
         f'</div>\n')

def _shared_card(aid, d):
    tc = sum(cd['conv']     for cd in d['camps'].values())
    ts = sum(cd['cost_usd'] for cd in d['camps'].values())
    cs = sorted(d['camps'].items(), key=lambda x: -x[1]['conv'])
    fl = FIELD_SHORT.get(d['field'], d['field'])
    is_vid = d.get('is_video')
    thumb  = (vid_cell(aid, d['vid_id'], d['name']) if is_vid
              else img_cell(aid, d['name']))
    meta_dim = '' if is_vid else f' &nbsp;·&nbsp; {fl} {d["w"]}×{d["h"]}'
    out  = '<div class="shared-card">'
    out += f'<div class="s-img-wrap">{thumb}</div>'
    out += '<div class="s-data">'
    out += f'<div class="s-name">{d["name"]}</div>'
    out += (f'<div class="s-meta">{len(d["camps"])} campaigns · {tc:.2f} conv · '
            f'${ts:,.0f} spend{meta_dim}</div>')
    out += ('<table class="mt"><thead>'
            '<tr><th>Campaign</th><th>Asset Group</th>'
            '<th>Conv</th><th>CTR</th><th>Impr</th><th>CPA</th><th>Spend</th>'
            '</tr></thead><tbody>')
    for camp, cd in cs:
        ctr  = f'{cd["clicks"]/cd["impr"]*100:.2f}%' if cd['impr'] else '—'
        cpa  = f'${cd["cost_usd"]/cd["conv"]:,.0f}'  if cd['conv'] else '—'
        ccls = 'cv' if cd['conv'] > 0 else 'zr'
        out += (f'<tr data-aid="{aid}" data-camp="{camp}">'
                f'<td>{camp}</td>'
                f'<td style="color:#bbb;font-size:10px">{cd["ag"]}</td>'
                f'<td data-f="conv" class="{ccls}">{cd["conv"]:.2f}</td>'
                f'<td data-f="ctr">{ctr}</td>'
                f'<td data-f="impr">{int(cd["impr"]):,}</td>'
                f'<td data-f="cpa">{cpa}</td>'
                f'<td data-f="cost">${cd["cost_usd"]:,.0f}</td></tr>')
    out += '</tbody></table></div></div>\n'
    return out

for aid, d in sorted(shared_images.items(), key=lambda x: -sum(c['conv'] for c in x[1]['camps'].values())):
    html += _shared_card(aid, d)
for aid, d in sorted(shared_videos.items(), key=lambda x: -sum(c['conv'] for c in x[1]['camps'].values())):
    html += _shared_card(aid, d)

# ── PER CAMPAIGN ───────────────────────────────────────────────────────────────
for camp in camp_order:
    aids     = sorted(camp_assets[camp], key=lambda a: -by_asset[a]['camps'][camp]['conv'])
    img_aids = [a for a in aids if not by_asset[a].get('is_video')]
    vid_aids = [a for a in aids if by_asset[a].get('is_video')]
    is_dg    = any(by_asset[aid].get('is_dg') for aid in img_aids)
    tc = sum(by_asset[aid]['camps'][camp]['conv']     for aid in aids)
    ts = sum(by_asset[aid]['camps'][camp]['cost_usd'] for aid in aids)
    anc = camp_anchor(camp)

    counts_parts = []
    if img_aids: counts_parts.append(f'{len(img_aids)} image{"s" if len(img_aids)!=1 else ""}')
    if vid_aids: counts_parts.append(f'{len(vid_aids)} video{"s" if len(vid_aids)!=1 else ""}')
    counts_str = ' · '.join(counts_parts)

    html += (f'<div class="sec-head" id="{anc}">'
             f'<span class="sec-title">{camp}</span>'
             f'<span class="sec-sub">'
             f'<span data-sc="{camp}" data-sf="conv">{tc:.2f} conv</span>'
             f' · <span data-sc="{camp}" data-sf="cost">${ts:,.0f} spend</span>'
             f' · {counts_str}'
             + (' · <span style="font-size:10px;color:#e0895a;font-weight:600">Demand Gen</span>' if is_dg else '') +
             f'</span>'
             f'</div>\n')

    # ── Image cards ──────────────────────────────────────────────────────────
    if img_aids:
        html += '<div class="img-grid">\n'
        for aid in img_aids:
            d  = by_asset[aid]
            cd = d['camps'][camp]
            fl = FIELD_SHORT.get(d['field'], d['field'])

            html += '<div class="card">'
            html += f'<div class="c-img">{img_cell(aid, d["name"])}</div>'
            html += '<div class="c-body">'
            html += f'<div class="c-name" title="{d["name"]}">{d["name"]}</div>'
            html += '<div class="c-tags">'
            html += f'<span class="tag-dim">{fl} {d["w"]}×{d["h"]}</span>'
            if len(d['camps']) > 1:
                html += f'<span class="tag-shared">×{len(d["camps"])} camps</span>'
            if d.get('is_dg'):
                html += '<span style="font-size:9px;color:#e0895a;background:#fff3ec;padding:1px 5px;border-radius:3px;font-weight:600">DG</span>'
            html += '</div>'
            ctr  = f'{cd["clicks"]/cd["impr"]*100:.2f}%' if cd['impr'] else '—'
            cpa  = f'${cd["cost_usd"]/cd["conv"]:,.0f}'  if cd['conv'] else '—'
            ccls = 'cv' if cd['conv'] > 0 else 'zr'
            html += (f'<div data-aid="{aid}" data-camp="{camp}">'
                     '<table class="mt"><tbody>'
                     f'<tr><td style="color:#aaa">Conv</td><td data-f="conv" class="{ccls}">{cd["conv"]:.2f}</td></tr>'
                     f'<tr><td style="color:#aaa">CTR</td><td data-f="ctr">{ctr}</td></tr>'
                     f'<tr><td style="color:#aaa">Impr</td><td data-f="impr">{int(cd["impr"]):,}</td></tr>'
                     f'<tr><td style="color:#aaa">CPA</td><td data-f="cpa">{cpa}</td></tr>'
                     f'<tr><td style="color:#aaa">Spend</td><td data-f="cost">${cd["cost_usd"]:,.0f}</td></tr>'
                     '</tbody></table>'
                     '</div>')
            ags = cd.get('ags') or set()
            if d.get('is_dg') and len(ags) > 1:
                ag_label = ' + '.join(sorted(ags))
            else:
                ag_label = cd['ag']
            html += f'<div class="dim-txt">{ag_label[:48]}</div>'
            html += '</div></div>\n'
        html += '</div>\n'

    # ── Video cards ──────────────────────────────────────────────────────────
    if vid_aids:
        html += '<div class="vid-section"><div class="vid-section-label">Videos</div><div class="vid-grid">\n'
        for aid in vid_aids:
            d   = by_asset[aid]
            cd  = d['camps'][camp]
            ctr = f'{cd["clicks"]/cd["impr"]*100:.2f}%' if cd['impr'] else '—'
            cpa = f'${cd["cost_usd"]/cd["conv"]:,.0f}'  if cd['conv'] else '—'
            ccls = 'cv' if cd['conv'] > 0 else 'zr'
            yt_url = f'https://www.youtube.com/watch?v={d["vid_id"]}'
            html += '<div class="vid-card">'
            html += f'<div class="vid-thumb">{vid_cell(aid, d["vid_id"], d["name"])}</div>'
            html += '<div class="c-body">'
            html += f'<div class="c-name" title="{d["name"]}">{d["name"]}</div>'
            html += '<div class="c-tags">'
            html += f'<span class="tag-dim">YouTube Video</span>'
            if len(d['camps']) > 1:
                html += f'<span class="tag-shared">×{len(d["camps"])} camps</span>'
            html += '</div>'
            html += (f'<div data-aid="{aid}" data-camp="{camp}">'
                     '<table class="mt"><tbody>'
                     f'<tr><td style="color:#aaa">Conv</td><td data-f="conv" class="{ccls}">{cd["conv"]:.2f}</td></tr>'
                     f'<tr><td style="color:#aaa">CTR</td><td data-f="ctr">{ctr}</td></tr>'
                     f'<tr><td style="color:#aaa">Impr</td><td data-f="impr">{int(cd["impr"]):,}</td></tr>'
                     f'<tr><td style="color:#aaa">CPA</td><td data-f="cpa">{cpa}</td></tr>'
                     f'<tr><td style="color:#aaa">Spend</td><td data-f="cost">${cd["cost_usd"]:,.0f}</td></tr>'
                     '</tbody></table>'
                     f'<div class="dim-txt"><a href="{yt_url}" target="_blank" rel="noopener" '
                     f'style="color:#aaa;text-decoration:none">&#9654; Watch on YouTube</a></div>'
                     '</div>')
            html += '</div></div>\n'
        html += '</div></div>\n'

# ── LinkedIn HTML ──────────────────────────────────────────────────────────────
html += '\n</div>\n'   # close #main-google

def li_thumb_cell(cid, d):
    b64    = li_img_b64.get(cid)
    ctype  = d['type']
    is_vid      = ctype == 'SPONSORED_VIDEO'
    is_carousel = ctype == 'SPONSORED_UPDATE_CAROUSEL'
    is_article  = ctype == 'SPONSORED_UPDATE_LINKEDIN_ARTICLE'
    is_doc      = ctype == 'SPONSORED_UPDATE_NATIVE_DOCUMENT'
    has_video   = bool(d.get('video_url'))
    post_url    = d.get('post_url', '')

    play_btn = ('<div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);'
                'width:48px;height:48px;background:rgba(0,0,0,.65);border-radius:50%;'
                'display:flex;align-items:center;justify-content:center;'
                'color:#fff;font-size:20px;pointer-events:none">&#9654;</div>')

    if b64:
        if is_carousel:
            badge = ('<div style="position:absolute;bottom:6px;right:6px;background:rgba(0,0,0,.55);'
                     'border-radius:4px;padding:2px 6px;color:#fff;font-size:10px;pointer-events:none">'
                     '&#10697; Carousel</div>')
            return (f'<div style="position:relative;cursor:pointer" onclick="openCarousel(\'{cid}\')">'
                    f'<img src="{b64}" style="width:100%;height:auto;display:block">'
                    f'{badge}</div>')
        if is_vid and has_video:
            return (f'<div style="position:relative;cursor:pointer" onclick="openVideo(\'{cid}\')">'
                    f'<img src="{b64}" style="width:100%;height:auto;display:block">'
                    f'{play_btn}</div>')
        if is_article and post_url:
            return (f'<a href="{post_url}" target="_blank" rel="noopener" style="display:block;position:relative">'
                    f'<img src="{b64}" style="width:100%;height:auto;display:block"></a>')
        return f'<img src="{b64}" class="zoomable" style="cursor:zoom-in;width:100%;height:auto;display:block">'

    # Placeholders
    if is_vid and has_video:
        return (f'<div style="width:100%;min-height:100px;background:#111;display:flex;flex-direction:column;'
                f'align-items:center;justify-content:center;cursor:pointer;gap:8px" onclick="openVideo(\'{cid}\')">'
                f'<span style="font-size:32px;color:#fff">&#9654;</span>'
                f'<span style="color:#aaa;font-size:10px">Play video</span></div>')
    if is_article and post_url:
        return (f'<a href="{post_url}" target="_blank" rel="noopener" style="display:flex;flex-direction:column;'
                f'align-items:center;justify-content:center;width:100%;min-height:80px;'
                f'background:#f0f4ff;color:#0a66c2;font-size:10px;gap:6px;text-decoration:none;padding:16px">'
                f'<span style="font-size:22px">&#128196;</span><span>Open Article &#8599;</span></a>')
    if is_vid:      icon, label = '&#127909;', 'Video'
    elif is_carousel: icon, label = '&#10697;', 'Carousel'
    elif is_article: icon, label = '&#128196;', 'Article'
    elif is_doc:    icon, label = '&#128196;', 'Document'
    else:           icon, label = '&#128247;', 'No preview'
    return (f'<div style="width:100%;min-height:80px;display:flex;flex-direction:column;'
            f'align-items:center;justify-content:center;color:#bbb;font-size:10px;padding:16px;gap:6px">'
            f'<span style="font-size:22px">{icon}</span>'
            f'<span>{label}</span></div>')

html += '\n<div id="main-linkedin" class="main-content" style="display:none">\n'
html += f'''  <div class="page-header">
    <div>
      <div class="page-title">LinkedIn Creative Performance</div>
      <div class="page-subtitle">Active creatives · Spend in USD · Jun 2025 – present</div>
    </div>
    <div class="report-meta">Generated {today}</div>
  </div>
  <div id="li-date-bar" style="display:flex;align-items:center;gap:8px;margin-bottom:20px;
      padding:10px 14px;background:#fff;border-radius:6px;border:1px solid #ede8e8;flex-wrap:wrap">
    <span class="date-lbl">Date range</span>
    <button class="preset-btn" data-lipreset="All" onclick="liApplyPreset('All')">All time</button>
    <button class="preset-btn" data-lipreset="90D" onclick="liApplyPreset('90D')">Last 90 days</button>
    <button class="preset-btn" data-lipreset="30D" onclick="liApplyPreset('30D')">Last 30 days</button>
    <button class="preset-btn active" data-lipreset="7D"  onclick="liApplyPreset('7D')">Last 7 days</button>
    <span style="margin-left:8px;width:1px;height:16px;background:#e0dada;display:inline-block;vertical-align:middle"></span>
    <span class="date-lbl" style="margin-left:8px">Custom</span>
    <input type="date" id="li-custom-start" value="2025-06-01" min="2025-06-01" max="{_today.isoformat()}"
           style="border:1px solid #e0dada;border-radius:4px;padding:4px 8px;font-size:11px;font-family:inherit;color:#444;background:#fff">
    <span style="font-size:11px;color:#bbb">to</span>
    <input type="date" id="li-custom-end" value="{_today.isoformat()}" min="2025-06-01" max="{_today.isoformat()}"
           style="border:1px solid #e0dada;border-radius:4px;padding:4px 8px;font-size:11px;font-family:inherit;color:#444;background:#fff">
    <button class="preset-btn" onclick="liApplyCustom()">Apply</button>
  </div>
'''

# ── LinkedIn Cross-Campaign section ────────────────────────────────────────────
html += (f'<div class="sec-head" id="li-cross">'
         f'<span class="sec-title">Cross-Campaign Creatives</span>'
         f'<span class="sec-sub">'
         f'<span id="li-cross-conv">{li_total_conv:.0f} conv</span>'
         f' · <span id="li-cross-spend">${li_total_spend:,.0f} spend</span>'
         f' · {len(li_creatives)} active creatives across {len(li_camp_order)} campaigns'
         f'</span></div>\n')

for grp in li_cross_groups:
    rep  = grp['rep']
    cids_g = grp['cids']
    d0   = li_creatives[rep]
    tlab = TYPE_LABEL.get(grp['ctype'], grp['ctype'])
    n_camps = len(cids_g)
    tc   = sum(li_creatives[c]['conv']  for c in cids_g)
    ts   = sum(li_creatives[c]['spend'] for c in cids_g)

    html += '<div class="shared-card">'
    html += f'<div class="s-img-wrap">{li_thumb_cell(rep, d0)}</div>'
    html += '<div class="s-data">'
    html += f'<div class="s-name">{grp["name"]}</div>'
    camp_names = ' · '.join(li_creatives[c]['camp_name'] for c in cids_g[:2])
    if n_camps > 2: camp_names += f' +{n_camps-2} more'
    html += f'<div class="s-meta">{camp_names} &nbsp;·&nbsp; {tlab}</div>'
    html += ('<table class="mt"><thead>'
             '<tr><th>Campaign</th><th>Ad Format</th>'
             '<th>Conv</th><th>CTR</th><th>Impr</th><th>CPA</th><th>Spend</th>'
             '</tr></thead><tbody>')
    for cid in cids_g:
        d    = li_creatives[cid]
        ccls = 'cv' if d['conv'] > 0 else 'zr'
        ctr  = f'{d["clicks"]/d["impr"]*100:.2f}%' if d['impr'] else '—'
        cpa  = f'${d["spend"]/d["conv"]:,.0f}'     if d['conv'] else '—'
        html += (f'<tr data-licid="{cid}" data-camp="{d["camp_name"]}">'
                 f'<td>{d["camp_name"]}</td>'
                 f'<td style="color:#bbb;font-size:10px">{tlab}</td>'
                 f'<td data-lif="conv" class="{ccls}">{d["conv"]:.2f}</td>'
                 f'<td data-lif="ctr">{ctr}</td>'
                 f'<td data-lif="impr">{d["impr"]:,}</td>'
                 f'<td data-lif="cpa">{cpa}</td>'
                 f'<td data-lif="spend">${d["spend"]:,.0f}</td></tr>')
    html += '</tbody></table></div></div>\n'

for camp in li_camp_order:
    cids = li_by_camp[camp]
    cids_sorted = sorted(cids, key=lambda c: -li_creatives[c]['conv'])
    tc = sum(li_creatives[c]['conv'] for c in cids)
    ts = sum(li_creatives[c]['spend'] for c in cids)
    anc = 'li-' + camp.replace('|','').replace(' ','-').replace('/','-').lower()[:40]

    html += (f'<div class="sec-head" id="{anc}">'
             f'<span class="sec-title">{camp}</span>'
             f'<span class="sec-sub">'
             f'<span data-licid-camp="{camp}" data-licid-f="conv">{tc:.0f} conv</span>'
             f' · <span data-licid-camp="{camp}" data-licid-f="spend">${ts:,.0f} spend</span>'
             f' · {len(cids)} creatives'
             f'</span></div>\n<div class="img-grid">\n')

    for cid in cids_sorted:
        d   = li_creatives[cid]
        ccls = 'cv' if d['conv'] > 0 else 'zr'
        ctr  = f'{d["clicks"]/d["impr"]*100:.2f}%' if d['impr'] else '—'
        cpa  = f'${d["spend"]/d["conv"]:,.0f}'     if d['conv'] else '—'
        tlab = TYPE_LABEL.get(d['type'], d['type'])

        html += f'<div class="card" data-camp="{camp}">'
        html += f'<div class="c-img">{li_thumb_cell(cid, d)}</div>'
        html += '<div class="c-body">'
        html += f'<div class="c-name" title="{d["name"]}">{d["name"]}</div>'
        html += (f'<div class="c-tags"><span class="tag-dim">{tlab}</span></div>')
        html += (f'<div data-licid="{cid}">'
                 '<table class="mt"><tbody>'
                 f'<tr><td style="color:#aaa">Conv</td><td data-lif="conv" class="{ccls}">{d["conv"]:.0f}</td></tr>'
                 f'<tr><td style="color:#aaa">CTR</td><td data-lif="ctr">{ctr}</td></tr>'
                 f'<tr><td style="color:#aaa">Impr</td><td data-lif="impr">{d["impr"]:,}</td></tr>'
                 f'<tr><td style="color:#aaa">CPA</td><td data-lif="cpa">{cpa}</td></tr>'
                 f'<tr><td style="color:#aaa">Spend</td><td data-lif="spend">${d["spend"]:,.0f}</td></tr>'
                 '</tbody></table></div>')
        html += '</div></div>\n'
    html += '</div>\n'

html += '\n</div>\n'  # close #main-linkedin

# ── Reddit HTML ────────────────────────────────────────────────────────────────
def rd_post_cell(aid, ad_info):
    media    = rd_ad_media.get(aid, {})
    b64      = media.get('b64')
    is_vid   = media.get('is_video', False)
    vid_url  = media.get('video_url', '')
    post_url = ad_info.get('post_url', '') or ad_info.get('click_url', '')

    if b64 and is_vid:
        return (f'<div onclick="rdOpenVideo(\'{aid}\')" style="cursor:pointer;position:relative;'
                f'width:100%;height:100%;min-height:120px;overflow:hidden">'
                f'<img src="{b64}" style="width:100%;height:100%;object-fit:cover;display:block">'
                f'<div style="position:absolute;inset:0;display:flex;align-items:center;'
                f'justify-content:center;background:rgba(0,0,0,.28)">'
                f'<svg width="44" height="44" viewBox="0 0 44 44">'
                f'<circle cx="22" cy="22" r="22" fill="rgba(0,0,0,.55)"/>'
                f'<polygon points="18,13 34,22 18,31" fill="white"/></svg>'
                f'</div></div>')
    elif b64:
        return (f'<img src="{b64}" class="zoomable" style="cursor:zoom-in;width:100%;height:100%;object-fit:cover;display:block">')
    else:
        # Fallback: Reddit icon + View Post link
        inner = (f'<svg width="28" height="28" viewBox="0 0 20 20" fill="#FF4500">'
                 f'<circle cx="10" cy="10" r="10"/>'
                 f'<path fill="#fff" d="M16.67 10a1.46 1.46 0 0 0-2.47-1 7.12 7.12 0 0 0-3.85-1.23'
                 f'l.65-3.07 2.13.45a1 1 0 1 0 .08-.5l-2.38-.5a.14.14 0 0 0-.16.1l-.73 3.43a7.14 '
                 f'7.14 0 0 0-3.89 1.24 1.46 1.46 0 1 0-1.61 2.39 2.87 2.87 0 0 0 0 .44c0 2.24 '
                 f'2.61 4.06 5.83 4.06s5.83-1.82 5.83-4.06a2.87 2.87 0 0 0 0-.44 1.46 1.46 0 0 0 '
                 f'.47-1.31zm-9.34 1.07a1 1 0 1 1 1 1 1 1 0 0 1-1-1zm5.58 2.64a3.58 3.58 0 0 '
                 f'1-2.91.93 3.58 3.58 0 0 1-2.91-.93.19.19 0 0 1 .27-.27 3.21 3.21 0 0 0 2.64.66 '
                 f'3.21 3.21 0 0 0 2.64-.66.19.19 0 0 1 .27.27zm-.17-1.64a1 1 0 1 1 1-1 1 1 0 0 1-1 1z"/>'
                 f'</svg><span>View Post &#8599;</span>')
        if post_url:
            return (f'<a href="{post_url}" target="_blank" rel="noopener" '
                    f'style="display:flex;flex-direction:column;align-items:center;justify-content:center;'
                    f'width:100%;min-height:120px;background:#f6f0f5;color:#650A41;'
                    f'font-size:10px;gap:6px;text-decoration:none;padding:20px">{inner}</a>')
        return (f'<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;'
                f'width:100%;min-height:120px;background:#f6f0f5;color:#bbb;font-size:10px;gap:6px;padding:20px">'
                f'{inner}</div>')

html += f'\n<div id="main-reddit" class="main-content" style="display:none">\n'
html += f'''  <div class="page-header">
    <div>
      <div class="page-title">Reddit Ads Performance</div>
      <div class="page-subtitle">SprintoGRC · Active campaigns &amp; ads · Spend in USD · Jul 2025 – present</div>
    </div>
    <div class="report-meta">Generated {today}</div>
  </div>
  <div id="rd-date-bar" style="display:flex;align-items:center;gap:8px;margin-bottom:20px;
      padding:10px 14px;background:#fff;border-radius:6px;border:1px solid #ede8e8;flex-wrap:wrap">
    <span class="date-lbl">Date range</span>
    <button class="preset-btn" data-rdpreset="All" onclick="rdApplyPreset(\'All\')">All time</button>
    <button class="preset-btn" data-rdpreset="90D" onclick="rdApplyPreset(\'90D\')">Last 90 days</button>
    <button class="preset-btn" data-rdpreset="30D" onclick="rdApplyPreset(\'30D\')">Last 30 days</button>
    <button class="preset-btn active" data-rdpreset="7D"  onclick="rdApplyPreset(\'7D\')">Last 7 days</button>
    <span style="margin-left:8px;width:1px;height:16px;background:#e0dada;display:inline-block;vertical-align:middle"></span>
    <span class="date-lbl" style="margin-left:8px">Custom</span>
    <input type="date" id="rd-custom-start" value="2025-07-01" min="2025-07-01" max="{_today.isoformat()}"
           style="border:1px solid #e0dada;border-radius:4px;padding:4px 8px;font-size:11px;font-family:inherit;color:#444;background:#fff">
    <span style="font-size:11px;color:#bbb">to</span>
    <input type="date" id="rd-custom-end" value="{_today.isoformat()}" min="2025-07-01" max="{_today.isoformat()}"
           style="border:1px solid #e0dada;border-radius:4px;padding:4px 8px;font-size:11px;font-family:inherit;color:#444;background:#fff">
    <button class="preset-btn" onclick="rdApplyCustom()">Apply</button>
  </div>
'''

# Cross-campaign overview — card grid of all active ads sorted by all-time spend
total_active_ads = len(rd_active_ads)
html += (f'<div class="sec-head" id="rd-cross">'
         f'<span class="sec-title">Cross-Campaign Ads</span>'
         f'<span class="sec-sub">{len(rd_camp_order)} campaigns · {total_active_ads} active ads · '
         f'<span id="rd-total-spend">${rd_total_spend:,.0f}</span> all-time spend</span></div>\n')

# Group ads by name — same creative running in multiple campaigns → one card, multiple rows
from collections import defaultdict as _dd
_rd_groups = _dd(list)
for _aid, _info in rd_active_ads.items():
    _rd_groups[_info['name']].append((_aid, _info))

def _grp_spend(ads):
    return sum(rd_preset_ads.get('All', {}).get(a, {}).get('spend', 0) for a, _ in ads)

rd_cross_groups = sorted(_rd_groups.values(), key=lambda g: -_grp_spend(g))

for grp in rd_cross_groups:
    # Primary ad = highest individual spend, used for image
    grp_sorted = sorted(grp, key=lambda x: -rd_preset_ads.get('All', {}).get(x[0], {}).get('spend', 0))
    primary_aid, primary_info = grp_sorted[0]
    ad_name = primary_info['name']
    camp_labels = ', '.join(
        rd_active_camps.get(i['campaign_id'], {}).get('name', '') for _, i in grp_sorted
    )

    html += f'<div class="shared-card">'   # no data-rdaid on card — rows carry it
    html += f'<div class="s-img-wrap">{rd_post_cell(primary_aid, primary_info)}</div>'
    html += '<div class="s-data">'
    html += f'<div class="s-name">{ad_name}</div>'
    html += f'<div class="s-meta">{camp_labels}</div>'
    html += ('<table class="mt"><thead>'
             '<tr><th>Campaign</th><th>Ad Group</th>'
             '<th>Conv</th><th>CTR</th><th>Impr</th><th>CPA</th><th>Spend</th>'
             '</tr></thead><tbody>')
    for aid, info in grp_sorted:
        cid       = info['campaign_id']
        camp_name = rd_active_camps.get(cid, {}).get('name', '')
        grp_id    = info.get('ad_group_id', '')
        grp_name  = rd_active_groups.get(grp_id, {}).get('name', '') if grp_id else ''
        html += (f'<tr data-rdaid="{aid}">'
                 f'<td>{camp_name}</td>'
                 f'<td style="color:#bbb;font-size:10px">{grp_name}</td>'
                 f'<td data-rdf="conv">—</td>'
                 f'<td data-rdf="ctr">—</td>'
                 f'<td data-rdf="impr">—</td>'
                 f'<td data-rdf="cpa">—</td>'
                 f'<td data-rdf="spend">—</td></tr>')
    html += '</tbody></table></div></div>\n'

# Per-campaign sections with ad cards (same as LinkedIn per-campaign layout)
for cid in rd_camp_order:
    camp_name  = rd_active_camps[cid]['name']
    anc        = 'rd-' + cid
    camp_ads   = [(aid, info) for aid, info in rd_active_ads.items() if info['campaign_id'] == cid]
    camp_ads.sort(key=lambda x: -rd_preset_ads.get('All', {}).get(x[0], {}).get('spend', 0))
    n_ads      = len(camp_ads)

    html += (f'<div class="sec-head" id="{anc}">'
             f'<span class="sec-title">{camp_name}</span>'
             f'<span class="sec-sub">'
             f'<span data-rdcamp-spend="{cid}">—</span> spend · '
             f'<span data-rdcamp-conv="{cid}">—</span> conv · '
             f'{n_ads} active ads'
             f'</span></div>\n<div class="img-grid">\n')

    for aid, info in camp_ads:
        ad_name = info['name']
        # Ad group label
        grp_id   = info.get('ad_group_id', '')
        grp_name = rd_active_groups.get(grp_id, {}).get('name', '') if grp_id else ''

        html += f'<div class="card" data-rdaid="{aid}">'
        html += f'<div class="c-img">{rd_post_cell(aid, info)}</div>'
        html += '<div class="c-body">'
        html += f'<div class="c-name" title="{ad_name}">{ad_name}</div>'
        tags  = '<span class="tag-dim">Reddit Ad</span>'
        if grp_name:
            tags += f'<span class="tag-dim">{grp_name}</span>'
        html += f'<div class="c-tags">{tags}</div>'
        html += ('<div>'
                 '<table class="mt"><tbody>'
                 '<tr><td style="color:#aaa">Conv</td><td data-rdf="conv">—</td></tr>'
                 '<tr><td style="color:#aaa">CTR</td><td data-rdf="ctr">—</td></tr>'
                 '<tr><td style="color:#aaa">Impr</td><td data-rdf="impr">—</td></tr>'
                 '<tr><td style="color:#aaa">CPA</td><td data-rdf="cpa">—</td></tr>'
                 '<tr><td style="color:#aaa">Spend</td><td data-rdf="spend">—</td></tr>'
                 '</tbody></table></div>')
        html += '</div></div>\n'

    html += '</div>\n'

html += '\n</div>\n'  # close #main-reddit

# ── Video + Carousel modal data ────────────────────────────────────────────────
carousel_js   = json.dumps(li_carousel_b64)
li_video_data = {cid: {'url': d['video_url'], 'name': d['name']}
                 for cid, d in li_creatives.items() if d.get('video_url')}
video_data_js = json.dumps(li_video_data)
rd_video_data = {aid: {'url': m['video_url'], 'name': rd_active_ads.get(aid, {}).get('name', '')}
                 for aid, m in rd_ad_media.items() if m.get('is_video') and m.get('video_url')}
rd_video_data_js = json.dumps(rd_video_data)
html += '''
<!-- Video modal -->
<div id="li-video-modal" onclick="if(event.target===this)closeVideo()"
  style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.9);z-index:9999;
         align-items:center;justify-content:center;flex-direction:column;padding:20px">
  <button onclick="closeVideo()"
    style="position:absolute;top:16px;right:20px;background:none;border:none;color:#fff;
           font-size:28px;cursor:pointer;line-height:1">&#215;</button>
  <video id="li-video-player" controls autoplay playsinline
    style="max-width:90vw;max-height:80vh;border-radius:8px;outline:none"></video>
  <div id="li-video-title"
    style="color:#ccc;font-size:12px;margin-top:10px;max-width:640px;text-align:center"></div>
</div>
<!-- Carousel modal -->
<div id="li-carousel-modal" onclick="if(event.target===this)closeCarousel()"
  style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.82);z-index:9999;
         align-items:center;justify-content:center;flex-direction:column;padding:20px">
  <button onclick="closeCarousel()"
    style="position:absolute;top:16px;right:20px;background:none;border:none;color:#fff;
           font-size:28px;cursor:pointer;line-height:1">&#215;</button>
  <div id="li-carousel-title"
    style="color:#fff;font-size:13px;font-weight:600;margin-bottom:12px;max-width:900px;text-align:center"></div>
  <div id="li-carousel-cards"
    style="display:flex;gap:12px;overflow-x:auto;max-width:95vw;padding-bottom:8px;
           scrollbar-width:thin;scrollbar-color:#555 transparent"></div>
  <div id="li-carousel-count"
    style="color:#aaa;font-size:11px;margin-top:10px"></div>
</div>
'''

html += f'''
<script>
// ── Google Ads date range controller ─────────────────────────────────────────
const DATASETS     = {datasets_js};
const PRESET_HINTS = {hints_js};
const PRESET_DATES = {preset_dates_js};
const DAILY_DATA   = {daily_js};

const fmtConv = v => (+v).toFixed(2);
const fmtImpr = v => Math.round(+v).toLocaleString();
const fmtCost = v => '$' + Math.round(+v).toLocaleString();
const fmtCtr  = (cl, im) => +im > 0 ? ((+cl / +im) * 100).toFixed(2) + '%' : '—';
const fmtCpa  = (co, cv) => +cv > 0 ? '$' + Math.round(+co / +cv).toLocaleString() : '—';

function _applyData(data) {{
  document.querySelectorAll('[data-aid]').forEach(el => {{
    const aid = el.dataset.aid, camp = el.dataset.camp;
    const d   = (data[aid] && data[aid][camp]) ? data[aid][camp] : {{conv:0,clicks:0,impr:0,cost_usd:0}};
    const q   = s => el.querySelector('[data-f="'+s+'"]');
    const cvEl = q('conv');
    if (cvEl) {{ cvEl.textContent = fmtConv(d.conv); cvEl.className = +d.conv > 0 ? 'cv' : 'zr'; }}
    const ctrEl = q('ctr');  if (ctrEl) ctrEl.textContent = fmtCtr(d.clicks, d.impr);
    const imEl  = q('impr'); if (imEl)  imEl.textContent  = fmtImpr(d.impr);
    const paEl  = q('cpa');  if (paEl)  paEl.textContent  = fmtCpa(d.cost_usd, d.conv);
    const coEl  = q('cost'); if (coEl)  coEl.textContent  = fmtCost(d.cost_usd);
  }});
  document.querySelectorAll('[data-sc]').forEach(el => {{
    const camp = el.dataset.sc, sf = el.dataset.sf;
    let total = 0;
    Object.values(data).forEach(camps => {{
      if (camps[camp]) total += sf === 'conv' ? +camps[camp].conv : +camps[camp].cost_usd;
    }});
    el.textContent = sf === 'conv' ? fmtConv(total)+' conv' : fmtCost(total)+' spend';
  }});
}}

function applyPreset(p) {{
  document.querySelectorAll('.preset-btn').forEach(b => b.classList.toggle('active', b.dataset.preset === p));
  document.getElementById('date-hint').textContent = PRESET_HINTS[p];
  _applyData(DATASETS[p]);
}}

function applyCustom() {{
  const s = document.getElementById('custom-start').value;
  const e = document.getElementById('custom-end').value;
  if (!s || !e || s > e) return;
  document.querySelectorAll('.preset-btn[data-preset]').forEach(b => b.classList.remove('active'));
  document.getElementById('date-hint').textContent = s + ' – ' + e;
  const agg = {{}};
  Object.entries(DAILY_DATA).forEach(([aid, camps]) => {{
    agg[aid] = {{}};
    Object.entries(camps).forEach(([camp, dates]) => {{
      const d = {{conv:0, clicks:0, impr:0, cost_usd:0}};
      Object.entries(dates).forEach(([dt, v]) => {{
        if (dt >= s && dt <= e) {{ d.conv += v[0]; d.clicks += v[1]; d.impr += v[2]; d.cost_usd += v[3]; }}
      }});
      agg[aid][camp] = d;
    }});
  }});
  _applyData(agg);
}}

// Scroll-spy sidebar
(function(){{
  const links    = document.querySelectorAll('.sb-link[data-section]');
  const sections = [];
  links.forEach(l => {{
    const el = document.getElementById(l.dataset.section);
    if (el) sections.push({{el, link: l}});
  }});

  function setActive(link) {{
    links.forEach(l => l.classList.remove('active'));
    link.classList.add('active');
    link.scrollIntoView({{block:'nearest', behavior:'smooth'}});
  }}

  function updateFromScroll() {{
    const mid = window.innerHeight * 0.35;
    let active = null;
    for (const s of sections) {{
      if (s.el.offsetHeight === 0) continue;  // skip elements hidden by display:none on parent
      if (s.el.getBoundingClientRect().top <= mid) active = s;
    }}
    if (active) setActive(active.link);
  }}

  // On page load: honour the URL hash
  function activateFromHash() {{
    const hash = location.hash.replace('#','');
    const match = hash ? sections.find(s => s.el.id === hash) : null;
    if (match) setActive(match.link);
    else if (sections.length) setActive(sections[0].link);
  }}
  activateFromHash();
  window.addEventListener('hashchange', activateFromHash);

  // Click: lock active state, suppress scroll-spy until scroll settles
  let suppressSpy = false;
  links.forEach(l => l.addEventListener('click', () => {{
    links.forEach(x => x.classList.remove('active'));
    l.classList.add('active');
    suppressSpy = true;
    setTimeout(() => {{ suppressSpy = false; updateFromScroll(); }}, 500);
  }}));

  let t = false;
  document.addEventListener('scroll', () => {{
    if (suppressSpy || t) return; t = true;
    requestAnimationFrame(() => {{ updateFromScroll(); t = false; }});
  }}, {{passive: true}});
}})();

// Lightbox
(function(){{
  const lb    = document.getElementById('lightbox');
  const lbImg = document.getElementById('lb-img');
  document.querySelectorAll('.zoomable').forEach(img => {{
    img.addEventListener('click', e => {{
      e.stopPropagation();
      lbImg.src = img.src;
      lb.classList.add('open');
    }});
  }});
  lb.addEventListener('click', () => lb.classList.remove('open'));
  document.getElementById('lb-close').addEventListener('click', () => lb.classList.remove('open'));
  document.addEventListener('keydown', e => {{
    if (e.key === 'Escape') lb.classList.remove('open');
  }});
}})();

// ── LinkedIn date range controller ────────────────────────────────────────────
const LI_PRESETS = {li_preset_js};
const LI_DAILY   = {li_daily_js};

function _liApplyData(data) {{
  document.querySelectorAll('[data-licid]').forEach(el => {{
    const cid = el.dataset.licid;
    const d   = data[cid] || {{conv:0, clicks:0, impr:0, spend:0}};
    const q   = s => el.querySelector('[data-lif="'+s+'"]');
    const cvEl = q('conv');
    if (cvEl) {{ cvEl.textContent = Math.round(+d.conv||0); cvEl.className = +d.conv > 0 ? 'cv' : 'zr'; }}
    const imEl  = q('impr');  if (imEl)  imEl.textContent  = Math.round(+d.impr||0).toLocaleString();
    const coEl  = q('spend'); if (coEl)  coEl.textContent  = '$' + Math.round(+d.spend||0).toLocaleString();
    const ctrEl = q('ctr');
    if (ctrEl) ctrEl.textContent = +d.impr > 0 ? ((+d.clicks/+d.impr)*100).toFixed(2)+'%' : '—';
    const paEl  = q('cpa');
    if (paEl) paEl.textContent = +d.conv > 0 ? '$'+Math.round(+d.spend/+d.conv).toLocaleString() : '—';
  }});
  document.querySelectorAll('[data-licid-camp]').forEach(el => {{
    const camp = el.dataset.licidCamp, sf = el.dataset.licidF;
    let tot = 0;
    Object.values(LI_PRESETS['All']).forEach(m => {{
      // data is keyed by creative_id, not camp — sum creatives that match this camp
    }});
    // Sum from data directly using camp match
    const campCreatives = Object.entries(data).filter(([cid]) => {{
      return document.querySelector(`[data-licid="${{cid}}"]`) !== null;
    }});
    // Simpler: track camp totals in JS
  }});
}}

// Pre-compute camp totals for each preset
const LI_CAMP_TOTALS = {{}};
const LI_CREATIVE_CAMP = {{}};

(function() {{
  // Map each creative to its campaign from the "All" preset keys
  const allData = LI_PRESETS['All'];
  // We embed camp per creative in HTML via data-licid-camp on card
  document.querySelectorAll('[data-licid]').forEach(el => {{
    const cid = el.dataset.licid;
    const card = el.closest('.card');
    if (card) LI_CREATIVE_CAMP[cid] = card.dataset.camp || '';
  }});
}})();

function _liUpdateCampTotals(data) {{
  const campConv = {{}}, campSpend = {{}};
  Object.entries(data).forEach(([cid, m]) => {{
    const camp = LI_CREATIVE_CAMP[cid];
    if (!camp) return;
    campConv[camp]  = (campConv[camp]  || 0) + (+m.conv  || 0);
    campSpend[camp] = (campSpend[camp] || 0) + (+m.spend || 0);
  }});
  document.querySelectorAll('[data-licid-camp]').forEach(el => {{
    const camp = el.dataset.licidCamp, sf = el.dataset.licidF;
    const v = sf === 'conv' ? campConv[camp]||0 : campSpend[camp]||0;
    el.textContent = sf === 'conv' ? Math.round(v)+' conv' : '$'+Math.round(v).toLocaleString()+' spend';
  }});
  // Update cross-campaign totals
  const totalConv  = Object.values(data).reduce((s,m) => s + (+m.conv||0),  0);
  const totalSpend = Object.values(data).reduce((s,m) => s + (+m.spend||0), 0);
  const cce = document.getElementById('li-cross-conv');
  const cse = document.getElementById('li-cross-spend');
  if (cce) cce.textContent = Math.round(totalConv) + ' conv';
  if (cse) cse.textContent = '$' + Math.round(totalSpend).toLocaleString() + ' spend';
}}

function liApplyPreset(p) {{
  document.querySelectorAll('[data-lipreset]').forEach(b => b.classList.toggle('active', b.dataset.lipreset === p));
  const data = LI_PRESETS[p] || {{}};
  _liApplyData(data);
  _liUpdateCampTotals(data);
}}

function liApplyCustom() {{
  const s = document.getElementById('li-custom-start').value;
  const e = document.getElementById('li-custom-end').value;
  if (!s || !e || s > e) return;
  document.querySelectorAll('[data-lipreset]').forEach(b => b.classList.remove('active'));
  const agg = {{}};
  Object.entries(LI_DAILY).forEach(([cid, dates]) => {{
    const m = {{conv:0, clicks:0, impr:0, spend:0}};
    Object.entries(dates).forEach(([dt, v]) => {{
      if (dt >= s && dt <= e) {{ m.conv += v[0]; m.clicks += v[1]; m.impr += v[2]; m.spend += v[3]; }}
    }});
    agg[cid] = m;
  }});
  _liApplyData(agg);
  _liUpdateCampTotals(agg);
}}

// ── Reddit date range controller ──────────────────────────────────────────────
const RD_PRESET_CAMPS = {rd_preset_camps_js};
const RD_PRESET_ADS   = {rd_preset_ads_js};
const RD_CAMP_DAILY   = {rd_camp_daily_js};  // campaign daily data for custom range

const fmtRd = v => '$' + Math.round(+v).toLocaleString();

function _rdApplyPresetData(campData, adData) {{
  // Update campaign section subtitles
  document.querySelectorAll('[data-rdcamp-spend]').forEach(el => {{
    const m = campData[el.dataset.rdcampSpend] || {{spend:0}};
    el.textContent = fmtRd(m.spend);
  }});
  document.querySelectorAll('[data-rdcamp-conv]').forEach(el => {{
    const m = campData[el.dataset.rdcampConv] || {{conv:0}};
    el.textContent = Math.round(m.conv || 0).toLocaleString();
  }});

  // Update total spend
  let total = 0;
  Object.values(campData).forEach(m => total += m.spend);
  const tEl = document.getElementById('rd-total-spend');
  if (tEl) tEl.textContent = fmtRd(total);

  // Update ad cards (both cross-campaign and per-campaign sections share same data-rdaid)
  document.querySelectorAll('[data-rdaid]').forEach(card => {{
    const aid = card.dataset.rdaid;
    const m   = (adData && adData[aid]) ? adData[aid] : null;
    const ctr = m && m.impr > 0 ? ((m.clicks/m.impr)*100).toFixed(2)+'%' : '—';
    const conv = m ? Math.round(m.conv || 0) : null;
    const cpa  = (m && conv && m.spend > 0) ? '$' + (m.spend / conv).toFixed(2) : '—';
    const q   = f => card.querySelector('[data-rdf="'+f+'"]');
    if (q('conv'))  q('conv').textContent  = conv !== null ? conv.toLocaleString() : '—';
    if (q('impr'))  q('impr').textContent  = m ? Math.round(m.impr).toLocaleString()   : '—';
    if (q('ctr'))   q('ctr').textContent   = ctr;
    if (q('cpa'))   q('cpa').textContent   = cpa;
    if (q('spend')) q('spend').textContent = m ? fmtRd(m.spend) : '—';
  }});
}}

function rdApplyPreset(p) {{
  document.querySelectorAll('[data-rdpreset]').forEach(b => b.classList.toggle('active', b.dataset.rdpreset === p));
  _rdApplyPresetData(RD_PRESET_CAMPS[p] || {{}}, RD_PRESET_ADS[p] || {{}});
}}

function rdApplyCustom() {{
  const s = document.getElementById('rd-custom-start').value;
  const e = document.getElementById('rd-custom-end').value;
  if (!s || !e || s > e) return;
  document.querySelectorAll('[data-rdpreset]').forEach(b => b.classList.remove('active'));
  // Aggregate campaign totals from daily data
  const campAgg = {{}};
  Object.entries(RD_CAMP_DAILY).forEach(([cid, dates]) => {{
    const m = {{clicks:0, impr:0, spend:0}};
    Object.entries(dates).forEach(([dt, v]) => {{
      if (dt >= s && dt <= e) {{ m.clicks += v[0]; m.impr += v[1]; m.spend += v[2]; }}
    }});
    campAgg[cid] = m;
  }});
  _rdApplyPresetData(campAgg, null);  // ad cards show '—' for custom range
}}

// ── Platform toggle ───────────────────────────────────────────────────────────
// Store camp mapping after DOM is ready
document.querySelectorAll('#main-linkedin .card').forEach(card => {{
  const licidEl = card.querySelector('[data-licid]');
  if (licidEl) LI_CREATIVE_CAMP[licidEl.dataset.licid] = card.dataset.camp || '';
}});

function showPlatform(p) {{
  ['google','linkedin','reddit'].forEach(pl => {{
    const isA = pl === p;
    document.getElementById('sb-'+pl).style.display     = isA ? 'flex' : 'none';
    document.getElementById('main-'+pl).style.display   = isA ? '' : 'none';
    document.getElementById('btn-'+pl).classList.toggle('active', isA);
  }});
}}

// Apply 7D as default on page load
applyPreset('7D');
liApplyPreset('7D');
if (Object.keys(RD_PRESET_CAMPS).length) rdApplyPreset('7D');

// ── Video player ─────────────────────────────────────────────────────────────
const LI_VIDEO_DATA = {video_data_js};
const RD_VIDEO_DATA = {rd_video_data_js};

function rdOpenVideo(aid) {{
  const v = RD_VIDEO_DATA[aid];
  if (!v) return;
  const player = document.getElementById('li-video-player');
  player.src = v.url;
  document.getElementById('li-video-title').textContent = v.name;
  document.getElementById('li-video-modal').style.display = 'flex';
  player.play().catch(() => {{}});
}}

function openVideo(cid) {{
  const v = LI_VIDEO_DATA[cid];
  if (!v) return;
  const player = document.getElementById('li-video-player');
  player.src = v.url;
  document.getElementById('li-video-title').textContent = v.name;
  document.getElementById('li-video-modal').style.display = 'flex';
  player.play().catch(() => {{}});
}}

function closeVideo() {{
  const player = document.getElementById('li-video-player');
  player.pause();
  player.src = '';
  document.getElementById('li-video-modal').style.display = 'none';
}}

// ── Carousel lightbox ─────────────────────────────────────────────────────────
const CAROUSEL_DATA = {carousel_js};

function openCarousel(cid) {{
  const cards = CAROUSEL_DATA[cid] || [];
  if (!cards.length) return;
  const container = document.getElementById('li-carousel-cards');
  container.innerHTML = cards.map((c, i) => `
    <div style="flex-shrink:0;text-align:center;max-width:260px">
      <a href="${{c.link}}" target="_blank" rel="noopener" style="display:block;text-decoration:none">
        <img src="${{c.b64}}" style="width:100%;max-width:260px;border-radius:6px;display:block">
        ${{c.title ? `<div style="color:#ddd;font-size:11px;margin-top:6px;padding:0 4px">${{c.title}}</div>` : ''}}
      </a>
    </div>`).join('');
  document.getElementById('li-carousel-title').textContent =
    document.querySelector(`[data-licid]`)?.closest('.shared-card')?.querySelector('.s-name')?.textContent || 'Carousel Ad';
  document.getElementById('li-carousel-count').textContent = cards.length + ' cards';
  document.getElementById('li-carousel-modal').style.display = 'flex';
}}

function closeCarousel() {{
  document.getElementById('li-carousel-modal').style.display = 'none';
}}
</script>
</body></html>'''

with open(OUT_FILE, 'w') as f:
    f.write(html)

import os
sz = os.path.getsize(OUT_FILE) / 1024 / 1024
print(f'\nSaved {OUT_FILE} — {sz:.1f} MB')
n_imgs_total = sum(1 for d in by_asset.values() if not d.get('is_video'))
n_vids_total = sum(1 for d in by_asset.values() if d.get('is_video'))
print(f'{n_imgs_total} images + {n_vids_total} videos, {len(shared_assets)} shared, {len(camp_order)} campaigns')
print('Done.')
