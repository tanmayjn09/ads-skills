"""
LinkedIn Competitor Ad Gallery Builder
Fetches all active ads, detects age, downloads creatives, generates HTML gallery.

Usage:
    python build_competitor_gallery.py                  # Full run, all competitors
    python build_competitor_gallery.py --company vanta  # Single company
    python build_competitor_gallery.py --no-fetch       # Regenerate gallery from cache only
    python build_competitor_gallery.py --skip-age       # Skip age detection API calls (faster)

Flow:
  1. Load base ad list from competitor_research.json (no API call needed)
  2. Seed copy cache from competitor_copy_with_images.json (existing data)
  3. Run 6m + 12m age detection (2 API calls per company, ~10 total)
  4. Fetch copy + images for all uncached ads
  5. Generate gallery HTML
"""

import os, re, sys, json, time, html, base64, argparse, threading
from pathlib import Path
from datetime import date, timedelta
from urllib.request import Request, urlopen
from urllib.parse import quote
from urllib.error import HTTPError

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
OUT_DIR    = BASE_DIR / "output"
IMG_DIR    = OUT_DIR  / "ad_images"
CACHE_FILE = OUT_DIR  / "gallery_cache.json"
PREV_FILE  = OUT_DIR  / "gallery_prev_ids.json"
GALLERY    = OUT_DIR  / "competitor_gallery.html"
ENV_FILE   = BASE_DIR / ".env"

OUT_DIR.mkdir(exist_ok=True)
IMG_DIR.mkdir(exist_ok=True)

# ── Config ────────────────────────────────────────────────────────────────────
COMPETITORS = {
    "vanta":       {"search": "Vanta",       "exact": "Vanta"},
    "drata":       {"search": "Drata",       "exact": "Drata"},
    "secureframe": {"search": "Secureframe", "exact": "Secureframe"},
    "thoropass":   {"search": "Thoropass",   "exact": "Thoropass"},
    "sprinto":     {"search": "Sprinto",     "exact": "Sprinto"},
}

COMPANY_COLORS = {
    "vanta":       "#7C3AED",
    "drata":       "#1E40AF",
    "secureframe": "#059669",
    "thoropass":   "#16A34A",
    "sprinto":     "#9B1B60",
}

MONTH_COLORS = {
    0: "#22C55E",  # current month
    1: "#3B82F6",  # 1 month ago
    2: "#60A5FA",
    3: "#F59E0B",
    4: "#FB923C",
    5: "#EF4444",
    6: "#DC2626",
}

def month_color(months_ago):
    return MONTH_COLORS.get(min(months_ago, 6), "#6B7280")

# ── Auth ──────────────────────────────────────────────────────────────────────
def load_env():
    token = None
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("LINKEDIN_ACCESS_TOKEN="):
                token = line.split("=", 1)[1].strip()
    return token or os.getenv("LINKEDIN_ACCESS_TOKEN")

ACCESS_TOKEN = load_env()

HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "LinkedIn-Version": "202503",
    "X-Restli-Protocol-Version": "2.0.0",
}
WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.linkedin.com/",
}

# ── Ad Library API ────────────────────────────────────────────────────────────
import calendar

def month_date_range(year, month):
    """Return Restli dateRange string for a single calendar month."""
    today = date.today()
    last_day = calendar.monthrange(year, month)[1]
    if year == today.year and month == today.month:
        end = today - timedelta(days=1)
        ey, em, ed = end.year, end.month, end.day
    else:
        ey, em, ed = year, month, last_day
    return (
        f"(start:(year:{year},month:{month},day:1),"
        f"end:(year:{ey},month:{em},day:{ed}))"
    )

def estimate_start_month(ad_id_int):
    """
    Estimate start month from ad ID.
    LinkedIn ad IDs are global sequential. Calibration:
      Anchor: ID 1,432,423,366 = June 8, 2026 (from live data)
      Rate:   ~16M IDs per month (empirically derived)
    Returns ("Since Jun 2026", color) or ("Pre-2026", color).
    """
    ANCHOR_ID   = 1_432_423_366
    ANCHOR_DATE = date(2026, 6, 8)
    IDS_PER_MONTH = 16_000_000

    delta_ids    = ANCHOR_ID - ad_id_int
    months_ago   = delta_ids / IDS_PER_MONTH

    if months_ago < 0:
        months_ago = 0

    # Round to nearest month
    m = round(months_ago)

    est_month = ANCHOR_DATE.month - m
    est_year  = ANCHOR_DATE.year
    while est_month <= 0:
        est_month += 12; est_year -= 1

    # Cap display at "Pre-2025" for very old IDs
    if est_year < 2025:
        return "Pre-2025 (long running)", "#6B7280"

    label = "Since " + date(est_year, est_month, 1).strftime("%b %Y")
    color = month_color(max(0, m))
    return label, color

def fetch_all_ads_for_company(search_name, exact_name, lookback_months=1):
    """Fetch ads active in the current month only (approximates currently active ads)."""
    today = date.today()
    date_range = month_date_range(today.year, today.month)
    ads = []
    for start in range(0, 500, 10):
        url = (
            f"https://api.linkedin.com/rest/adLibrary"
            f"?q=criteria&dateRange={date_range}"
            f"&advertiser={quote(search_name)}&count=10&start={start}"
        )
        req = Request(url, headers=HEADERS)
        try:
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except HTTPError as e:
            if e.code == 429:
                print("    Rate limited, waiting 65s..."); time.sleep(65); continue
            break
        elements = data.get("elements", [])
        if not elements: break
        for el in elements:
            adv = el.get("details", {}).get("advertiser", {})
            if adv.get("advertiserName", "").lower() == exact_name.lower():
                ads.append({
                    "adUrl":       el.get("adUrl", ""),
                    "type":        el.get("details", {}).get("type", ""),
                    "adTargeting": el.get("details", {}).get("adTargeting", []),
                    "adPayer":     adv.get("adPayer", ""),
                    "advertiserUrl": adv.get("advertiserUrl", ""),
                })
        total = data.get("paging", {}).get("total", 0)
        if start + 10 >= total: break
        time.sleep(2)
    return ads

# ── Ad Detail Scraper ─────────────────────────────────────────────────────────
def unescape(text):
    text = re.sub(r"<a [^>]+>", "", text)
    text = re.sub(r"</a>", "", text)
    return html.unescape(re.sub(r"<[^>]+>", " ", text)).strip()

