"""
Duplicate ENABLED campaign-level assets from source campaigns in account 1
to target campaigns in account 2.
Strategy: check if matching asset exists in account 2 first, link it;
otherwise create new asset then link it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from config import get_config
from google.ads.googleads.client import GoogleAdsClient

_cfg = get_config()
DEVELOPER_TOKEN = _cfg["developer_token"]
CLIENT_ID = _cfg["client_id"]
CLIENT_SECRET = _cfg["client_secret"]
REFRESH_TOKEN = _cfg["refresh_token"]

ACCOUNT1 = "1403356646"
ACCOUNT2 = "1960894839"

# Source campaigns in account 1
SOURCE_CAMPAIGNS = {
    "EU | Brand | BOFU": "24096426147",
    "EU | ISO | Experiment": "24203008781",
}

# Target campaigns in account 2
TARGET_CAMPAIGNS = {
    "EU | Brand | BOFU": "24264882626",   # EU | Brand | BOFU | US
    "EU | ISO | Experiment": "24259535694",  # EU | ISO | Experiment | US
}

def make_client(customer_id, login_id=None):
    cfg = {
        "developer_token": DEVELOPER_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
        "use_proto_plus": True,
    }
    if login_id:
        cfg["login_customer_id"] = login_id
    return GoogleAdsClient.load_from_dict(cfg)


def gaql(client, customer_id, query):
    svc = client.get_service("GoogleAdsService")
    resp = svc.search(customer_id=customer_id, query=query)
    return list(resp)


def fetch_source_assets(client1, campaign_id):
    """Fetch all ENABLED campaign-level assets with full details."""
    rows = gaql(client1, ACCOUNT1, f"""
        SELECT
            campaign.id,
            campaign_asset.asset,
            campaign_asset.field_type,
            campaign_asset.status,
            asset.id,
            asset.type,
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

    assets = []
    for r in rows:
        a = r.asset
        t = a.type_.name if hasattr(a.type_, 'name') else str(a.type_)
        info = {"id": a.id, "type": t, "field_type": r.campaign_asset.field_type.name}

        if t == "SITELINK":
            sl = a.sitelink_asset
            info["link_text"] = sl.link_text
            info["description1"] = sl.description1
            info["description2"] = sl.description2
        elif t == "CALLOUT":
            info["callout_text"] = a.callout_asset.callout_text
        elif t == "STRUCTURED_SNIPPET":
            sn = a.structured_snippet_asset
            info["header"] = sn.header
            info["values"] = list(sn.values)

        assets.append(info)
    return assets


def fetch_account2_assets(client2):
    """Fetch all assets in account 2 with their full details."""
    rows = gaql(client2, ACCOUNT2, """
        SELECT
            asset.id,
            asset.type,
            asset.sitelink_asset.link_text,
            asset.sitelink_asset.description1,
            asset.sitelink_asset.description2,
            asset.callout_asset.callout_text,
            asset.structured_snippet_asset.header,
            asset.structured_snippet_asset.values
        FROM asset
        WHERE asset.type IN ('SITELINK', 'CALLOUT', 'STRUCTURED_SNIPPET')
    """)

    by_type = {"SITELINK": [], "CALLOUT": [], "STRUCTURED_SNIPPET": []}
    for r in rows:
        a = r.asset
        t = a.type_.name if hasattr(a.type_, 'name') else str(a.type_)
        info = {"id": a.id, "type": t}

        if t == "SITELINK":
            sl = a.sitelink_asset
            info["link_text"] = sl.link_text
            info["description1"] = sl.description1
            info["description2"] = sl.description2
        elif t == "CALLOUT":
            info["callout_text"] = a.callout_asset.callout_text
        elif t == "STRUCTURED_SNIPPET":
            sn = a.structured_snippet_asset
            info["header"] = sn.header
            info["values"] = list(sn.values)

        if t in by_type:
            by_type[t].append(info)
    return by_type


def match_sitelink(src, pool):
    """Match by link_text only (descriptions may differ)."""
    src_text = src["link_text"].strip().lower()
    for a in pool:
        if a["link_text"].strip().lower() == src_text:
            return a
    return None


def match_callout(src, pool):
    src_text = src["callout_text"].strip().lower()
    for a in pool:
        if a["callout_text"].strip().lower() == src_text:
            return a
    return None


def match_snippet(src, pool):
    src_header = src["header"].strip().lower()
    src_vals = [v.strip().lower() for v in src["values"]]
    for a in pool:
        if a["header"].strip().lower() == src_header and \
           [v.strip().lower() for v in a["values"]] == src_vals:
            return a
    return None


