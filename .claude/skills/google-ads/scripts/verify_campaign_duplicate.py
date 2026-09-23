"""
Full-flight verification of duplicated campaigns.
Compares everything between source (account 1) and target (account 2):
  - Campaign settings: bidding strategy, tracking template
  - Geo targets (locations)
  - Audiences
  - Ad groups (ENABLED only from source)
  - Positive keywords + match types
  - Ad-group-level negative keywords
  - Campaign-level negative keywords
  - Negative keyword lists (shared sets)
  - RSA ads: headlines + pins, descriptions + pins, display paths, final URLs
  - Campaign assets: sitelinks (with final URL), callouts, structured snippets
  - Conversion goals (biddable)
"""

import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from config import get_config
from google.ads.googleads.client import GoogleAdsClient

ACCOUNT1 = "1403356646"
ACCOUNT2 = "1960894839"

CAMPAIGN_PAIRS = [
    {
        "label": "EU | Brand | BOFU",
        "src": "24096426147",
        "tgt": "24264882626",
        # RSA final URL intentionally different (US-specific LP)
        "skip_final_url": True,
    },
    {
        "label": "EU | ISO | Experiment",
        "src": "24203008781",
        "tgt": "24259535694",
        # RSA final URL intentionally different (US-specific LP)
        "skip_final_url": True,
        # Negative list names differ slightly across accounts ("SOC2" vs "SOC 2") — functionally same
        "skip_list_naming": True,
        # "Organic to paid push pages" is observation-mode only (bid_modifier=0) — skipped intentionally
        "skip_audiences": {"organic to paid push pages"},
        # "Demo form - Thank you page visitors" intentionally added to target (not in source ISO)
        "bonus_audiences": {"demo form - thank you page visitors"},
    },
]

_cfg = get_config()
_base = {
    "developer_token": _cfg["developer_token"],
    "client_id": _cfg["client_id"],
    "client_secret": _cfg["client_secret"],
    "refresh_token": _cfg["refresh_token"],
    "use_proto_plus": True,
}

MATCH = {2: "EXACT", 3: "PHRASE", 4: "BROAD"}
PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

# Normalize curly/smart quotes to straight so cross-account text comparisons don't
# fail on cosmetic encoding differences introduced by the Google Ads UI.
_QUOTE_MAP = str.maketrans("‘’“”′″", "''\"\"''")

def nq(text):
    return text.translate(_QUOTE_MAP).strip().lower()


def make_client(login_id):
    return GoogleAdsClient.load_from_dict({**_base, "login_customer_id": login_id})


def gaql(client, cid, q):
    return list(client.get_service("GoogleAdsService").search(customer_id=cid, query=q))


def result(label, ok, extras=(), missing=()):
    tag = PASS if ok else FAIL
    print(f"  [{tag}] {label}")
    for line in extras:
        print(f"         + EXTRA:   {line}")
    for line in missing:
        print(f"         - MISSING: {line}")
    return 0 if ok else 1


# ── Campaign settings ─────────────────────────────────────────────────────────

def get_campaign_settings(client, cid, campaign_id):
    rows = gaql(client, cid, f"""
        SELECT
            campaign.bidding_strategy_type,
            campaign.tracking_url_template,
            campaign.status
        FROM campaign
        WHERE campaign.id = {campaign_id}
    """)
    if not rows:
        return {}
    c = rows[0].campaign
    return {
        "bidding": c.bidding_strategy_type.name,
        "tracking": c.tracking_url_template,
        "status": c.status.name,
    }


# ── Geo targets ───────────────────────────────────────────────────────────────

def get_geo_targets(client, cid, campaign_id):
    rows = gaql(client, cid, f"""
        SELECT
            campaign_criterion.location.geo_target_constant,
            campaign_criterion.negative
        FROM campaign_criterion
        WHERE campaign.id = {campaign_id}
          AND campaign_criterion.type = LOCATION
          AND campaign_criterion.status != 'REMOVED'
    """)
    pos, neg = set(), set()
    for r in rows:
        cr = r.campaign_criterion
        geo = cr.location.geo_target_constant
        (neg if cr.negative else pos).add(geo)
    return pos, neg