def parse_detail_page(h, ad_url):
    r = {"url": ad_url, "body": "", "headline": "", "cta": "", "ad_type": "",
         "image_url": "", "is_thought_leadership": False, "poster_name": "", "poster_title": "",
         "landing_url": "", "likes": 0, "comments": 0,
         "impression_range": "", "run_dates": "", "country_impressions": [],
         "targeting_params": {}, "paid_by": "",
         "utm_campaign": "", "utm_source": "", "utm_medium": "",
         "offer_type": "", "lp_title": "", "lp_h1": "", "cta_stage": ""}

    m = re.search(r'class="commentary__content[^"]*"[^>]*>(.*?)</p>', h, re.DOTALL)
    if m: r["body"] = unescape(m.group(1))

    m = re.search(r'sponsored-content-headline[^>]*>.*?<h2[^>]*>(.*?)</h2>', h, re.DOTALL)
    if m: r["headline"] = unescape(m.group(1))

    m = re.search(r'data-tracking-control-name="ad_library_ad_detail_cta"[^>]*>(.*?)</button>', h, re.DOTALL)
    if m: r["cta"] = unescape(m.group(1))

    m = re.search(r'<p class="text-sm mb-1 text-color-text[^"]*">(.*?)</p>', h)
    if m: r["ad_type"] = unescape(m.group(1))

    # Paid by
    m = re.search(r'Paid for by\s*</[^>]+>\s*<[^>]+>\s*([^<]{2,60})<', h)
    if m: r["paid_by"] = m.group(1).strip()

    # Run dates: "Ran from May 14, 2026 to Jun 8, 2026"
    m = re.search(r'Ran from ([A-Za-z]+ \d+, \d{4}) to ([A-Za-z]+ \d+, \d{4})', h)
    if m: r["run_dates"] = f"{m.group(1)} – {m.group(2)}"
    else:
        m = re.search(r'Ran from ([A-Za-z]+ \d+, \d{4})', h)
        if m: r["run_dates"] = f"From {m.group(1)}"

    # Total impressions range
    m = re.search(r'Total Impressions.*?font-semibold[^>]*>([^<]{2,20})<', h, re.DOTALL)
    if m: r["impression_range"] = m.group(1).strip()

    # Country impressions: aria-label="France, impressions 15%"
    r["country_impressions"] = re.findall(
        r'aria-label="([^"]+), impressions (\d+(?:\.\d+)?%|<1%)"', h
    )

    # Landing page URL - find first non-LinkedIn, non-static external link
    ext_links = re.findall(r'href="(https?://(?!(?:www\.)?linkedin\.com|static\.licdn\.com|about\.linkedin\.com)[^"]+)"', h)
    if ext_links:
        r["landing_url"] = html.unescape(ext_links[0])

    # UTM parameter decoding for campaign intelligence
    if r["landing_url"] and "utm_campaign=" in r["landing_url"]:
        utm_m = re.search(r'utm_campaign=([^&"]+)', r["landing_url"])
        if utm_m: r["utm_campaign"] = utm_m.group(1)
        utm_src = re.search(r'utm_source=([^&"]+)', r["landing_url"])
        if utm_src: r["utm_source"] = utm_src.group(1)
        utm_med = re.search(r'utm_medium=([^&"]+)', r["landing_url"])
        if utm_med: r["utm_medium"] = utm_med.group(1)

    # Engagement: likes and comments
    m = re.search(r'(\d[\d,]*)\s*(?:reaction|like)', h, re.IGNORECASE)
    if m: r["likes"] = int(m.group(1).replace(",", ""))
    m = re.search(r'(\d[\d,]*)\s*comment', h, re.IGNORECASE)
    if m: r["comments"] = int(m.group(1).replace(",", ""))

    # Targeting parameters table
    param_rows = re.findall(
        r'<p[^>]+truncate[^>]*>([^<]{3,40})</p>.*?'
        r'type="(check|minus)".*?type="(check|minus)"',
        h, re.DOTALL
    )
    for param, targeted, excluded in param_rows:
        r["targeting_params"][param.strip()] = {
            "targeted": targeted == "check",
            "excluded": excluded == "check"
        }

    # Image (single image ads)
    m = re.search(r'ad-preview__dynamic-dimensions-image[^>]+data-delayed-url="([^"]+)"', h)
    if not m:
        m = re.search(r'data-delayed-url="([^"]+)"[^>]+ad-preview__dynamic-dimensions-image', h)
    if m:
        r["image_url"] = html.unescape(m.group(1))
    else:
        m = re.search(r'data-poster-url="([^"]+)"', h)
        if m: r["image_url"] = html.unescape(m.group(1))

    # Thought leadership detection
    if "profile-displayphoto" in h[3000:7000]:
        r["is_thought_leadership"] = True
        idx = h.find("profile-displayphoto", 3000)
        chunk = h[max(0, idx-500):idx+1500]
        names = re.findall(r'font-bold[^>]*>[\s\n]*([A-Z][a-zA-Z ]{2,40})[\s\n]*<', chunk)
        if names: r["poster_name"] = names[0]

    return r

def fetch_detail(url, retries=2):
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers=WEB_HEADERS)
            with urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except HTTPError as e:
            if e.code == 429:
                time.sleep(30 * (attempt + 1)); continue
            return None
        except Exception:
            return None
    return None

def scrape_landing_page(url):
    """Fetch landing page and extract offer intelligence."""
    if not url or len(url) > 300:
        return {}
    try:
        req = Request(url, headers=WEB_HEADERS)
        with urlopen(req, timeout=10) as resp:
            h = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return {}
    result = {}
    m = re.search(r'<title[^>]*>(.*?)</title>', h, re.DOTALL)
    if m: result["lp_title"] = re.sub(r'<[^>]+>', '', m.group(1)).strip()[:120]
    m = re.search(r'<h1[^>]*>(.*?)</h1>', h, re.DOTALL)
    if m: result["lp_h1"] = re.sub(r'<[^>]+>', '', m.group(1)).strip()[:120]
    m = re.search(r'meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{10,200})', h, re.IGNORECASE)
    if m: result["lp_meta"] = m.group(1).strip()
    # Detect offer type from URL + page content
    combined = (url + " " + result.get("lp_title","") + " " + result.get("lp_h1","")).lower()
    if any(x in combined for x in ["webinar","register","event","live"]):   result["offer_type"] = "Webinar/Event"
    elif any(x in combined for x in ["download","ebook","guide","checklist","template","report","whitepaper"]): result["offer_type"] = "Content Download"
    elif any(x in combined for x in ["free trial","start free","try free","sign up free"]): result["offer_type"] = "Free Trial"
    elif any(x in combined for x in ["demo","book a","schedule","talk to","request a"]): result["offer_type"] = "Demo Request"
    elif any(x in combined for x in ["pricing","plans","buy","purchase"]): result["offer_type"] = "Pricing/Purchase"
    elif any(x in combined for x in ["case study","customer story","how .* uses"]): result["offer_type"] = "Case Study"
    else: result["offer_type"] = "Website/Landing Page"
    return result

def classify_cta(cta_text, landing_url=""):
    """Only classify funnel stage if TOFU/MOFU/BOFU appears explicitly in the URL."""
    combined = (landing_url or "").lower()
    if "tofu" in combined: return "TOFU"
    if "mofu" in combined: return "MOFU"
    if "bofu" in combined: return "BOFU"
    return ""

def download_image(img_url, path):
    try:
        req = Request(img_url, headers=WEB_HEADERS)
        with urlopen(req, timeout=15) as resp:
            Path(path).write_bytes(resp.read())
        return True
    except Exception:
        return False

# ── Cache ─────────────────────────────────────────────────────────────────────
def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}

def save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, indent=2))

# ── Gallery HTML ──────────────────────────────────────────────────────────────
TYPE_ICONS = {
    "Single Image Ad": "IMG",
    "Video Ad": "VID",
    "Carousel Ad": "CAR",
    "InMail": "MAIL",
    "Document Ad": "DOC",
}

