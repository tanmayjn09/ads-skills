"""
LinkedIn Ad Library - Fetch Ad Copy from Detail Pages
Parses public transparency pages to extract copy, headline, CTA.

Usage:
    python fetch_competitor_copy.py                          # All competitors, top 5 ads each
    python fetch_competitor_copy.py --company vanta          # Single company
    python fetch_competitor_copy.py --top 10                 # Top 10 most recent per company
    python fetch_competitor_copy.py --company vanta drata    # Multiple companies
"""

import os
import re
import sys
import json
import time
import html
import argparse
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


INPUT_JSON = Path(__file__).parent / "output/competitor_research.json"
OUTPUT_JSON = Path(__file__).parent / "output/competitor_copy.json"
OUTPUT_TXT = Path(__file__).parent / "output/competitor_copy.txt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def unescape(text: str) -> str:
    """Strip HTML tags and decode entities."""
    text = re.sub(r"<a [^>]+>", "", text)
    text = re.sub(r"</a>", "", text)
    text = html.unescape(text)
    return text.strip()


def parse_ad_page(html_text: str) -> dict:
    """Extract copy, headline, CTA, and image URL from ad library HTML."""
    result = {"body": "", "headline": "", "cta": "", "ad_type": "", "image_url": ""}

    # Body copy - in commentary__content paragraph
    m = re.search(
        r'class="commentary__content[^"]*"[^>]*>(.*?)</p>',
        html_text, re.DOTALL
    )
    if m:
        result["body"] = unescape(m.group(1)).strip()

    # Headline - in sponsored-content-headline h2
    m = re.search(
        r'sponsored-content-headline[^>]*>.*?<h2[^>]*>(.*?)</h2>',
        html_text, re.DOTALL
    )
    if m:
        result["headline"] = unescape(m.group(1)).strip()

    # CTA button
    m = re.search(
        r'data-tracking-control-name="ad_library_ad_detail_cta"[^>]*>(.*?)</button>',
        html_text, re.DOTALL
    )
    if m:
        result["cta"] = unescape(m.group(1)).strip()

    # Ad type from "About the ad" section
    m = re.search(r'<p class="text-sm mb-1 text-color-text[^"]*">(.*?)</p>', html_text)
    if m:
        result["ad_type"] = unescape(m.group(1)).strip()

    # Image: data-delayed-url on preview image div (image ads)
    m = re.search(r'ad-preview__dynamic-dimensions-image[^>]+data-delayed-url="([^"]+)"', html_text)
    if not m:
        m = re.search(r'data-delayed-url="([^"]+)"[^>]+ad-preview__dynamic-dimensions-image', html_text)
    if m:
        result["image_url"] = html.unescape(m.group(1))
    else:
        # Video: poster thumbnail
        m = re.search(r'data-poster-url="([^"]+)"', html_text)
        if m:
            result["image_url"] = html.unescape(m.group(1))

    return result


def fetch_ad_copy(ad_url: str, retries: int = 2) -> dict | None:
    """Fetch and parse a single ad library detail page."""
    for attempt in range(retries + 1):
        try:
            req = Request(ad_url, headers=HEADERS)
            with urlopen(req, timeout=15) as resp:
                html_text = resp.read().decode("utf-8", errors="ignore")
            parsed = parse_ad_page(html_text)
            parsed["url"] = ad_url
            return parsed
        except HTTPError as e:
            if e.code == 429:
                wait = 30 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
            elif e.code in (404, 403):
                return None
            else:
                print(f"    HTTP {e.code} for {ad_url}")
                return None
        except URLError as e:
            print(f"    Network error: {e}")
            return None
    return None


def get_most_recent_ads(ads: list, n: int) -> list:
    """Return top N ads sorted by most recent (highest ID)."""
    def ad_id(ad):
        url = ad.get("adUrl", "")
        part = url.split("/")[-1]
        return int(part) if part.isdigit() else 0

    return sorted(ads, key=ad_id, reverse=True)[:n]


def format_report(results: dict) -> str:
    lines = ["=" * 70, "LINKEDIN COMPETITOR AD COPY REPORT", "=" * 70]

    for company, ads in results.items():
        lines.append(f"\n{'='*40}")
        lines.append(f"{company.upper()}")
        lines.append(f"{'='*40}")

        if not ads:
            lines.append("  No ads fetched.")
            continue

        for i, ad in enumerate(ads, 1):
            lines.append(f"\n  AD {i} - {ad.get('ad_type', 'Unknown')} | {ad['url']}")
            if ad.get("headline"):
                lines.append(f"  Headline: {ad['headline']}")
            if ad.get("cta"):
                lines.append(f"  CTA:      {ad['cta']}")
            if ad.get("body"):
                body_preview = ad["body"][:400].replace("\n", " ")
                if len(ad["body"]) > 400:
                    body_preview += "..."
                lines.append(f"  Copy:     {body_preview}")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Fetch ad copy from LinkedIn Ad Library detail pages")
    parser.add_argument("--company", nargs="+", help="Companies to fetch (default: all)")
    parser.add_argument("--top", type=int, default=5, help="Most recent N ads per company (default: 5)")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between requests (default: 2)")
    args = parser.parse_args()

    if not INPUT_JSON.exists():
        print(f"ERROR: {INPUT_JSON} not found. Run competitor_ad_research.py first.")
        sys.exit(1)

    with open(INPUT_JSON) as f:
        data = json.load(f)

    companies = args.company if args.company else list(data.keys())
    unknown = [c for c in companies if c not in data]
    if unknown:
        print(f"Unknown companies: {unknown}. Available: {list(data.keys())}")
        sys.exit(1)

    results = {}

    for company in companies:
        ads = data[company]
        if not ads:
            results[company] = []
            continue

        recent = get_most_recent_ads(ads, args.top)
        print(f"\n{company.upper()} - fetching {len(recent)} ads...")

        fetched = []
        img_dir = Path(__file__).parent / "output/ad_images"
        img_dir.mkdir(exist_ok=True)
        for ad in recent:
            url = ad.get("adUrl", "")
            if not url:
                continue
            print(f"  {url}")
            result = fetch_ad_copy(url)
            if result:
                result["format"] = ad.get("type", "")
                # Download creative image
                if result.get("image_url"):
                    ad_id = url.split("/")[-1]
                    img_path = img_dir / f"{company}_{ad_id}.jpg"
                    try:
                        req = Request(result["image_url"], headers=HEADERS)
                        with urlopen(req, timeout=15) as resp:
                            img_path.write_bytes(resp.read())
                        result["local_image"] = str(img_path)
                    except Exception:
                        pass
                fetched.append(result)
            time.sleep(args.delay)

        results[company] = fetched
        print(f"  -> {len(fetched)} ads parsed")

    # Save JSON
    with open(OUTPUT_JSON, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nRaw data saved: {OUTPUT_JSON}")

    # Save + print report
    report = format_report(results)
    with open(OUTPUT_TXT, "w") as f:
        f.write(report)
    print(f"Report saved:   {OUTPUT_TXT}\n")
    print(report)


if __name__ == "__main__":
    main()
