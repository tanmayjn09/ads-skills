"""
Replace sitelinks in both target campaigns with exact copies from source.
For each sitelink that differs (matched by link_text):
  1. Unlink old campaign_asset from target
  2. Create new asset with exact source content (text, descriptions, final_url)
  3. Link new asset to target campaign
"""

import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from config import get_config
from google.ads.googleads.client import GoogleAdsClient

ACCOUNT1 = "1403356646"
ACCOUNT2 = "1960894839"

CAMPAIGN_PAIRS = [
    {"label": "EU | Brand | BOFU", "src": "24096426147", "tgt": "24264882626"},
    {"label": "EU | ISO | Experiment", "src": "24203008781", "tgt": "24259535694"},
]

_cfg = get_config()
_base = {
    "developer_token": _cfg["developer_token"],
    "client_id": _cfg["client_id"],
    "client_secret": _cfg["client_secret"],
    "refresh_token": _cfg["refresh_token"],
    "use_proto_plus": True,
}


def make_client(login_id):
    return GoogleAdsClient.load_from_dict({**_base, "login_customer_id": login_id})


def gaql(client, cid, q):
    return list(client.get_service("GoogleAdsService").search(customer_id=cid, query=q))


def fetch_sitelinks(client, cid, campaign_id):
    rows = gaql(client, cid, f"""
        SELECT
            campaign.id,
            campaign_asset.resource_name,
            campaign_asset.status,
            asset.id,
            asset.final_urls,
            asset.sitelink_asset.link_text,
            asset.sitelink_asset.description1,
            asset.sitelink_asset.description2
        FROM campaign_asset
        WHERE campaign.id = {campaign_id}
          AND campaign_asset.status = 'ENABLED'
          AND campaign_asset.field_type = 'SITELINK'
    """)
    out = {}
    for r in rows:
        a = r.asset
        sl = a.sitelink_asset
        lt = sl.link_text.strip().lower()
        final_url = list(a.final_urls)[0].strip() if a.final_urls else ""
        out[lt] = {
            "link_text": sl.link_text.strip(),
            "description1": sl.description1.strip(),
            "description2": sl.description2.strip(),
            "final_url": final_url,
            "asset_id": str(a.id),
            "campaign_asset_rn": r.campaign_asset.resource_name,
        }
    return out


def sitelinks_match(src, tgt):
    return (
        src["description1"].lower() == tgt["description1"].lower()
        and src["description2"].lower() == tgt["description2"].lower()
        and src["final_url"].rstrip("/") == tgt["final_url"].rstrip("/")
    )


def unlink_sitelink(client2, campaign_asset_rn):
    svc = client2.get_service("CampaignAssetService")
    op = client2.get_type("CampaignAssetOperation")
    op.remove = campaign_asset_rn
    svc.mutate_campaign_assets(customer_id=ACCOUNT2, operations=[op])


def create_sitelink(client2, src):
    svc = client2.get_service("AssetService")
    op = client2.get_type("AssetOperation")
    asset = op.create
    sl = asset.sitelink_asset
    sl.link_text = src["link_text"]
    sl.description1 = src["description1"]
    sl.description2 = src["description2"]
    if src["final_url"]:
        asset.final_urls.append(src["final_url"])
    resp = svc.mutate_assets(customer_id=ACCOUNT2, operations=[op])
    return resp.results[0].resource_name.split("/")[-1]


def link_sitelink(client2, asset_id, campaign_id):
    svc = client2.get_service("CampaignAssetService")
    op = client2.get_type("CampaignAssetOperation")
    ca = op.create
    ca.asset = f"customers/{ACCOUNT2}/assets/{asset_id}"
    ca.campaign = f"customers/{ACCOUNT2}/campaigns/{campaign_id}"
    ca.field_type = client2.enums.AssetFieldTypeEnum.SITELINK
    resp = svc.mutate_campaign_assets(customer_id=ACCOUNT2, operations=[op])
    return resp.results[0].resource_name


def fix_campaign(c1, c2, label, src_id, tgt_id):
    print(f"\n{'='*60}")
    print(f"{label}")

    src_sitelinks = fetch_sitelinks(c1, ACCOUNT1, src_id)
    tgt_sitelinks = fetch_sitelinks(c2, ACCOUNT2, tgt_id)

    print(f"  Source: {len(src_sitelinks)} sitelinks  |  Target: {len(tgt_sitelinks)} sitelinks")

    for lt, src in src_sitelinks.items():
        tgt = tgt_sitelinks.get(lt)

        if tgt and sitelinks_match(src, tgt):
            print(f"  OK       '{src['link_text']}'")
            continue

        label_str = f"'{src['link_text']}'"

        if tgt:
            print(f"  UPDATING {label_str}")
            print(f"           old desc: '{tgt['description1']}' / '{tgt['description2']}'")
            print(f"           new desc: '{src['description1']}' / '{src['description2']}'")
            print(f"           old url:  {tgt['final_url']}")
            print(f"           new url:  {src['final_url']}")
            unlink_sitelink(c2, tgt["campaign_asset_rn"])
        else:
            print(f"  CREATING {label_str} (not in target)")

        new_id = create_sitelink(c2, src)
        rn = link_sitelink(c2, new_id, tgt_id)
        print(f"           -> linked asset {new_id}: {rn}")


def main():
    c1 = make_client(ACCOUNT1)
    c2 = make_client(ACCOUNT2)
    for pair in CAMPAIGN_PAIRS:
        fix_campaign(c1, c2, pair["label"], pair["src"], pair["tgt"])
    print("\nDone.")


if __name__ == "__main__":
    main()