def create_asset(client2, src):
    svc = client2.get_service("AssetService")
    op = client2.get_type("AssetOperation")
    asset = op.create

    if src["type"] == "SITELINK":
        sl = asset.sitelink_asset
        sl.link_text = src["link_text"]
        sl.description1 = src.get("description1", "")
        sl.description2 = src.get("description2", "")
        asset.final_urls.append("https://sprinto.com/")
    elif src["type"] == "CALLOUT":
        asset.callout_asset.callout_text = src["callout_text"]
    elif src["type"] == "STRUCTURED_SNIPPET":
        sn = asset.structured_snippet_asset
        sn.header = src["header"]
        for v in src["values"]:
            sn.values.append(v)

    resp = svc.mutate_assets(customer_id=ACCOUNT2, operations=[op])
    new_id = resp.results[0].resource_name.split("/")[-1]
    return new_id


def link_asset_to_campaign(client2, asset_id, campaign_id, field_type_str):
    svc = client2.get_service("CampaignAssetService")
    op = client2.get_type("CampaignAssetOperation")
    ca = op.create
    ca.asset = f"customers/{ACCOUNT2}/assets/{asset_id}"
    ca.campaign = f"customers/{ACCOUNT2}/campaigns/{campaign_id}"
    ft_enum = client2.enums.AssetFieldTypeEnum
    ca.field_type = getattr(ft_enum, field_type_str)
    resp = svc.mutate_campaign_assets(customer_id=ACCOUNT2, operations=[op])
    return resp.results[0].resource_name


def process_campaign(client1, client2, label, source_campaign_id, target_campaign_id, acc2_assets):
    print(f"\n{'='*60}")
    print(f"Processing: {label}")
    print(f"  Source campaign (acct1): {source_campaign_id}")
    print(f"  Target campaign (acct2): {target_campaign_id}")

    src_assets = fetch_source_assets(client1, source_campaign_id)
    print(f"  Found {len(src_assets)} ENABLED source assets")

    for src in src_assets:
        t = src["type"]
        ft = src["field_type"]

        if t == "SITELINK":
            desc = f"Sitelink: '{src['link_text']}'"
            match = match_sitelink(src, acc2_assets["SITELINK"])
        elif t == "CALLOUT":
            desc = f"Callout: '{src['callout_text']}'"
            match = match_callout(src, acc2_assets["CALLOUT"])
        elif t == "STRUCTURED_SNIPPET":
            desc = f"Snippet: '{src['header']}' -> {src['values']}"
            match = match_snippet(src, acc2_assets["STRUCTURED_SNIPPET"])
        else:
            print(f"  SKIP unknown type: {t}")
            continue

        if match:
            asset_id = str(match["id"])
            print(f"  EXISTING  {desc} → asset {asset_id}")
        else:
            print(f"  CREATING  {desc}")
            asset_id = create_asset(client2, src)
            print(f"            → created asset {asset_id}")
            # Add to pool so subsequent campaigns can reuse
            new_entry = dict(src)
            new_entry["id"] = int(asset_id)
            acc2_assets[t].append(new_entry)

        # Link to target campaign
        try:
            rn = link_asset_to_campaign(client2, asset_id, target_campaign_id, ft)
            print(f"            → linked: {rn}")
        except Exception as e:
            err = str(e)
            if "ALREADY_EXISTS" in err or "already exists" in err.lower() or "RESOURCE_ALREADY_EXISTS" in err:
                print(f"            → already linked (skipped)")
            elif "AUTOMATICALLY_CREATED" in err or "automatically created" in err.lower():
                # Asset is auto-created, can't link — create a fresh copy
                print(f"            → auto-created asset, creating fresh copy...")
                asset_id = create_asset(client2, src)
                print(f"            → created asset {asset_id}")
                new_entry = dict(src)
                new_entry["id"] = int(asset_id)
                acc2_assets[t].append(new_entry)
                try:
                    rn = link_asset_to_campaign(client2, asset_id, target_campaign_id, ft)
                    print(f"            → linked: {rn}")
                except Exception as e2:
                    print(f"            → ERROR linking fresh copy: {e2}")
            else:
                print(f"            → ERROR linking: {err}")


def main():
    print("Building clients...")
    client1 = make_client(ACCOUNT1, login_id=ACCOUNT1)
    client2 = make_client(ACCOUNT2, login_id=ACCOUNT2)

    # Fetch all existing assets in account 2
    print("\nFetching existing assets in account 2...")
    acc2_assets = fetch_account2_assets(client2)
    print(f"  Sitelinks: {len(acc2_assets['SITELINK'])}")
    print(f"  Callouts: {len(acc2_assets['CALLOUT'])}")
    print(f"  Snippets: {len(acc2_assets['STRUCTURED_SNIPPET'])}")

    # Process both campaigns
    for label in ["EU | Brand | BOFU", "EU | ISO | Experiment"]:
        process_campaign(
            client1, client2,
            label,
            SOURCE_CAMPAIGNS[label],
            TARGET_CAMPAIGNS[label],
            acc2_assets,
        )

    print("\n\nDone! All assets linked.")


if __name__ == "__main__":
    main()