# ── Audiences ─────────────────────────────────────────────────────────────────

def get_user_list_names(client, cid, ul_ids):
    """Resolve user list IDs to names for cross-account comparison."""
    if not ul_ids:
        return {}
    id_list = ",".join(ul_ids)
    rows = gaql(client, cid, f"""
        SELECT user_list.id, user_list.name
        FROM user_list
        WHERE user_list.id IN ({id_list})
    """)
    return {str(r.user_list.id): r.user_list.name for r in rows}


def get_audiences(client, cid, campaign_id):
    """Returns set of (user_list_name_lower, is_negative) — comparable cross-account."""
    rows = gaql(client, cid, f"""
        SELECT
            campaign_criterion.type,
            campaign_criterion.user_list.user_list,
            campaign_criterion.negative
        FROM campaign_criterion
        WHERE campaign.id = {campaign_id}
          AND campaign_criterion.type IN (USER_LIST, USER_INTEREST, AUDIENCE, COMBINED_AUDIENCE)
          AND campaign_criterion.status != 'REMOVED'
    """)
    ul_ids = []
    raw = []
    for r in rows:
        ul_rn = r.campaign_criterion.user_list.user_list
        ul_id = ul_rn.split("/")[-1] if ul_rn else ""
        ul_ids.append(ul_id)
        raw.append((ul_id, r.campaign_criterion.negative))

    names = get_user_list_names(client, cid, [i for i in ul_ids if i])
    return {(names.get(ul_id, ul_id).strip().lower(), is_neg) for ul_id, is_neg in raw}


# ── Ad groups ─────────────────────────────────────────────────────────────────

def get_ad_groups(client, cid, campaign_id, enabled_only=True):
    status_filter = "AND ad_group.status = 'ENABLED'" if enabled_only else ""
    rows = gaql(client, cid, f"""
        SELECT ad_group.name, ad_group.status, ad_group.cpc_bid_micros
        FROM ad_group
        WHERE campaign.id = {campaign_id}
          AND ad_group.status != 'REMOVED'
          {status_filter}
    """)
    return {r.ad_group.name.strip().lower(): r.ad_group for r in rows}


# ── Positive keywords ─────────────────────────────────────────────────────────

def get_positive_kws(client, cid, campaign_id, enabled_ag_only=True):
    ag_filter = "AND ad_group.status = 'ENABLED'" if enabled_ag_only else ""
    rows = gaql(client, cid, f"""
        SELECT
            ad_group.name,
            ad_group_criterion.keyword.text,
            ad_group_criterion.keyword.match_type
        FROM ad_group_criterion
        WHERE campaign.id = {campaign_id}
          AND ad_group_criterion.type = KEYWORD
          AND ad_group_criterion.negative = FALSE
          AND ad_group_criterion.status = 'ENABLED'
          {ag_filter}
    """)
    return {(r.ad_group_criterion.keyword.text.strip().lower(),
             MATCH.get(r.ad_group_criterion.keyword.match_type, "?"))
            for r in rows}


# ── Ad-group-level negative keywords ─────────────────────────────────────────

def get_ag_negatives(client, cid, campaign_id, enabled_ag_only=True):
    ag_filter = "AND ad_group.status = 'ENABLED'" if enabled_ag_only else ""
    rows = gaql(client, cid, f"""
        SELECT
            ad_group.name,
            ad_group_criterion.keyword.text,
            ad_group_criterion.keyword.match_type
        FROM ad_group_criterion
        WHERE campaign.id = {campaign_id}
          AND ad_group_criterion.type = KEYWORD
          AND ad_group_criterion.negative = TRUE
          AND ad_group_criterion.status != 'REMOVED'
          {ag_filter}
    """)
    # Note: negatives don't have PAUSED status — REMOVED is the only inactive state
    return {(r.ad_group.name.strip().lower(),
             r.ad_group_criterion.keyword.text.strip().lower(),
             MATCH.get(r.ad_group_criterion.keyword.match_type, "?"))
            for r in rows}


