"""
Create 2 California-targeted SOC 2 campaigns in account 1 (INR).

Source: NA | SOC 2 | Experiment (23441974241)
  - ENABLED ad group: SOC 2 | Phrase | v2 (12 PHRASE keywords, 3 ENABLED RSA ads)

Campaign 1: NA | California | SOC 2 | Experiment
  - Final URL: https://sprinto.com/lp/soc-2/ (same as source)

Campaign 2: NA | California | SOC 2 | Experiment | V2
  - Final URL: https://sprinto.com/lp/soc-2-certification/ (from NA | SOC 2 | Experiment | V3)

Both: ₹20,000/day, California only (PRESENCE), MAXIMIZE_CONVERSIONS, PAUSED, English only
"""

import sys
import urllib.parse
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from config import get_config
from google.ads.googleads.client import GoogleAdsClient

ACCOUNT = "1403356646"
SOURCE_CAMPAIGN = "23441974241"
SOURCE_AG = "196659316992"  # SOC 2 | Phrase | v2

BUDGET_MICROS = 20_000_000_000       # ₹20,000/day
CALIFORNIA_GEO = "geoTargetConstants/21137"
ENGLISH_LANG = "languageConstants/1000"

LP_V1 = "https://sprinto.com/lp/soc-2/"
LP_V2 = "https://sprinto.com/lp/soc-2-certification/"

CAMPAIGNS = [
    {"name": "NA | California | SOC 2 | Experiment",       "lp": LP_V1},
    {"name": "NA | California | SOC 2 | Experiment | V2",  "lp": LP_V2},
]

NEGATIVE_LIST_IDS = ["10398843624", "11883551159"]  # SOC2 | ISO Overall, Framework - SOC2

SOURCE_ASSET_IDS = [
    ("50015932379",  "STRUCTURED_SNIPPET"),
    ("287135719441", "SITELINK"),
    ("334197576513", "SITELINK"),
    ("347847825006", "SITELINK"),
    ("348061218349", "SITELINK"),
    ("407436648681", "SITELINK"),
    ("411184024388", "SITELINK"),
    ("411357226686", "SITELINK"),
]

_cfg = get_config()
client = GoogleAdsClient.load_from_dict({
    "developer_token": _cfg["developer_token"],
    "client_id": _cfg["client_id"],
    "client_secret": _cfg["client_secret"],
    "refresh_token": _cfg["refresh_token"],
    "use_proto_plus": True,
    "login_customer_id": ACCOUNT,
})
ga = client.get_service("GoogleAdsService")

MATCH = {2: "EXACT", 3: "PHRASE", 4: "BROAD"}


def gaql(q):
    return list(ga.search(customer_id=ACCOUNT, query=q))


# ── Fetch source data ─────────────────────────────────────────────────────────

def fetch_source_keywords():
    rows = gaql(f"""
        SELECT ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type
        FROM ad_group_criterion
        WHERE ad_group.id = {SOURCE_AG}
          AND ad_group_criterion.type = KEYWORD
          AND ad_group_criterion.negative = FALSE
          AND ad_group_criterion.status = ENABLED
    """)
    return [(r.ad_group_criterion.keyword.text, r.ad_group_criterion.keyword.match_type)
            for r in rows]


def fetch_source_ads():
    rows = gaql(f"""
        SELECT
            ad_group_ad.ad.responsive_search_ad.headlines,
            ad_group_ad.ad.responsive_search_ad.descriptions,
            ad_group_ad.ad.responsive_search_ad.path1,
            ad_group_ad.ad.responsive_search_ad.path2
        FROM ad_group_ad
        WHERE ad_group.id = {SOURCE_AG}
          AND ad_group_ad.status = ENABLED
          AND ad_group_ad.ad.type = RESPONSIVE_SEARCH_AD
    """)
    ads = []
    for r in rows:
        rsa = r.ad_group_ad.ad.responsive_search_ad
        ads.append({
            "headlines": [(h.text, h.pinned_field) for h in rsa.headlines],
            "descriptions": [(d.text, d.pinned_field) for d in rsa.descriptions],
            "path1": rsa.path1,
            "path2": rsa.path2,
        })
    return ads


