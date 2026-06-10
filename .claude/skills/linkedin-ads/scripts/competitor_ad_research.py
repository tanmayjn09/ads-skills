"""
LinkedIn Ad Library - Competitor Research
Pulls active ads for competitor companies by name.
Uses /rest/adLibrary with q=criteria finder (version 202503).
"""
import os
import sys
import json
import time
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN")
API_BASE = "https://api.linkedin.com"

COMPETITORS = {
    "vanta": {"search": "Vanta", "exact": "Vanta", "payer_hint": "Vanta Inc"},
    "drata": {"search": "Drata", "exact": "Drata", "payer_hint": "Drata"},
    "secureframe": {"search": "Secureframe", "exact": "Secureframe", "payer_hint": "Secureframe"},
    "thoropass": {"search": "Thoropass", "exact": "Thoropass", "payer_hint": "Thoropass"},
    "sprinto": {"search": "Sprinto", "exact": "Sprinto", "payer_hint": "Sprinto"},
}


def get_headers():
    return {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "LinkedIn-Version": "202503",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def fetch_ads_for_advertiser(search_name, exact_name, date_range, max_pages=60, max_target_ads=50):
    """Fetch all ads matching search_name, filter for exact_name match."""
    import urllib.request
    import urllib.parse

    ads = []
    page = 0
    rate_limit_wait = 3

    while page < max_pages:
        start = page * 10
        url = (
            f"{API_BASE}/rest/adLibrary"
            f"?q=criteria"
            f"&dateRange={date_range}"
            f"&advertiser={urllib.parse.quote(search_name)}"
            f"&count=10"
            f"&start={start}"
        )

        req = urllib.request.Request(url, headers=get_headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if e.code == 429:
                print(f"    Rate limited at page {page}, waiting 65s...")
                time.sleep(65)
                continue
            print(f"    HTTP {e.code}: {body[:200]}")
            break

        elements = data.get("elements", [])
        if not elements:
            break

        for el in elements:
            adv = el.get("details", {}).get("advertiser", {})
            name = adv.get("advertiserName", "")
            if name.lower() == exact_name.lower():
                ads.append({
                    "adUrl": el.get("adUrl", ""),
                    "type": el.get("details", {}).get("type", ""),
                    "advertiserName": name,
                    "adPayer": adv.get("adPayer", ""),
                    "advertiserUrl": adv.get("advertiserUrl", ""),
                    "adTargeting": el.get("details", {}).get("adTargeting", []),
                    "isRestricted": el.get("isRestricted", False),
                })

        total = data.get("paging", {}).get("total", 0)
        if start + 10 >= total:
            break
        if len(ads) >= max_target_ads:
            print(f"    Reached {max_target_ads} target ads, stopping early")
            break

        page += 1
        time.sleep(rate_limit_wait)

    return ads


def run_competitor_research(companies, lookback_months=3):
    """Run competitor research for a list of company keys."""
    from datetime import date

    today = date.today()
    # Calculate start date (lookback_months ago)
    start_month = today.month - lookback_months
    start_year = today.year
    while start_month <= 0:
        start_month += 12
        start_year -= 1

    # LinkedIn Ad Library API requires end date to be at least 1 day in the past
    end_day = today.day - 1 if today.day > 1 else 28
    end_month = today.month if today.day > 1 else (today.month - 1 or 12)
    end_year = today.year if not (today.day == 1 and today.month == 1) else today.year - 1

    date_range = (
        f"(start:(year:{start_year},month:{start_month},day:1),"
        f"end:(year:{end_year},month:{end_month},day:{end_day}))"
    )
    print(f"Date range: {start_year}-{start_month:02d}-01 to {today}")
    print()

    results = {}
    for key in companies:
        if key not in COMPETITORS:
            print(f"Unknown company: {key}. Available: {list(COMPETITORS.keys())}")
            continue

        config = COMPETITORS[key]
        print(f"Fetching ads for: {config['exact']} (search: '{config['search']}')...")
        ads = fetch_ads_for_advertiser(
            config["search"], config["exact"], date_range
        )
        results[key] = ads
        print(f"  Found {len(ads)} ads for {config['exact']}")
        print()

    return results


def format_report(results):
    """Format results as a readable report."""
    lines = []
    lines.append("=" * 60)
    lines.append("LINKEDIN AD LIBRARY - COMPETITOR RESEARCH")
    lines.append("=" * 60)

    for company, ads in results.items():
        lines.append(f"\n{'='*40}")
        lines.append(f"{company.upper()} - {len(ads)} ads found")
        lines.append(f"{'='*40}")

        if not ads:
            lines.append("  No ads found in date range")
            continue

        # Show company URL from first ad
        lines.append(f"Company URL: {ads[0].get('advertiserUrl', 'N/A')}")
        lines.append(f"Ad Payer: {ads[0].get('adPayer', 'N/A')}")
        lines.append("")

        # Group by ad type
        by_type = {}
        for ad in ads:
            t = ad.get("type", "UNKNOWN")
            by_type.setdefault(t, []).append(ad)

        for ad_type, type_ads in by_type.items():
            lines.append(f"  [{ad_type}] - {len(type_ads)} ads")

        lines.append("")
        lines.append("Ad URLs:")
        for ad in ads:
            restricted = " [RESTRICTED]" if ad.get("isRestricted") else ""
            lines.append(f"  - {ad['adUrl']}{restricted}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="LinkedIn competitor ad research")
    parser.add_argument(
        "--companies",
        nargs="+",
        default=list(COMPETITORS.keys()),
        help=f"Companies to research (default: all). Options: {list(COMPETITORS.keys())}",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=3,
        help="Months of lookback (default: 3)",
    )
    parser.add_argument(
        "--output",
        default="output/competitor_research.json",
        help="Output JSON file",
    )
    args = parser.parse_args()

    if not ACCESS_TOKEN:
        print("Error: LINKEDIN_ACCESS_TOKEN not set in .env")
        sys.exit(1)

    results = run_competitor_research(args.companies, args.lookback)

    # Save JSON
    output_path = Path(__file__).parent / args.output
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Raw data saved to: {output_path}")

    # Print report
    report = format_report(results)
    print(report)

    # Save report
    report_path = output_path.with_suffix(".txt")
    with open(report_path, "w") as f:
        f.write(report)
    print(f"Report saved to: {report_path}")


if __name__ == "__main__":
    main()
