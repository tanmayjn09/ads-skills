"""
Fetch Keyword Planner historical metrics for a list of keywords.

Input  (stdin or file): 3 columns per line, tab or comma separated
    campaign | intent | keyword

Intent prefix: Brand / Competitor / Generic (case-insensitive)

Output: 7-column TSV ready to paste into the Media Plan Generator
    campaign  intent  keyword  match  vol/mo  bid_low  bid_high

Usage:
    python keyword_metrics.py < keywords.txt
    python keyword_metrics.py keywords.txt
    python keyword_metrics.py keywords.txt --market US
    python keyword_metrics.py keywords.txt --customer-id 1234567890
"""

import sys
import argparse
import time
from pathlib import Path
from itertools import islice

# load credentials from local .env
from config import get_config, validate_config
from google.ads.googleads.client import GoogleAdsClient

# ── geo/language constants ───────────────────────────────────────────────────
GEO = {
    "IN": "2356", "India": "2356",
    "US": "2840",
    "UK": "2826", "GB": "2826",
    "SG": "2702",
    "AU": "2036",
    "CA": "2124",
}
LANG_EN = "languageConstants/1000"
BATCH = 20   # API limit per request


def get_match(kw: str) -> str:
    kw = kw.strip()
    if kw.startswith("[") and kw.endswith("]"):
        return "exact"
    if kw.startswith('"') and kw.endswith('"'):
        return "phrase"
    return "broad"


def clean_kw(kw: str) -> str:
    """Strip match-type wrappers for the API call."""
    return kw.strip().strip("[]\"")


def parse_input(lines: list[str]) -> list[dict]:
    rows = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sep = "\t" if "\t" in line else ","
        parts = [p.strip() for p in line.split(sep, 2)]
        if len(parts) < 3:
            continue
        campaign, intent_raw, kw = parts[0], parts[1], parts[2]
        rows.append({
            "campaign": campaign,
            "intent": intent_raw,
            "kw": kw,
            "match": get_match(kw),
            "kw_clean": clean_kw(kw),
        })
    return rows


def chunk(lst, n):
    it = iter(lst)
    while batch := list(islice(it, n)):
        yield batch


def fetch_metrics(client, customer_id: str, keywords: list[str], geo_constant: str) -> dict:
    """Return {keyword_text: (avg_vol, bid_low, bid_high)} for a batch."""
    svc = client.get_service("KeywordPlanIdeaService")
    req = client.get_type("GenerateKeywordHistoricalMetricsRequest")
    req.customer_id = customer_id
    req.keywords.extend(keywords)
    req.geo_target_constants.append(f"geoTargetConstants/{geo_constant}")
    req.language = LANG_EN
    req.keyword_plan_network = (
        client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    )

    resp = svc.generate_keyword_historical_metrics(req)

    out = {}
    for result in resp.results:
        m = result.keyword_metrics
        vol = m.avg_monthly_searches if m.avg_monthly_searches else 0
        low = round(m.low_top_of_page_bid_micros / 1e6, 2) if m.low_top_of_page_bid_micros else 0
        high = round(m.high_top_of_page_bid_micros / 1e6, 2) if m.high_top_of_page_bid_micros else 0
        out[result.text.lower()] = (vol, low, high)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file", nargs="?", help="Input file (default: stdin)")
    parser.add_argument("--market", default="IN", help="Market code: IN, US, UK, SG, AU, CA (default: IN)")
    parser.add_argument("--customer-id", default=None, help="Override Google Ads customer ID")
    args = parser.parse_args()

    # read input
    if args.file:
        lines = Path(args.file).read_text().splitlines()
    else:
        lines = sys.stdin.read().splitlines()

    rows = parse_input(lines)
    if not rows:
        print("No keywords parsed. Check input format.", file=sys.stderr)
        sys.exit(1)

    # resolve geo
    geo = GEO.get(args.market, args.market)

    # build client
    config = get_config()
    missing = validate_config(config)
    if missing:
        print(f"Missing credentials: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    creds = {
        "developer_token": config["developer_token"],
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "refresh_token": config["refresh_token"],
        "use_proto_plus": True,
    }
    if config["login_customer_id"]:
        creds["login_customer_id"] = config["login_customer_id"]

    client = GoogleAdsClient.load_from_dict(creds)
    customer_id = (args.customer_id or config["customer_id"]).replace("-", "")

    # batch fetch
    all_keywords = [r["kw_clean"] for r in rows]
    metrics_map = {}

    batches = list(chunk(all_keywords, BATCH))
    for i, batch in enumerate(batches, 1):
        print(f"Fetching batch {i}/{len(batches)} ({len(batch)} keywords)…", file=sys.stderr)
        try:
            m = fetch_metrics(client, customer_id, batch, geo)
            metrics_map.update(m)
        except Exception as e:
            print(f"  Warning: batch {i} failed — {e}", file=sys.stderr)
        if i < len(batches):
            time.sleep(0.5)

    # output
    print(f"# campaign\tintent\tkeyword\tmatch\tvol/mo\tbid_low\tbid_high")
    for r in rows:
        vol, low, high = metrics_map.get(r["kw_clean"].lower(), (0, 0, 0))
        print(f"{r['campaign']}\t{r['intent']}\t{r['kw']}\t{r['match']}\t{vol}\t{low}\t{high}")

    print(f"\n# {len(rows)} keywords processed.", file=sys.stderr)


if __name__ == "__main__":
    main()