FORMAT_LABELS = {
    "Single Image Ad":    "Single Image",
    "Video Ad":           "Video",
    "Carousel Ad":        "Carousel",
    "Document Ad":        "Document",
    "LinkedIn Article Ad":"Article",
    "Message Ad":         "Message",
    "Conversation Ad":    "Conversation",
    "Text Ad":            "Text",
    "Dynamic Ad":         "Dynamic",
    "Spotlight Ad":       "Spotlight",
    "Event Ad":           "Event",
    "Lead Gen Form Ad":   "Lead Gen",
    "InMail":             "InMail",
}

def img_to_b64(path):
    try:
        return base64.b64encode(Path(path).read_bytes()).decode()
    except Exception:
        return None

def dedup_ads(ads):
    """Deduplicate ads with identical creatives (same image + headline).
    Keeps the most recent (highest ID). Records duplicate count on card."""
    seen = {}
    for ad in ads:
        # Key: image_url (primary) or headline+body (fallback for ads without images)
        img  = ad.get("image_url", "").split("?")[0]  # strip query params
        head = ad.get("headline", "")
        body = (ad.get("body", "") or "")[:80]
        key  = img if img else f"{head}|{body}"
        if not key:
            key = ad.get("url", "")  # absolute fallback

        if key not in seen:
            seen[key] = ad.copy()
            seen[key]["_variants"] = 1
        else:
            seen[key]["_variants"] += 1
            # Keep the higher-ID (more recent) entry
            existing_id = int(seen[key].get("url","0").split("/")[-1] or 0)
            this_id     = int(ad.get("url","0").split("/")[-1] or 0)
            if this_id > existing_id:
                variants = seen[key]["_variants"]
                seen[key] = ad.copy()
                seen[key]["_variants"] = variants

    return list(seen.values())