# ── Campaign-level negative keywords ─────────────────────────────────────────

def get_campaign_negatives(client, cid, campaign_id):
    rows = gaql(client, cid, f"""
        SELECT
            campaign_criterion.keyword.text,
            campaign_criterion.keyword.match_type
        FROM campaign_criterion
        WHERE campaign.id = {campaign_id}
          AND campaign_criterion.type = KEYWORD
          AND campaign_criterion.negative = TRUE
          AND campaign_criterion.status != 'REMOVED'
    """)
    return {(r.campaign_criterion.keyword.text.strip().lower(),
             MATCH.get(r.campaign_criterion.keyword.match_type, "?"))
            for r in rows}


# ── Negative keyword lists ────────────────────────────────────────────────────

def get_negative_lists(client, cid, campaign_id):
    rows = gaql(client, cid, f"""
        SELECT shared_set.name, shared_set.type
        FROM campaign_shared_set
        WHERE campaign.id = {campaign_id}
          AND shared_set.type = NEGATIVE_KEYWORDS
          AND campaign_shared_set.status != 'REMOVED'
    """)
    return {r.shared_set.name.strip().lower() for r in rows}


# ── RSA ads ───────────────────────────────────────────────────────────────────

def get_rsa_ads(client, cid, campaign_id, enabled_ag_only=True):
    ag_filter = "AND ad_group.status = 'ENABLED'" if enabled_ag_only else ""
    rows = gaql(client, cid, f"""
        SELECT
            ad_group.name,
            ad_group_ad.ad.responsive_search_ad.headlines,
            ad_group_ad.ad.responsive_search_ad.descriptions,
            ad_group_ad.ad.responsive_search_ad.path1,
            ad_group_ad.ad.responsive_search_ad.path2,
            ad_group_ad.ad.final_urls,
            ad_group_ad.status
        FROM ad_group_ad
        WHERE campaign.id = {campaign_id}
          AND ad_group_ad.ad.type = RESPONSIVE_SEARCH_AD
          AND ad_group_ad.status != 'REMOVED'
          {ag_filter}
    """)

    ads = []
    for r in rows:
        rsa = r.ad_group_ad.ad.responsive_search_ad
        headlines = frozenset(
            (nq(h.text), h.pinned_field.name)
            for h in rsa.headlines
        )
        descriptions = frozenset(
            (nq(d.text), d.pinned_field.name)
            for d in rsa.descriptions
        )
        final_urls = list(r.ad_group_ad.ad.final_urls)
        ads.append({
            "ag": r.ad_group.name.strip().lower(),
            "status": r.ad_group_ad.status.name,
            "headlines": headlines,
            "descriptions": descriptions,
            "path1": rsa.path1.strip().lower(),
            "path2": rsa.path2.strip().lower(),
            "final_url": final_urls[0].strip().lower() if final_urls else "",
        })
    return ads


# ── Campaign assets ───────────────────────────────────────────────────────────

def get_assets(client, cid, campaign_id):
    rows = gaql(client, cid, f"""
        SELECT
            campaign.id,
            campaign_asset.field_type,
            campaign_asset.status,
            asset.type,
            asset.final_urls,
            asset.sitelink_asset.link_text,
            asset.sitelink_asset.description1,
            asset.sitelink_asset.description2,
            asset.callout_asset.callout_text,
            asset.structured_snippet_asset.header,
            asset.structured_snippet_asset.values
        FROM campaign_asset
        WHERE campaign.id = {campaign_id}
          AND campaign_asset.status = 'ENABLED'
          AND campaign_asset.field_type IN ('SITELINK', 'CALLOUT', 'STRUCTURED_SNIPPET')
    """)

    sitelinks, callouts, snippets = [], [], []
    for r in rows:
        a = r.asset
        t = a.type_.name
        if t == "SITELINK":
            sl = a.sitelink_asset
            final_url = list(a.final_urls)[0].strip().lower() if a.final_urls else ""
            sitelinks.append((
                sl.link_text.strip().lower(),
                sl.description1.strip().lower(),
                sl.description2.strip().lower(),
                final_url,
            ))
        elif t == "CALLOUT":
            callouts.append(a.callout_asset.callout_text.strip().lower())
        elif t == "STRUCTURED_SNIPPET":
            sn = a.structured_snippet_asset
            snippets.append((
                sn.header.strip().lower(),
                tuple(v.strip().lower() for v in sn.values),
            ))
    return set(sitelinks), set(callouts), set(snippets)