def fetch_source_negatives():
    rows = gaql(f"""
        SELECT campaign_criterion.keyword.text, campaign_criterion.keyword.match_type
        FROM campaign_criterion
        WHERE campaign.id = {SOURCE_CAMPAIGN}
          AND campaign_criterion.type = KEYWORD
          AND campaign_criterion.negative = TRUE
          AND campaign_criterion.status != REMOVED
    """)
    return [(r.campaign_criterion.keyword.text, r.campaign_criterion.keyword.match_type)
            for r in rows]


# ── Create operations ─────────────────────────────────────────────────────────

def create_budget():
    svc = client.get_service("CampaignBudgetService")
    op = client.get_type("CampaignBudgetOperation")
    b = op.create
    b.amount_micros = BUDGET_MICROS
    b.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
    b.explicitly_shared = False
    resp = svc.mutate_campaign_budgets(customer_id=ACCOUNT, operations=[op])
    return resp.results[0].resource_name


def create_campaign(name, budget_rn):
    svc = client.get_service("CampaignService")
    op = client.get_type("CampaignOperation")
    c = op.create
    c.name = name
    c.status = client.enums.CampaignStatusEnum.PAUSED
    c.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
    c.campaign_budget = budget_rn
    c.maximize_conversions.target_cpa_micros = 0
    c.network_settings.target_google_search = True
    c.network_settings.target_search_network = False
    c.network_settings.target_content_network = False
    c.geo_target_type_setting.positive_geo_target_type = (
        client.enums.PositiveGeoTargetTypeEnum.PRESENCE
    )
    c.contains_eu_political_advertising = client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    resp = svc.mutate_campaigns(customer_id=ACCOUNT, operations=[op])
    return resp.results[0].resource_name.split("/")[-1]


def set_tracking_template(campaign_id, campaign_name):
    svc = client.get_service("CampaignService")
    op = client.get_type("CampaignOperation")
    c = op.update
    c.resource_name = f"customers/{ACCOUNT}/campaigns/{campaign_id}"
    encoded_name = urllib.parse.quote(campaign_name, safe="").replace("%20", "+")
    c.tracking_url_template = (
        f"{{lpurl}}?utm_term={{keyword}}&utm_campaign={encoded_name}"
        f"&utm_source=google&utm_medium=ppc"
        f"&hsa_acc={ACCOUNT}&hsa_cam={campaign_id}"
        f"&hsa_grp={{adgroupid}}&hsa_ad={{creative}}&hsa_src={{network}}"
        f"&hsa_tgt={{targetid}}&hsa_kw={{keyword}}&hsa_mt={{matchtype}}"
        f"&hsa_net=adwords&hsa_ver=3"
    )
    from google.protobuf import field_mask_pb2
    op.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["tracking_url_template"]))
    svc.mutate_campaigns(customer_id=ACCOUNT, operations=[op])


def add_geo(campaign_id):
    svc = client.get_service("CampaignCriterionService")
    op = client.get_type("CampaignCriterionOperation")
    cc = op.create
    cc.campaign = f"customers/{ACCOUNT}/campaigns/{campaign_id}"
    cc.location.geo_target_constant = CALIFORNIA_GEO
    svc.mutate_campaign_criteria(customer_id=ACCOUNT, operations=[op])


def add_language(campaign_id):
    svc = client.get_service("CampaignCriterionService")
    op = client.get_type("CampaignCriterionOperation")
    cc = op.create
    cc.campaign = f"customers/{ACCOUNT}/campaigns/{campaign_id}"
    cc.language.language_constant = ENGLISH_LANG
    svc.mutate_campaign_criteria(customer_id=ACCOUNT, operations=[op])