def generate_gallery(all_company_data, new_ids, today_str):

    # Load Sprinto icon SVG for inline embedding
    logo_svg = ""
    svg_path = os.path.join(os.path.dirname(__file__), "sprinto_icon.svg")
    if os.path.exists(svg_path):
        with open(svg_path) as f:
            logo_svg = f.read().strip()

    # Pre-process: dedup and drop ads with no image AND no headline
    processed = {}
    for company, ads in all_company_data.items():
        deduped = dedup_ads(ads)
        valid = [a for a in deduped
                 if a.get("local_image") or a.get("image_url") or a.get("headline","").strip()]
        processed[company] = valid

    total_unique = sum(len(v) for v in processed.values())
    total_raw    = sum(len(v) for v in all_company_data.values())
    new_count    = len(new_ids)
    tl_total     = sum(1 for ads in processed.values() for a in ads if a.get("is_thought_leadership"))

    # Stats per company for sidebar
    company_stats_html = ""
    for company, ads in processed.items():
        color   = COMPANY_COLORS.get(company, "#555")
        tl_c    = sum(1 for a in ads if a.get("is_thought_leadership"))
        new_c   = sum(1 for a in ads
                      if a.get("url","").split("/")[-1].isdigit()
                      and int(a["url"].split("/")[-1]) in new_ids)
        company_stats_html += f"""
        <button class="co-btn" data-company="{company}"
                onclick="filterCompany('{company}',this)"
                style="--co:{color}">
          <span class="co-dot" style="background:{color}"></span>
          <span class="co-name">{company.title()}</span>
          <span class="co-count">{len(ads)}</span>
          {f'<span class="co-new">+{new_c}</span>' if new_c else ''}
        </button>"""

    # Cards
    all_types = set()
    cards_html = ""
    for company, ads in processed.items():
        color = COMPANY_COLORS.get(company, "#555")
        for i, ad in enumerate(ads, 1):
            ad_id   = ad.get("url","").split("/")[-1]
            is_new  = ad_id.isdigit() and int(ad_id) in new_ids
            age_lbl = ad.get("age_label", "")
            age_col = ad.get("age_color", "#555")
            ad_type = ad.get("ad_type", ad.get("type", ""))
            type_lbl= TYPE_ICONS.get(ad_type, ad_type[:3].upper() if ad_type else "—")
            is_tl   = ad.get("is_thought_leadership", False)
            poster  = ad.get("poster_name", "")
            headline= (ad.get("headline") or "").strip()
            copy    = (ad.get("body") or "").strip()
            cta     = (ad.get("cta") or "").strip()
            variants= ad.get("_variants", 1)
            img_path= ad.get("local_image", "")
            url     = ad.get("url","")
            locations = ad.get("locations", [])
            all_types.add(ad_type)

            if img_path and Path(img_path).exists():
                b64 = img_to_b64(img_path)
                img_html = (f'<img class="card-img" src="data:image/jpeg;base64,{b64}" loading="lazy">'
                            if b64 else '<div class="card-img-empty"><span>NO PREVIEW</span></div>')
            elif ad_type and "Video" in ad_type:
                img_html = '<div class="card-img-empty video"><span>&#9654; VIDEO</span></div>'
            else:
                img_html = '<div class="card-img-empty"><span>NO PREVIEW</span></div>'

            new_ribbon = '<div class="new-ribbon">NEW</div>' if is_new else ''
            tl_badge   = f'<span class="badge badge-tl">TL{(" · " + poster) if poster else ""}</span>' if is_tl else ''
            var_badge  = f'<span class="badge badge-var">{variants}x</span>' if variants > 1 else ''

            copy_preview = copy[:160] + ("…" if len(copy) > 160 else "")

            # Location display: show first 3, then +N more
            if locations:
                shown = locations[:3]
                extra = len(locations) - 3
                loc_text = ", ".join(shown) + (f" +{extra}" if extra > 0 else "")
                loc_html = f'<div class="card-location">&#128205; {loc_text}</div>'
            else:
                loc_html = ""

            cards_html += f"""
<div class="card-wrap" data-company="{company}" data-type="{ad_type}" data-tl="{'yes' if is_tl else 'no'}">
  <div class="card {'card-new' if is_new else ''}" style="--co:{color}">
    {new_ribbon}
    <div class="card-img-wrap">{img_html}</div>
    <div class="card-body">
      <div class="card-meta">
        <span class="badge badge-co" style="background:{color}18;color:{color};border-color:{color}33">{company.upper()}</span>
        <span class="badge badge-type">{type_lbl}</span>
        {var_badge}{tl_badge}
        <span class="badge badge-age" style="color:{age_col}">{age_lbl}</span>
      </div>
      <div class="card-headline">{headline or '<em style="color:#444">No headline</em>'}</div>
      {f'<div class="card-copy">{copy_preview}</div>' if copy_preview else ''}
      {f'<div class="card-cta">{cta} &rarr;</div>' if cta else ''}
      {loc_html}
    </div>
    <a class="card-link" href="{url}" target="_blank">View Ad &rarr;</a>
  </div>
</div>"""

    # Type filter pills
    type_pills = '<button class="pill pill-active" data-type="all" onclick="filterType(\'all\',this)">All formats</button>'
    for t in sorted(all_types):
        if t:
            display = FORMAT_LABELS.get(t, t.replace(" Ad", "").strip())
            type_pills += f'<button class="pill" data-type="{t}" onclick="filterType(\'{t}\',this)">{display}</button>'
    tl_pills = """
    <button class="pill pill-active" data-tl="all" onclick="filterTL('all',this)">All ads</button>
    <button class="pill" data-tl="yes" onclick="filterTL('yes',this)">Thought leadership</button>
    <button class="pill" data-tl="no"  onclick="filterTL('no',this)">Brand ads</button>"""
    emea_pills = """
    <button class="pill pill-active" data-emea="all" onclick="filterEMEA('all',this)">All regions</button>
    <button class="pill" data-emea="yes" onclick="filterEMEA('yes',this)">EMEA only</button>
    <button class="pill" data-emea="no"  onclick="filterEMEA('no',this)">Non-EMEA</button>"""

    css = """
@import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=Lora:wght@600&display=swap');

:root {
  --bg:      #F6F5F2;
  --bg2:     #FFFFFF;
  --bg3:     #EEEDE9;
  --border:  #E0DED9;
  --border2: #D0CEC8;
  --text:    #1F0214;
  --muted:   #7A6F78;
  --brand:   #650A41;
  --texas:   #DDF07E;
  --texas-d: #b8cc5a;
  --new-bg:  #DDF07E;
  --new-txt: #1F0214;
  --sidebar: 230px;
  --topbar:  64px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body { font-family: 'Instrument Sans', -apple-system, sans-serif;
       background: var(--bg); color: var(--text); min-height: 100vh; }

/* ── Top bar ── */
.topbar { position: fixed; top: 0; left: 0; right: 0; height: var(--topbar);
          background: var(--brand); border-bottom: 1px solid #4a0730;
          display: flex; align-items: center; padding: 0 24px; gap: 24px;
          z-index: 100; }
.logo { display: flex; align-items: center; gap: 10px; text-decoration: none; }
.logo-mark { width: 36px; height: 36px; flex-shrink: 0; display: block; }
.logo-mark svg { width: 36px; height: 36px; display: block; }
.logo-text { font-size: 15px; font-weight: 700; color: #fff; letter-spacing: -.2px; }
.logo-sub  { font-size: 11px; color: rgba(255,255,255,.55); font-weight: 400; }
.topbar-divider { width: 1px; height: 28px; background: rgba(255,255,255,.15); }
.stat-chip { display: flex; flex-direction: column; align-items: center; min-width: 56px; }
.stat-chip .val { font-size: 18px; font-weight: 700; color: #fff; line-height: 1; }
.stat-chip .lbl { font-size: 10px; color: rgba(255,255,255,.5); margin-top: 2px;
                  text-transform: uppercase; letter-spacing: .06em; }
.stat-chip.accent .val { color: var(--texas); }
.topbar-date { margin-left: auto; font-size: 11px; color: rgba(255,255,255,.5); }

/* ── Layout ── */
.layout { display: flex; padding-top: var(--topbar); min-height: 100vh; }

/* ── Sidebar ── */
.sidebar { width: var(--sidebar); flex-shrink: 0; position: sticky; top: var(--topbar);
           height: calc(100vh - var(--topbar)); overflow-y: auto; padding: 20px 14px;
           border-right: 1px solid var(--border); background: var(--bg2); }
.sidebar-label { font-size: 10px; font-weight: 700; color: var(--muted);
                 text-transform: uppercase; letter-spacing: .1em;
                 padding: 0 8px; margin-bottom: 6px; margin-top: 22px; }
.sidebar-label:first-child { margin-top: 0; }
.co-btn { display: flex; align-items: center; gap: 8px; width: 100%;
          padding: 8px 10px; border-radius: 8px; border: 1px solid transparent;
          background: transparent; color: var(--muted); font-size: 12px;
          font-family: inherit; cursor: pointer; transition: all .12s; text-align: left; }
.co-btn:hover { background: var(--bg3); color: var(--text); }
.co-btn.active { background: #650A4110; border-color: #650A4130; color: var(--brand);
                 font-weight: 600; }
.co-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.co-name { flex: 1; font-weight: 500; }
.co-count { font-size: 11px; color: var(--muted); }
.co-new { font-size: 10px; font-weight: 700; color: var(--brand);
          background: var(--texas); padding: 1px 5px; border-radius: 4px; }
.co-all { font-weight: 600 !important; }

/* ── Main ── */
.main { flex: 1; min-width: 0; padding: 28px; }

/* ── Filter pills (sidebar) ── */
.sidebar-pill { display: flex; width: 100%; padding: 7px 10px; border-radius: 8px;
                border: 1px solid transparent; background: transparent;
                color: var(--muted); font-size: 12px; font-weight: 500;
                font-family: inherit; cursor: pointer; transition: all .12s;
                text-align: left; margin-bottom: 2px; }
.sidebar-pill:hover { background: var(--bg3); color: var(--text); }
.sidebar-pill.pill-active { background: var(--brand); border-color: var(--brand);
                            color: #fff !important; font-weight: 600; }
/* legacy pill-row (unused but keep for safety) */
.pill-row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 22px; }
.pill { padding: 5px 13px; border-radius: 20px; border: 1px solid var(--border2);
        background: var(--bg2); color: var(--muted); font-size: 11px; font-weight: 500;
        font-family: inherit; cursor: pointer; transition: all .12s; }
.pill:hover { border-color: var(--brand); color: var(--brand); }
.pill-active { background: var(--brand); border-color: var(--brand);
               color: #fff !important; }

/* ── Grid ── */
.grid { display: grid;
        grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
        gap: 16px; }

/* ── Card ── */
.card-wrap { display: flex; }
.card { background: var(--bg2); border: 1px solid var(--border);
        border-radius: 12px; overflow: hidden; display: flex;
        flex-direction: column; width: 100%; position: relative;
        transition: transform .18s, box-shadow .18s;
        border-top: 3px solid var(--co); }
.card:hover { transform: translateY(-2px);
              box-shadow: 0 8px 32px rgba(101,10,65,.1); }
.card-new { border-color: var(--brand) !important;
            box-shadow: 0 0 0 1px #650A4122; }

.new-ribbon { position: absolute; top: 10px; right: 10px; z-index: 2;
              background: var(--texas); color: var(--brand); font-size: 9px;
              font-weight: 800; padding: 3px 8px; border-radius: 4px;
              letter-spacing: .08em; }

/* Image */
.card-img-wrap { width: 100%; background: var(--bg3); overflow: hidden; }
.card-img { width: 100%; height: auto; display: block;
            max-height: 340px; object-fit: contain; }
.card-img-empty { width: 100%; height: 150px; display: flex;
                  align-items: center; justify-content: center;
                  color: var(--border2); font-size: 11px;
                  letter-spacing: .08em; font-weight: 600; background: var(--bg3); }
.card-img-empty.video { font-size: 22px; color: var(--muted); }

/* Body */
.card-body { padding: 14px 16px 10px; flex: 1; }
.card-meta  { display: flex; gap: 5px; flex-wrap: wrap; margin-bottom: 10px; }

.badge { padding: 2px 7px; border-radius: 5px; font-size: 10px; font-weight: 600;
         letter-spacing: .04em; border: 1px solid transparent; }
.badge-type { background: var(--bg3); color: var(--muted); border-color: var(--border2); }
.badge-tl   { background: #650A4110; color: var(--brand); border-color: #650A4128; }
.badge-var  { background: var(--bg3); color: var(--muted); border-color: var(--border2); }
.badge-age  { background: transparent; border: none; padding-left: 0;
              font-weight: 500; color: var(--muted); }

.card-headline { font-size: 13px; font-weight: 600; color: var(--text);
                 line-height: 1.5; margin-bottom: 7px; }
.card-copy { font-size: 11.5px; color: var(--muted); line-height: 1.65;
             display: -webkit-box; -webkit-line-clamp: 3;
             -webkit-box-orient: vertical; overflow: hidden; }
.card-cta      { font-size: 11px; color: var(--brand); margin-top: 8px; font-weight: 600; }

/* Targeting block */
.card-targeting { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 4px; }
.trow    { display: flex; gap: 6px; align-items: flex-start; font-size: 10.5px; }
.tfacet  { color: var(--muted); white-space: nowrap; min-width: 90px; flex-shrink: 0; }
.tval    { color: var(--text); line-height: 1.4; }

/* Landing + engagement */
.card-landing    { font-size: 10.5px; margin-top: 8px; padding-top: 8px;
                   border-top: 1px solid var(--border); color: var(--muted); }
.card-landing a  { color: var(--brand); text-decoration: none; font-weight: 600; }
.card-landing a:hover { text-decoration: underline; }
.offer-badge { display: inline-block; margin-left: 6px; padding: 1px 6px; border-radius: 4px;
               background: #650A4110; color: var(--brand); font-size: 9.5px; font-weight: 700;
               letter-spacing: .04em; border: 1px solid #650A4128; }
.stage-badge { display: inline-block; margin-left: 4px; padding: 1px 6px; border-radius: 4px;
               font-size: 9.5px; font-weight: 700; letter-spacing: .04em; }
.stage-tofu  { background: #d1fae510; color: #065f46; border: 1px solid #a7f3d040; }
.stage-mofu  { background: #fef3c710; color: #92400e; border: 1px solid #fde68a40; }
.stage-bofu  { background: #fee2e210; color: #991b1b; border: 1px solid #fca5a540; }
.lp-sub  { font-size: 10px; color: var(--text); margin-top: 4px; font-style: italic; }
.lp-utm  { font-size: 9.5px; color: var(--muted); margin-top: 2px; font-family: monospace;
           overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-engagement { font-size: 10.5px; color: var(--muted); margin-top: 5px; }

/* EMEA badge */
.badge-emea { background: #1e3a5f18; color: #1d6fa4; border-color: #1e3a5f33; }

/* Performance row */
.card-perf    { font-size: 10.5px; color: var(--muted); margin-top: 10px; padding-top: 10px;
                border-top: 1px solid var(--border); display: flex; flex-wrap: wrap; gap: 6px; }
.perf-imp     { color: var(--brand); font-weight: 600; }
.perf-dates   { color: var(--muted); }

/* Country impressions */
.card-countries { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border); }
.ci-label   { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em;
              color: var(--muted); margin-bottom: 7px; }
.ci-row     { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.ci-country { font-size: 10.5px; color: var(--text); min-width: 110px; flex-shrink: 0; }
.ci-bar-wrap{ flex: 1; height: 4px; background: var(--bg3); border-radius: 2px; overflow: hidden; }
.ci-bar     { height: 100%; background: var(--brand); border-radius: 2px; transition: width .3s; }
.ci-pct     { font-size: 10px; color: var(--muted); min-width: 28px; text-align: right; }
.ci-more    { font-size: 10px; color: var(--muted); margin-top: 4px; }

/* Targeting params table */
.card-tp    { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border); }
.tp-table   { width: 100%; border-collapse: collapse; font-size: 10.5px; }
.tp-table thead tr { border-bottom: 1px solid var(--border); }
.tp-name    { padding: 3px 0; color: var(--text); text-align: left; }
.tp-val     { padding: 3px 4px; color: var(--muted); text-align: center; width: 44px; }
.tp-table thead .tp-name, .tp-table thead .tp-val { font-weight: 700; font-size: 9.5px;
  text-transform: uppercase; letter-spacing: .05em; color: var(--muted); padding-bottom: 5px; }

/* Link button */
.card-link { display: block; text-align: center; padding: 9px 16px;
             margin: 10px 16px 14px; background: var(--bg3);
             border: 1px solid var(--border2); border-radius: 8px;
             color: var(--muted); font-size: 11px; font-weight: 500;
             text-decoration: none; transition: all .12s; }
.card-link:hover { background: var(--brand); border-color: var(--brand);
                   color: #fff; }

/* ── Section heading ── */
.section-head { display: flex; align-items: center; gap: 12px;
                margin-bottom: 16px; padding-bottom: 12px;
                border-bottom: 1px solid var(--border); }
.section-dot  { width: 10px; height: 10px; border-radius: 50%; }
.section-name { font-size: 15px; font-weight: 700; }
.section-stat { font-size: 12px; color: var(--muted); margin-left: auto; }

.company-section { margin-bottom: 48px; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 3px; }

/* Empty state */
.empty { text-align: center; padding: 80px 20px; color: var(--muted);
         font-size: 14px; display: none; }
"""

    js = """
let activeCompany = 'all', activeType = 'all', activeTL = 'all', activeEMEA = 'all';

function applyFilters() {
  let visible = 0;
  document.querySelectorAll('.card-wrap').forEach(c => {
    const co = c.dataset.company, tp = c.dataset.type, tl = c.dataset.tl, em = c.dataset.emea;
    const show = (activeCompany === 'all' || co === activeCompany) &&
                 (activeType   === 'all' || tp === activeType)    &&
                 (activeTL     === 'all' || tl === activeTL)      &&
                 (activeEMEA   === 'all' || em === activeEMEA);
    c.style.display = show ? '' : 'none';
    if (show) visible++;
  });
  document.querySelectorAll('.company-section').forEach(s => {
    const co = s.dataset.company;
    const hasVisible = [...s.querySelectorAll('.card-wrap')]
      .some(c => c.style.display !== 'none');
    s.style.display = hasVisible ? '' : 'none';
  });
  document.querySelector('.empty').style.display = visible ? 'none' : 'block';
}

function filterCompany(val, btn) {
  activeCompany = val;
  document.querySelectorAll('.co-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilters();
}
function filterType(val, btn) {
  activeType = val;
  document.querySelectorAll('[data-type]').forEach(b => {
    if (b.classList.contains('pill')) b.classList.remove('pill-active');
  });
  btn.classList.add('pill-active');
  applyFilters();
}
function filterTL(val, btn) {
  activeTL = val;
  document.querySelectorAll('[data-tl]').forEach(b => {
    if (b.classList.contains('pill')) b.classList.remove('pill-active');
  });
  btn.classList.add('pill-active');
  applyFilters();
}
function filterEMEA(val, btn) {
  activeEMEA = val;
  document.querySelectorAll('[data-emea]').forEach(b => {
    if (b.classList.contains('pill')) b.classList.remove('pill-active');
  });
  btn.classList.add('pill-active');
  applyFilters();
}
"""

    # Build per-company sections
    sections_html = ""
    for company, ads in processed.items():
        color   = COMPANY_COLORS.get(company, "#555")
        tl_c    = sum(1 for a in ads if a.get("is_thought_leadership"))
        new_c   = sum(1 for a in ads
                      if (a.get("url","").split("/")[-1]).isdigit()
                      and int(a["url"].split("/")[-1]) in new_ids)
        sections_html += f"""
<div class="company-section" data-company="{company}">
  <div class="section-head">
    <div class="section-dot" style="background:{color}"></div>
    <div class="section-name" style="color:{color}">{company.upper()}</div>
    {f'<span class="badge badge-co" style="background:#DDF07E;color:#650A41;border-color:#b8cc5a">+{new_c} new</span>' if new_c else ''}
    <div class="section-stat">{len(ads)} ads &nbsp;&middot;&nbsp; {tl_c} thought leadership</div>
  </div>
  <div class="grid">
"""
        for ad in ads:
            ad_id   = ad.get("url","").split("/")[-1]
            is_new  = ad_id.isdigit() and int(ad_id) in new_ids
            age_lbl = ad.get("age_label", "")
            age_col = ad.get("age_color", "#555")
            ad_type = ad.get("ad_type", ad.get("type", ""))
            type_lbl= TYPE_ICONS.get(ad_type, ad_type[:3].upper() if ad_type else "—")
            is_tl   = ad.get("is_thought_leadership", False)
            poster  = ad.get("poster_name", "")
            headline= (ad.get("headline") or "").strip()
            copy    = (ad.get("body") or "").strip()
            cta     = (ad.get("cta") or "").strip()
            variants           = ad.get("_variants", 1)
            img_path           = ad.get("local_image", "")
            url                = ad.get("url","")
            locations          = ad.get("locations", [])
            targeting          = ad.get("targeting", {})
            landing_url        = ad.get("landing_url", "")
            likes              = ad.get("likes", 0)
            comments           = ad.get("comments", 0)
            impression_range   = ad.get("impression_range", "")
            run_dates          = ad.get("run_dates", "")
            country_impressions= ad.get("country_impressions", [])
            targeting_params   = ad.get("targeting_params", {})
            offer_type         = ad.get("offer_type", "")
            lp_title           = ad.get("lp_title", "")
            lp_h1              = ad.get("lp_h1", "")
            utm_campaign       = ad.get("utm_campaign", "")
            url_signals = " ".join([ad.get("utm_campaign",""), ad.get("utm_medium",""), ad.get("landing_url","")])
            cta_stage = classify_cta("", url_signals)

            if img_path and Path(img_path).exists():
                b64 = img_to_b64(img_path)
                img_html = (f'<img class="card-img" src="data:image/jpeg;base64,{b64}" loading="lazy">'
                            if b64 else '<div class="card-img-empty"><span>NO PREVIEW</span></div>')
            elif ad_type and "Video" in ad_type:
                img_html = '<div class="card-img-empty video"><span>&#9654;</span></div>'
            else:
                img_html = '<div class="card-img-empty"><span>NO PREVIEW</span></div>'

            new_ribbon = '<div class="new-ribbon">NEW</div>' if is_new else ''
            tl_badge   = f'<span class="badge badge-tl">TL{(" · " + poster) if poster else ""}</span>' if is_tl else ''
            var_badge  = f'<span class="badge badge-var">{variants}x</span>' if variants > 1 else ''

            # EMEA detection
            emea_terms = {"emea","europe","european","uk","united kingdom","germany","france",
                          "netherlands","nordics","dach","benelux","ireland","spain","italy",
                          "sweden","norway","denmark","finland","israel","middle east","africa"}
            is_emea = any(any(term in loc.lower() for term in emea_terms) for loc in locations)
            emea_badge = '<span class="badge badge-emea">EMEA</span>' if is_emea else ''

            # Engagement
            eng_parts = []
            if likes:    eng_parts.append(f"👍 {likes:,}")
            if comments: eng_parts.append(f"💬 {comments:,}")
            eng_html = f'<div class="card-engagement">{" &nbsp; ".join(eng_parts)}</div>' if eng_parts else ""

            # Full targeting breakdown
            targeting_rows = []
            label_map = {"Location": "📍", "Language": "🗣", "Job": "💼",
                         "Audience": "🎯", "Company": "🏢", "Industry": "🏭"}
            for facet, segs in targeting.items():
                if facet == "Location": continue  # shown separately
                if segs:
                    icon  = label_map.get(facet, "•")
                    shown = segs[:3]
                    extra = len(segs) - 3
                    txt   = ", ".join(shown) + (f" +{extra}" if extra > 0 else "")
                    targeting_rows.append(f'<div class="trow"><span class="tfacet">{icon} {facet}</span><span class="tval">{txt}</span></div>')

            loc_row = ""
            if locations:
                shown = locations[:4]
                extra = len(locations) - 4
                txt   = ", ".join(shown) + (f" +{extra}" if extra > 0 else "")
                loc_row = f'<div class="trow"><span class="tfacet">📍 Location</span><span class="tval">{txt}</span></div>'

            targeting_html = ""
            if loc_row or targeting_rows:
                inner = loc_row + "".join(targeting_rows)
                targeting_html = f'<div class="card-targeting">{inner}</div>'

            # Landing page + offer intelligence
            landing_html = ""
            if landing_url:
                domain = re.sub(r"https?://(www\.)?", "", landing_url).split("/")[0]
                offer_badge = f' <span class="offer-badge">{offer_type}</span>' if offer_type else ""
                stage_badge = f' <span class="stage-badge stage-{cta_stage.lower()}">{cta_stage}</span>' if cta_stage else ""
                lp_sub = f'<div class="lp-sub">{lp_h1 or lp_title}</div>' if (lp_h1 or lp_title) else ""
                utm_sub = f'<div class="lp-utm">{utm_campaign}</div>' if utm_campaign else ""
                landing_html = f'<div class="card-landing">🔗 <a href="{landing_url}" target="_blank">{domain}</a>{offer_badge}{stage_badge}{lp_sub}{utm_sub}</div>'

            # Impressions + run dates
            perf_parts = []
            if impression_range: perf_parts.append(f'<span class="perf-imp">📊 {impression_range} impressions</span>')
            if run_dates:        perf_parts.append(f'<span class="perf-dates">📅 {run_dates}</span>')
            perf_html = f'<div class="card-perf">{" &nbsp;·&nbsp; ".join(perf_parts)}</div>' if perf_parts else ""

            # Country impression breakdown
            country_html = ""
            if country_impressions:
                rows = ""
                for country, pct in country_impressions[:12]:
                    pct_val = int(pct.replace("%","").replace("<","").strip()) if "%" in pct else 0
                    bar_w   = max(2, pct_val)
                    rows += f'<div class="ci-row"><span class="ci-country">{country}</span><div class="ci-bar-wrap"><div class="ci-bar" style="width:{bar_w}%"></div></div><span class="ci-pct">{pct}</span></div>'
                extra = len(country_impressions) - 12
                if extra > 0:
                    rows += f'<div class="ci-more">+{extra} more countries</div>'
                country_html = f'<div class="card-countries"><div class="ci-label">Impressions by country</div>{rows}</div>'

            # Targeting params table
            tp_html = ""
            if targeting_params:
                rows = ""
                for param, v in targeting_params.items():
                    t = "✓" if v["targeted"] else "—"
                    x = "✓" if v["excluded"] else "—"
                    rows += f'<tr><td class="tp-name">{param}</td><td class="tp-val">{t}</td><td class="tp-val">{x}</td></tr>'
                tp_html = f'<div class="card-tp"><table class="tp-table"><thead><tr><th class="tp-name">Parameter</th><th class="tp-val">Target</th><th class="tp-val">Excl.</th></tr></thead><tbody>{rows}</tbody></table></div>'

            sections_html += f"""
    <div class="card-wrap" data-company="{company}" data-type="{ad_type}" data-tl="{'yes' if is_tl else 'no'}" data-emea="{'yes' if is_emea else 'no'}">
      <div class="card {'card-new' if is_new else ''}" style="--co:{color}">
        {new_ribbon}
        <div class="card-img-wrap">{img_html}</div>
        <div class="card-body">
          <div class="card-meta">
            <span class="badge badge-type">{type_lbl}</span>
            {var_badge}{tl_badge}{emea_badge}
            <span class="badge badge-age" style="color:{age_col}">{age_lbl}</span>
          </div>
          <div class="card-headline">{headline or '<em style="opacity:.3">No headline</em>'}</div>
          {f'<div class="card-copy">{copy}</div>' if copy else ''}
          {f'<div class="card-cta">{cta} &rarr;</div>' if cta else ''}
          {targeting_html}
          {landing_html}
          {eng_html}
          {perf_html}
          {country_html}
          {tp_html}
        </div>
        <a class="card-link" href="{url}" target="_blank">View on LinkedIn Ad Library &rarr;</a>
      </div>
    </div>"""

        sections_html += "\n  </div>\n</div>"

    new_stat = f'<div class="stat-chip accent"><div class="val">+{new_count}</div><div class="lbl">New this week</div></div><div class="topbar-divider"></div>' if new_count else ''

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ads Intelligence - Sprinto</title>
<style>{css}</style>
</head>
<body>