# ── Conversion goals ──────────────────────────────────────────────────────────

def get_biddable_goals(client, cid, campaign_id):
    rows = gaql(client, cid, f"""
        SELECT
            campaign_conversion_goal.category,
            campaign_conversion_goal.biddable
        FROM campaign_conversion_goal
        WHERE campaign.id = {campaign_id}
          AND campaign_conversion_goal.biddable = TRUE
    """)
    return {r.campaign_conversion_goal.category.name for r in rows}


# ── Diff helpers ──────────────────────────────────────────────────────────────

def fmt_set(s):
    return sorted(str(x) for x in s)


def diff(label, src_set, tgt_set):
    extra = tgt_set - src_set
    missing = src_set - tgt_set
    ok = not extra and not missing
    return result(
        f"{label} — {len(src_set)} expected, {len(tgt_set)} found",
        ok,
        extras=fmt_set(extra),
        missing=fmt_set(missing),
    )


# ── Main verification ─────────────────────────────────────────────────────────

def verify_pair(c1, c2, pair):
    label = pair["label"]
    src = pair["src"]
    tgt = pair["tgt"]
    failures = 0

    print(f"\n{'='*65}")
    print(f" {label}")
    print(f" Source (acct1 {ACCOUNT1}): campaign {src}")
    print(f" Target (acct2 {ACCOUNT2}): campaign {tgt}")
    print(f"{'='*65}")

    # ── 1. Campaign settings ──
    print("\n[Campaign Settings]")
    src_s = get_campaign_settings(c1, ACCOUNT1, src)
    tgt_s = get_campaign_settings(c2, ACCOUNT2, tgt)

    failures += result("Bidding strategy",
        src_s.get("bidding") == tgt_s.get("bidding"),
        extras=[f"target={tgt_s.get('bidding')}"] if src_s.get("bidding") != tgt_s.get("bidding") else [],
        missing=[f"expected={src_s.get('bidding')}"] if src_s.get("bidding") != tgt_s.get("bidding") else [],
    )
    failures += result("Tracking template present",
        bool(tgt_s.get("tracking") and "utm_term" in tgt_s.get("tracking", "")),
        extras=[], missing=["No tracking template set"] if not tgt_s.get("tracking") else [],
    )

    # ── 2. Geo targets ──
    print("\n[Geo Targets]")
    src_geo_pos, src_geo_neg = get_geo_targets(c1, ACCOUNT1, src)
    tgt_geo_pos, tgt_geo_neg = get_geo_targets(c2, ACCOUNT2, tgt)

    def fmt_geo(s):
        return {g.split("/")[-1] for g in s}

    failures += diff("Positive locations", fmt_geo(src_geo_pos), fmt_geo(tgt_geo_pos))
    if src_geo_neg or tgt_geo_neg:
        failures += diff("Negative locations", fmt_geo(src_geo_neg), fmt_geo(tgt_geo_neg))
    else:
        result("Negative locations", True, [], [])

    # ── 3. Audiences (compared by list name, cross-account safe) ──
    print("\n[Audiences]")
    src_aud = get_audiences(c1, ACCOUNT1, src)
    tgt_aud = get_audiences(c2, ACCOUNT2, tgt)
    skip_aud = pair.get("skip_audiences", set())
    bonus_aud = pair.get("bonus_audiences", set())
    src_aud = {a for a in src_aud if a[0] not in skip_aud}
    tgt_aud_cmp = {a for a in tgt_aud if a[0] not in bonus_aud}
    if not src_aud and not tgt_aud_cmp:
        result("Audiences", True, [], [])
    else:
        extra = tgt_aud_cmp - src_aud
        missing = src_aud - tgt_aud_cmp
        ok = not extra and not missing
        failures += result(
            f"Audiences — {len(src_aud)} expected, {len(tgt_aud_cmp)} in target",
            ok,
            extras=[f"name='{n}' negative={neg}" for n, neg in sorted(extra)],
            missing=[f"name='{n}' negative={neg}" for n, neg in sorted(missing)],
        )

    # ── 4. Ad groups ──
    print("\n[Ad Groups]")
    src_ags = get_ad_groups(c1, ACCOUNT1, src, enabled_only=True)
    tgt_ags = get_ad_groups(c2, ACCOUNT2, tgt, enabled_only=False)
    src_ag_names = set(src_ags.keys())
    tgt_ag_names = set(tgt_ags.keys())
    failures += diff("Ad group names (source ENABLED vs target)", src_ag_names, tgt_ag_names)

    # ── 5. Positive keywords ──
    print("\n[Positive Keywords]")
    src_kws = get_positive_kws(c1, ACCOUNT1, src, enabled_ag_only=True)
    tgt_kws = get_positive_kws(c2, ACCOUNT2, tgt, enabled_ag_only=False)

    def fmt_kw(s):
        return {f"[{m}] {t}" for t, m in s}

    failures += diff("Positive keywords (text + match type)", fmt_kw(src_kws), fmt_kw(tgt_kws))

    # ── 6. Ad-group-level negative keywords ──
    print("\n[Ad-Group Negative Keywords]")
    src_ag_neg = get_ag_negatives(c1, ACCOUNT1, src, enabled_ag_only=True)
    tgt_ag_neg = get_ag_negatives(c2, ACCOUNT2, tgt, enabled_ag_only=False)

    def fmt_ag_neg(s):
        return {f"[{m}] {t} (ag={ag})" for ag, t, m in s}

    failures += diff("Ad-group negatives", fmt_ag_neg(src_ag_neg), fmt_ag_neg(tgt_ag_neg))

    # ── 7. Campaign-level negative keywords ──
    print("\n[Campaign-Level Negative Keywords]")
    src_neg = get_campaign_negatives(c1, ACCOUNT1, src)
    tgt_neg = get_campaign_negatives(c2, ACCOUNT2, tgt)

    def fmt_neg(s):
        return {f"[{m}] {t}" for t, m in s}

    failures += diff("Campaign negatives", fmt_neg(src_neg), fmt_neg(tgt_neg))

    # ── 8. Negative keyword lists ──
    print("\n[Negative Keyword Lists]")
    src_lists = get_negative_lists(c1, ACCOUNT1, src)
    tgt_lists = get_negative_lists(c2, ACCOUNT2, tgt)
    if pair.get("skip_list_naming"):
        # Normalize: "soc2" → "soc 2" before comparing (cross-account naming drift)
        def norm_list(s):
            return {name.replace("soc2", "soc 2") for name in s}
        failures += diff("Shared negative keyword lists", norm_list(src_lists), norm_list(tgt_lists))
    else:
        failures += diff("Shared negative keyword lists", src_lists, tgt_lists)

    # ── 9. RSA ads ──
    print("\n[RSA Ads]")
    src_ads = get_rsa_ads(c1, ACCOUNT1, src, enabled_ag_only=True)
    tgt_ads = get_rsa_ads(c2, ACCOUNT2, tgt, enabled_ag_only=False)

    src_count = len(src_ads)
    tgt_count = len(tgt_ads)
    failures += result(f"Ad count — {src_count} in source, {tgt_count} in target",
                       src_count == tgt_count)

    # Bijective RSA matching: each target ad consumed once, preventing false diffs
    ad_issues = []
    tgt_pool = list(tgt_ads)  # mutable pool — remove each target ad once matched

    for src_ad in src_ads:
        ag = src_ad["ag"]
        candidates = [a for a in tgt_pool if a["ag"] == ag]
        if not candidates:
            ad_issues.append(f"No unmatched ads in target for ad group: {ag}")
            continue
        # Pick the target ad with most headline overlap; remove it from pool
        best = max(candidates, key=lambda a: len(a["headlines"] & src_ad["headlines"]))
        tgt_pool.remove(best)

        if best["headlines"] != src_ad["headlines"]:
            hl_extra = best["headlines"] - src_ad["headlines"]
            hl_miss = src_ad["headlines"] - best["headlines"]
            if hl_extra:
                ad_issues.append(f"[{ag}] EXTRA headlines: " + "; ".join(f"{t}({p})" for t, p in hl_extra))
            if hl_miss:
                ad_issues.append(f"[{ag}] MISSING headlines: " + "; ".join(f"{t}({p})" for t, p in hl_miss))

        if best["descriptions"] != src_ad["descriptions"]:
            d_extra = best["descriptions"] - src_ad["descriptions"]
            d_miss = src_ad["descriptions"] - best["descriptions"]
            if d_extra:
                ad_issues.append(f"[{ag}] EXTRA descriptions: " + "; ".join(f"{t}({p})" for t, p in d_extra))
            if d_miss:
                ad_issues.append(f"[{ag}] MISSING descriptions: " + "; ".join(f"{t}({p})" for t, p in d_miss))

        if best["path1"] != src_ad["path1"] or best["path2"] != src_ad["path2"]:
            ad_issues.append(
                f"[{ag}] Display paths: source={src_ad['path1']}/{src_ad['path2']} "
                f"target={best['path1']}/{best['path2']}"
            )

        if not pair.get("skip_final_url"):
            src_url = src_ad["final_url"].rstrip("/")
            tgt_url = best["final_url"].rstrip("/")
            if src_url != tgt_url:
                ad_issues.append(f"[{ag}] Final URL: source={src_url} target={tgt_url}")

    url_note = " (final URL skipped — intentional)" if pair.get("skip_final_url") else ""
    failures += result(f"RSA ad content (headlines, descriptions, paths{url_note})",
                       len(ad_issues) == 0,
                       extras=ad_issues)

    # ── 10. Campaign assets ──
    print("\n[Campaign Assets]")
    src_sl, src_co, src_sn = get_assets(c1, ACCOUNT1, src)
    tgt_sl, tgt_co, tgt_sn = get_assets(c2, ACCOUNT2, tgt)

    def fmt_sl(s):
        return {f"'{lt}' | '{d1}' | '{d2}' | url={u}" for lt, d1, d2, u in s}

    failures += diff("Sitelinks (link text + descriptions + final URL)", fmt_sl(src_sl), fmt_sl(tgt_sl))
    failures += diff("Callouts", src_co, tgt_co)

    def fmt_sn(s):
        return {f"'{h}': {list(v)}" for h, v in s}

    failures += diff("Structured snippets", fmt_sn(src_sn), fmt_sn(tgt_sn))

    # ── 11. Conversion goals ──
    print("\n[Conversion Goals]")
    src_goals = get_biddable_goals(c1, ACCOUNT1, src)
    tgt_goals = get_biddable_goals(c2, ACCOUNT2, tgt)
    failures += diff("Biddable conversion goals", src_goals, tgt_goals)

    # ── Summary ──
    print(f"\n{'─'*65}")
    if failures == 0:
        print(f"  {PASS}  All checks passed for {label}")
    else:
        print(f"  {FAIL}  {failures} check(s) failed for {label} — fix before enabling")
    return failures


def main():
    print("Loading API clients...")
    c1 = make_client(ACCOUNT1)
    c2 = make_client(ACCOUNT2)

    total = 0
    for pair in CAMPAIGN_PAIRS:
        total += verify_pair(c1, c2, pair)

    print(f"\n{'='*65}")
    if total == 0:
        print(f"  OVERALL: {PASS}  Both campaigns verified — all clear")
    else:
        print(f"  OVERALL: {FAIL}  {total} total failure(s) — review above before enabling")
    print()


if __name__ == "__main__":
    main()