def create_ad_group(campaign_id):
    svc = client.get_service("AdGroupService")
    op = client.get_type("AdGroupOperation")
    ag = op.create
    ag.name = "SOC 2 | Phrase | v2"
    ag.campaign = f"customers/{ACCOUNT}/campaigns/{campaign_id}"
    ag.status = client.enums.AdGroupStatusEnum.ENABLED
    ag.type_ = client.enums.AdGroupTypeEnum.SEARCH_STANDARD
    ag.cpc_bid_micros = 10000
    resp = svc.mutate_ad_groups(customer_id=ACCOUNT, operations=[op])
    return resp.results[0].resource_name.split("/")[-1]


def add_keywords(ag_id, keywords):
    svc = client.get_service("AdGroupCriterionService")
    ops = []
    for text, match_type in keywords:
        op = client.get_type("AdGroupCriterionOperation")
        agc = op.create
        agc.ad_group = f"customers/{ACCOUNT}/adGroups/{ag_id}"
        agc.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
        agc.keyword.text = text
        agc.keyword.match_type = match_type
        ops.append(op)
    svc.mutate_ad_group_criteria(customer_id=ACCOUNT, operations=ops)
    return len(ops)


def create_rsa(ag_id, ad_data, final_url):
    svc = client.get_service("AdGroupAdService")
    op = client.get_type("AdGroupAdOperation")
    aga = op.create
    aga.ad_group = f"customers/{ACCOUNT}/adGroups/{ag_id}"
    aga.status = client.enums.AdGroupAdStatusEnum.ENABLED
    rsa = aga.ad.responsive_search_ad
    rsa.path1 = ad_data["path1"]
    rsa.path2 = ad_data["path2"]
    aga.ad.final_urls.append(final_url)

    for text, pinned_field in ad_data["headlines"]:
        h = client.get_type("AdTextAsset")
        h.text = text
        h.pinned_field = pinned_field
        rsa.headlines.append(h)

    for text, pinned_field in ad_data["descriptions"]:
        d = client.get_type("AdTextAsset")
        d.text = text
        d.pinned_field = pinned_field
        rsa.descriptions.append(d)

    svc.mutate_ad_group_ads(customer_id=ACCOUNT, operations=[op])


def add_campaign_negatives(campaign_id, negatives):
    svc = client.get_service("CampaignCriterionService")
    ops = []
    for text, match_type in negatives:
        op = client.get_type("CampaignCriterionOperation")
        cc = op.create
        cc.campaign = f"customers/{ACCOUNT}/campaigns/{campaign_id}"
        cc.negative = True
        cc.keyword.text = text
        cc.keyword.match_type = match_type
        ops.append(op)
    # Batch in chunks of 100
    for i in range(0, len(ops), 100):
        svc.mutate_campaign_criteria(customer_id=ACCOUNT, operations=ops[i:i+100])
    return len(ops)


def link_negative_lists(campaign_id):
    svc = client.get_service("CampaignSharedSetService")
    ops = []
    for ss_id in NEGATIVE_LIST_IDS:
        op = client.get_type("CampaignSharedSetOperation")
        css = op.create
        css.campaign = f"customers/{ACCOUNT}/campaigns/{campaign_id}"
        css.shared_set = f"customers/{ACCOUNT}/sharedSets/{ss_id}"
        ops.append(op)
    svc.mutate_campaign_shared_sets(customer_id=ACCOUNT, operations=ops)
    return len(ops)


def link_assets(campaign_id):
    svc = client.get_service("CampaignAssetService")
    ops = []
    ft_enum = client.enums.AssetFieldTypeEnum
    for asset_id, field_type_str in SOURCE_ASSET_IDS:
        op = client.get_type("CampaignAssetOperation")
        ca = op.create
        ca.asset = f"customers/{ACCOUNT}/assets/{asset_id}"
        ca.campaign = f"customers/{ACCOUNT}/campaigns/{campaign_id}"
        ca.field_type = getattr(ft_enum, field_type_str)
        ops.append(op)
    try:
        svc.mutate_campaign_assets(customer_id=ACCOUNT, operations=ops)
    except Exception as e:
        if "AUTOMATICALLY_CREATED" in str(e):
            print("  WARN: some assets are auto-created, skipping those")
        else:
            raise
    return len(ops)