<div class="topbar">
  <div class="logo">
    <div class="logo-mark">{logo_svg}</div>
    <div>
      <div class="logo-text">Sprinto</div>
      <div class="logo-sub">Ads Intelligence</div>
    </div>
  </div>
  <div class="topbar-divider"></div>
  <div class="stat-chip"><div class="val">{total_unique}</div><div class="lbl">Unique ads</div></div>
  <div class="stat-chip"><div class="val">{len(processed)}</div><div class="lbl">Competitors</div></div>
  <div class="stat-chip"><div class="val">{tl_total}</div><div class="lbl">Thought leadership</div></div>
  {new_stat}
  <div class="topbar-date">Updated {today_str} &nbsp;&middot;&nbsp; LinkedIn Ad Library</div>
</div>

<div class="layout">
  <aside class="sidebar">
    <div class="sidebar-label">Companies</div>
    <button class="co-btn co-all active" data-company="all" onclick="filterCompany('all',this)">
      <span class="co-name">All competitors</span>
      <span class="co-count">{total_unique}</span>
    </button>
    {company_stats_html}

    <div class="sidebar-label">Format</div>
    {type_pills.replace('<button class="pill', '<button class="pill sidebar-pill')}

    <div class="sidebar-label">Type</div>
    {tl_pills.replace('<button class="pill', '<button class="pill sidebar-pill')}

    <div class="sidebar-label">Region</div>
    {emea_pills.replace('<button class="pill', '<button class="pill sidebar-pill')}
  </aside>

  <main class="main">
    {sections_html}
    <div class="empty">No ads match the current filters.</div>
  </main>
