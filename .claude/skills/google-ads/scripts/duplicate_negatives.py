"""
Add campaign-level negative keywords and link negative keyword lists
to the duplicated campaigns in account 2.
"""

import sys
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from config import get_config
from google.ads.googleads.client import GoogleAdsClient

ACCOUNT2 = "1960894839"

c = get_config()
cfg = {
    "developer_token": c["developer_token"],
    "client_id": c["client_id"],
    "client_secret": c["client_secret"],
    "refresh_token": c["refresh_token"],
    "use_proto_plus": True,
    "login_customer_id": ACCOUNT2,
}
client = GoogleAdsClient.load_from_dict(cfg)

# ---- Campaign-level negatives to add ----

BRAND_BOFU_ID = "24264882626"
BRAND_NEGATIVES = [
    ("what is sprinto", 2),  # EXACT=2
]

ISO_EXP_ID = "24259535694"
ISO_NEGATIVES_EXACT = [
    "what is a soc report", "what is soc report", "what is a soc 2 audit",
    "what does soc 2 stand for", "what is soc compliance", "what is soc 2 audit",
    "what is soc2 audit", "what is soc 2 type 2 certification", "what is soc2 compliant",
    "what does soc 2 mean", "what is an soc 2 report", "what is a soc 2",
    "what is a soc 2 type 2 report", "what is soc 2 type 2 compliance", "what is soc type 2",
    "soc2 what is", "soc2 what is it", "what is a soc2 type 2", "what is an soc audit",
    "what is soc 2 type 1", "what is soc 2 type ii", "what's soc2",
    "soc 2 compliance what is it", "what is soc 2 attestation", "what is soc ii compliance",
    "what are soc 2 requirements", "what is a soc 2 certification", "what is an soc 2",
    "what is soc certification", "what is soc2 security", "what is soc 1 and soc 2",
    "what is soc reporting", "soc 2 que es", "what is a soc2 report", "what is soc2 report",
    "what does soc2 mean", "what is soc 2 certified", "what is soc 2 compliance mean",
    "what is required for soc 2 compliance", "what is the difference between soc 2 and iso 27001",
    "what is aicpa soc 2", "what does soc 2 compliant mean",
    "what does it mean to be soc 2 compliant", "what does soc 2 type 2 mean",
    "what is soc 2 type ii certification", "what is soc 2 in cyber security",
    "what is soc 2 type ii compliance", "whats soc2", "soc2 certification what is it",
    "soc 2 what does it stand for", "what is sco2 compliance", "what is sock 2",
    "what does soc2 compliant mean", "what's soc 2 compliance", "railway soc2",
]

# ---- Negative keyword lists to link to EU | ISO | Experiment | US ----
# Account 2 equivalents of account 1's "SOC2 | ISO Overall" and "Framework - SOC2"
LISTS_TO_LINK = [
    ("11495210135", "SOC 2 | ISO Overall"),
    ("11867884313", "Framework - SOC 2"),
]


def add_campaign_negatives(campaign_id, neg_list):
    svc = client.get_service("CampaignCriterionService")
    ops = []
    for text, match_type_val in neg_list:
        op = client.get_type("CampaignCriterionOperation")
        cc = op.create
        cc.campaign = f"customers/{ACCOUNT2}/campaigns/{campaign_id}"
        cc.negative = True
        cc.keyword.text = text
        cc.keyword.match_type = match_type_val
        ops.append(op)

    resp = svc.mutate_campaign_criteria(customer_id=ACCOUNT2, operations=ops)
    return len(resp.results)


def link_shared_set(campaign_id, shared_set_id):
    svc = client.get_service("CampaignSharedSetService")
    op = client.get_type("CampaignSharedSetOperation")
    css = op.create
    css.campaign = f"customers/{ACCOUNT2}/campaigns/{campaign_id}"
    css.shared_set = f"customers/{ACCOUNT2}/sharedSets/{shared_set_id}"
    resp = svc.mutate_campaign_shared_sets(customer_id=ACCOUNT2, operations=[op])
    return resp.results[0].resource_name


# ---- EU | Brand | BOFU | US ----
print("=== EU | Brand | BOFU | US ===")
print(f"  Adding {len(BRAND_NEGATIVES)} campaign-level negative(s)...")
n = add_campaign_negatives(BRAND_BOFU_ID, BRAND_NEGATIVES)
print(f"  → Added {n} negative keyword(s)")
print("  No negative keyword lists to link for this campaign.")

# ---- EU | ISO | Experiment | US ----
print("\n=== EU | ISO | Experiment | US ===")
iso_neg_list = [(kw, 2) for kw in ISO_NEGATIVES_EXACT]
print(f"  Adding {len(iso_neg_list)} campaign-level negative keywords...")
n = add_campaign_negatives(ISO_EXP_ID, iso_neg_list)
print(f"  → Added {n} negative keyword(s)")

print(f"  Linking {len(LISTS_TO_LINK)} negative keyword list(s)...")
for ss_id, ss_name in LISTS_TO_LINK:
    try:
        rn = link_shared_set(ISO_EXP_ID, ss_id)
        print(f"  → Linked \"{ss_name}\" ({rn})")
    except Exception as e:
        err = str(e)
        if "already exists" in err.lower() or "ALREADY_EXISTS" in err:
            print(f"  → \"{ss_name}\" already linked (skipped)")
        else:
            print(f"  → ERROR linking \"{ss_name}\": {err}")

print("\nDone.")