def set_conversion_goal(campaign_id):
    from google.protobuf import field_mask_pb2
    svc = client.get_service("CampaignConversionGoalService")
    ops = []
    # New campaigns inherit account defaults — must explicitly turn off all except BOOK_APPOINTMENT
    TURN_OFF = ["PURCHASE", "SIGNUP", "PAGE_VIEW", "REQUEST_QUOTE", "CONTACT", "QUALIFIED_LEAD"]
    for category in TURN_OFF:
        op = client.get_type("CampaignConversionGoalOperation")
        g = op.update
        g.resource_name = f"customers/{ACCOUNT}/campaignConversionGoals/{campaign_id}~{category}~WEBSITE"
        g.biddable = False
        op.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["biddable"]))
        ops.append(op)
    on_op = client.get_type("CampaignConversionGoalOperation")
    g = on_op.update
    g.resource_name = f"customers/{ACCOUNT}/campaignConversionGoals/{campaign_id}~BOOK_APPOINTMENT~WEBSITE"
    g.biddable = True
    on_op.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["biddable"]))
    ops.append(on_op)
    try:
        svc.mutate_campaign_conversion_goals(customer_id=ACCOUNT, operations=ops)
    except Exception as e:
        print(f"  WARN: conversion goal update: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def build_campaign(camp_cfg, keywords, ads, negatives):
    name = camp_cfg["name"]
    lp = camp_cfg["lp"]
    print(f"\n{'='*60}")
    print(f"Building: {name}")
    print(f"  LP: {lp}")

    print("  Creating budget (₹20,000/day)...")
    budget_rn = create_budget()

    print("  Creating campaign (PAUSED)...")
    campaign_id = create_campaign(name, budget_rn)
    print(f"  Campaign ID: {campaign_id}")

    print("  Setting tracking template...")
    set_tracking_template(campaign_id, name)

    print("  Adding California geo target...")
    add_geo(campaign_id)

    print("  Adding English language...")
    add_language(campaign_id)

    print("  Creating ad group: SOC 2 | Phrase | v2...")
    ag_id = create_ad_group(campaign_id)

    print(f"  Adding {len(keywords)} PHRASE keywords...")
    add_keywords(ag_id, keywords)

    print(f"  Creating {len(ads)} RSA ads (LP: {lp})...")
    for ad_data in ads:
        create_rsa(ag_id, ad_data, lp)

    print(f"  Adding {len(negatives)} campaign-level negatives...")
    add_campaign_negatives(campaign_id, negatives)

    print(f"  Linking {len(NEGATIVE_LIST_IDS)} negative keyword lists...")
    link_negative_lists(campaign_id)

    print(f"  Linking {len(SOURCE_ASSET_IDS)} campaign assets...")
    try:
        link_assets(campaign_id)
    except Exception as e:
        print(f"  WARN asset linking: {e}")

    print("  Setting BOOK_APPOINTMENT conversion goal...")
    set_conversion_goal(campaign_id)

    print(f"  DONE: https://ads.google.com/aw/campaigns?campaignId={campaign_id}")
    return campaign_id


def main():
    print("Fetching source data from NA | SOC 2 | Experiment...")
    keywords = fetch_source_keywords()
    ads = fetch_source_ads()
    negatives = fetch_source_negatives()
    print(f"  {len(keywords)} keywords, {len(ads)} ENABLED ads, {len(negatives)} negatives")

    created = []
    for camp_cfg in CAMPAIGNS:
        cid = build_campaign(camp_cfg, keywords, ads, negatives)
        created.append((camp_cfg["name"], cid))

    print(f"\n{'='*60}")
    print("CREATED CAMPAIGNS (both PAUSED — review before enabling):")
    for name, cid in created:
        print(f"  {cid}: {name}")


if __name__ == "__main__":
    main()