</div>

<script>{js}</script>
</body>
</html>"""


# ── Helpers ───────────────────────────────────────────────────────────────────
RESEARCH_FILE = OUT_DIR / "competitor_research.json"
COPY_FILE     = OUT_DIR / "competitor_copy_with_images.json"

def load_research():
    if RESEARCH_FILE.exists():
        return json.loads(RESEARCH_FILE.read_text())
    return {}

def seed_cache_from_copy(cache):
    """Pre-populate cache with already-fetched copy data."""
    if not COPY_FILE.exists():
        return 0
    copy_data = json.loads(COPY_FILE.read_text())
    seeded = 0
    for company, ads in copy_data.items():
        for ad in ads:
            url   = ad.get("url", "")
            ad_id = url.split("/")[-1]
            if ad_id.isdigit() and ad_id not in cache:
                cache[ad_id] = {
                    "url":                  url,
                    "company":              company,
                    "body":                 ad.get("body", ""),
                    "headline":             ad.get("headline", ""),
                    "cta":                  ad.get("cta", ""),
                    "ad_type":              ad.get("ad_type", ad.get("format", "")),
                    "type":                 ad.get("format", ""),
                    "image_url":            ad.get("image_url", ""),
                    "local_image":          ad.get("local_image", ""),
                    "is_thought_leadership": False,
                    "poster_name":          "",
                    "age_label":            "unknown",
                    "age_color":            "#555",
                }
                seeded += 1
    return seeded


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", nargs="+", default=list(COMPETITORS.keys()))
    parser.add_argument("--no-fetch",  action="store_true", help="Regenerate gallery from cache only (no HTTP)")
    parser.add_argument("--delay",     type=float, default=0.8, help="Seconds between detail page requests")
    args = parser.parse_args()

    if not ACCESS_TOKEN and not args.no_fetch:
        print("ERROR: LINKEDIN_ACCESS_TOKEN not set"); sys.exit(1)

    today_str = date.today().strftime("%B %d, %Y")
    companies = {k: v for k, v in COMPETITORS.items() if k in args.company}

    # Load cache, seed from existing copy data, load previous run IDs
    cache    = load_cache()
    seeded   = seed_cache_from_copy(cache)
    if seeded:
        print(f"  Pre-seeded cache with {seeded} ads from existing copy data")
    prev_ids = set(json.loads(PREV_FILE.read_text()) if PREV_FILE.exists() else [])

    # Load base ad list from research file (no API call)
    research = load_research()

    all_company_data = {}
    current_ids = set()

    for company, config in companies.items():
        print(f"\n{'='*50}")
        print(f"  {company.upper()}")
        print(f"{'='*50}")

        # ── Step 1: Base ad list ───────────────────────────────────────────────
        if args.no_fetch:
            # Cache/research mode - no API calls
            if research.get(company):
                raw_ads = [
                    {"adUrl": a["adUrl"], "type": a.get("type",""), "adTargeting": a.get("adTargeting",[])}
                    for a in research[company]
                ]
                print(f"  Loaded {len(raw_ads)} ads from research file")
            else:
                raw_ads = [
                    {"adUrl": d["url"], "type": d.get("type",""), "adTargeting": []}
                    for d in cache.values() if d.get("company") == company
                ]
                print(f"  Cache mode: {len(raw_ads)} ads")
        else:
            # Fresh fetch - current month only (active ads)
            print(f"  Fetching active ads from API (current month)...")
            raw_ads = fetch_all_ads_for_company(config["search"], config["exact"])
            # Save to research file for future cache use
            research[company] = [{"adUrl": a["adUrl"], "type": a.get("type",""), "adTargeting": a.get("adTargeting",[])} for a in raw_ads]
            print(f"  Found {len(raw_ads)} active ads")

        # Sort by ID descending (newest first)
        raw_ads.sort(key=lambda a: int(a.get("adUrl","0").split("/")[-1])
                     if a.get("adUrl","").split("/")[-1].isdigit() else 0, reverse=True)

        # ── Step 2: Estimate start month from ad ID (no API needed) ──────────
        start_dates = {}  # populated per-ad below during enrichment

        # ── Step 3: Fetch detail + image for each uncached ad ─────────────────
        enriched = []
        needs_fetch = [a for a in raw_ads
                       if a.get("adUrl","").split("/")[-1] not in cache]
        cached_count = len(raw_ads) - len(needs_fetch)
        if needs_fetch:
            print(f"  {cached_count} ads from cache, fetching {len(needs_fetch)} new ads...")
        else:
            print(f"  All {cached_count} ads from cache")

        for idx, ad in enumerate(raw_ads):
            url   = ad.get("adUrl", "")
            ad_id = url.split("/")[-1]
            if not ad_id.isdigit():
                continue

            current_ids.add(int(ad_id))

            # Estimate start month from ad ID (instant, no API)
            age_lbl, age_col = estimate_start_month(int(ad_id))

            # Extract all targeting facets from adTargeting
            targeting = {}
            for t in ad.get("adTargeting", []):
                facet = t.get("facetName", "")
                segs  = t.get("includedSegments", [])
                excl  = t.get("isExcluded", False)
                if segs and not excl:
                    targeting[facet] = segs
            locations = targeting.get("Location", [])

            # Use cache if detail already fetched AND has all current fields
            if ad_id in cache and cache[ad_id].get("body") is not None and "utm_campaign" in cache[ad_id]:
                detail = cache[ad_id].copy()
                detail["age_label"] = age_lbl
                detail["age_color"] = age_col
                detail["company"]   = company
                detail["locations"] = locations
                detail["targeting"] = targeting
                detail.setdefault("url", url)
                enriched.append(detail)
                continue

            # Fetch detail page
            print(f"  [{idx+1}/{len(raw_ads)}] {ad_id}...")
            h = fetch_detail(url)
            if not h:
                # Minimal record so it still shows in gallery
                enriched.append({"url": url, "company": company, "type": ad.get("type",""),
                                  "body": "", "headline": "", "cta": "", "ad_type": ad.get("type",""),
                                  "image_url": "", "local_image": "", "is_thought_leadership": False,
                                  "poster_name": "", "age_label": age_lbl, "age_color": age_col})
                continue

            detail = parse_detail_page(h, url)
            detail["company"]   = company
            detail["type"]      = ad.get("type", "")
            detail["age_label"] = age_lbl
            detail["age_color"] = age_col
            detail["locations"] = locations
            detail["targeting"] = targeting

            # Scrape landing page for offer intelligence
            if detail.get("landing_url"):
                lp = scrape_landing_page(detail["landing_url"])
                detail.update(lp)

            # Classify CTA funnel stage from URL signals only
            url_signals = " ".join([
                detail.get("utm_campaign", ""),
                detail.get("utm_medium", ""),
                detail.get("landing_url", ""),
            ])
            detail["cta_stage"] = classify_cta("", url_signals)

            # Download image
            if detail["image_url"]:
                img_path = IMG_DIR / f"{company}_{ad_id}.jpg"
                if not img_path.exists():
                    download_image(detail["image_url"], str(img_path))
                if img_path.exists():
                    detail["local_image"] = str(img_path)

            cache[ad_id] = detail
            enriched.append(detail)
            time.sleep(args.delay)

        all_company_data[company] = enriched
        print(f"  Total enriched: {len(enriched)} ads")

    # ── Save cache ─────────────────────────────────────────────────────────────
    save_cache(cache)

    # ── Detect new ads vs previous run ────────────────────────────────────────
    new_ids = current_ids - prev_ids
    if new_ids:
        print(f"\n  NEW ads since last run: {len(new_ids)}")
    PREV_FILE.write_text(json.dumps(list(current_ids)))

    # ── Save updated research file if we fetched fresh data ───────────────────
    if not args.no_fetch:
        RESEARCH_FILE.write_text(json.dumps(research, indent=2))
        print(f"  Saved updated research file.")

    # ── Generate gallery ───────────────────────────────────────────────────────
    print(f"\n  Generating gallery...")
    gallery_html = generate_gallery(all_company_data, new_ids, today_str)
    GALLERY.write_text(gallery_html)
    size_kb = len(gallery_html) // 1024
    print(f"  Saved: {GALLERY} ({size_kb}KB)")

    import subprocess
    subprocess.Popen(["open", str(GALLERY)])
    print(f"  Gallery opened in browser.\n")

    # ── Slack notification (only when new ads found) ───────────────────────────
    if new_ids and not args.no_fetch:
        notify_slack(all_company_data, new_ids, today_str, cache)


def notify_slack(all_company_data, new_ids, today_str, cache):
    """Post new ad summary to #ads-intelligence via Slack API."""
    slack_token = os.getenv("SLACK_BOT_TOKEN")
    env_file    = BASE_DIR / ".env"
    if not slack_token and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("SLACK_BOT_TOKEN="):
                slack_token = line.split("=", 1)[1].strip()
    if not slack_token:
        print("  Slack: SLACK_BOT_TOKEN not set - skipping notification")
        return

    CHANNEL = "C0B12EWRN7M"  # #ads-intelligence

    # Build per-company breakdown of new ads
    new_by_company = {}
    for company, ads in all_company_data.items():
        for ad in ads:
            url   = ad.get("url", "")
            ad_id = url.split("/")[-1]
            if ad_id.isdigit() and int(ad_id) in new_ids:
                new_by_company.setdefault(company, []).append(ad)

    # Build message
    lines = [
        f"*New competitor ads detected - {today_str}*",
        f"{len(new_ids)} new ads found across {len(new_by_company)} competitors\n",
    ]

    for company, ads in new_by_company.items():
        color  = COMPANY_COLORS.get(company, "#555")
        lines.append(f"*{company.upper()}* - {len(ads)} new ad{'s' if len(ads)>1 else ''}")
        for ad in ads[:5]:  # show up to 5 per company
            headline = ad.get("headline", "").strip()
            ad_type  = ad.get("ad_type", ad.get("type", ""))
            tl       = " · TL" if ad.get("is_thought_leadership") else ""
            url      = ad.get("url", "")
            label    = f"_{headline}_" if headline else "_(no headline)_"
            lines.append(f"  • {label} [{ad_type}{tl}] - <{url}|view ad>")
        if len(ads) > 5:
            lines.append(f"  _...and {len(ads)-5} more_")
        lines.append("")

    lines.append(f"View full gallery: https://ads-intelligence-one.vercel.app")

    message = "\n".join(lines)

    payload = json.dumps({
        "channel": CHANNEL,
        "text":    message,
        "unfurl_links": False,
    }).encode()

    req = Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={
            "Authorization": f"Bearer {slack_token}",
            "Content-Type":  "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("ok"):
            print(f"  Slack: posted to #ads-intelligence")
        else:
            print(f"  Slack error: {result.get('error')}")
    except Exception as e:
        print(f"  Slack: failed - {e}")


if __name__ == "__main__":
    main()
