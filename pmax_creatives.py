"""
PMax Creative Performance Dashboard
All image assets from enabled asset groups — with conversions, CTR, ad URLs
Run: streamlit run pmax_creatives.py
"""

import sys
from collections import defaultdict
import streamlit as st
import pandas as pd

sys.path.insert(0, ".claude/skills/google-ads/scripts")
from client import get_client, get_customer_id

st.set_page_config(page_title="PMax Creatives", layout="wide", page_icon="🖼")

# ── Add extra account IDs here if needed ──────────────────────────────────────
# Format: ("Account Name", "customer_id")
EXTRA_ACCOUNTS = [
    # ("Second Account", "1234567890"),
]

# ─── API ──────────────────────────────────────────────────────────────────────

@st.cache_resource
def _init():
    c = get_client()
    cid = get_customer_id(None)
    return c, cid

def svc(version="v21"):
    c, _ = _init()
    return c.get_service("GoogleAdsService", version=version)

def main_cid():
    _, c = _init()
    return c

def all_accounts():
    base = [("Sprinto", main_cid())]
    return base + [(name, cid) for name, cid in EXTRA_ACCOUNTS]

# ─── FETCH ────────────────────────────────────────────────────────────────────

IMAGE_TYPES = (
    "MARKETING_IMAGE",
    "SQUARE_MARKETING_IMAGE",
    "PORTRAIT_MARKETING_IMAGE",
    "LOGO",
    "LANDSCAPE_LOGO",
)

FIELD_LABELS = {
    "MARKETING_IMAGE":          "Landscape (1.91:1)",
    "SQUARE_MARKETING_IMAGE":   "Square (1:1)",
    "PORTRAIT_MARKETING_IMAGE": "Portrait (4:5)",
    "LOGO":                     "Square Logo",
    "LANDSCAPE_LOGO":           "Landscape Logo",
}

LABEL_COLOR = {
    "BEST":    "#4CAF50",
    "GOOD":    "#8BC34A",
    "LOW":     "#F44336",
    "LEARNING":"#9E9E9E",
    "PENDING": "#9E9E9E",
    "UNKNOWN": "#9E9E9E",
}

@st.cache_data(ttl=300)
def fetch_creatives(account_id, account_name, start, end, only_enabled_campaigns):
    campaign_filter = "AND campaign.status = ENABLED" if only_enabled_campaigns else ""
    query = f"""
        SELECT
            campaign.id, campaign.name, campaign.status,
            asset_group.id, asset_group.name, asset_group.status,
            asset_group.final_urls, asset_group.final_mobile_urls,
            asset_group_asset.field_type,
            asset_group_asset.performance_label,
            asset.id, asset.name,
            asset.image_asset.full_size.url,
            asset.image_asset.full_size.width_pixels,
            asset.image_asset.full_size.height_pixels,
            metrics.impressions, metrics.clicks,
            metrics.conversions, metrics.cost_micros
        FROM asset_group_asset
        WHERE campaign.advertising_channel_type = PERFORMANCE_MAX
        AND asset_group.status = ENABLED
        {campaign_filter}
        AND asset_group_asset.field_type IN (
            MARKETING_IMAGE, SQUARE_MARKETING_IMAGE,
            PORTRAIT_MARKETING_IMAGE, LOGO, LANDSCAPE_LOGO
        )
        AND segments.date BETWEEN '{start}' AND '{end}'
    """
    try:
        rows = list(svc("v21").search(customer_id=account_id, query=query))
    except Exception as e:
        st.error(f"Account {account_name} ({account_id}): {e}")
        return []

    # Aggregate by (campaign_id, ag_id, asset_id, field_type)
    _agg = defaultdict(lambda: {
        "impr": 0, "clicks": 0, "conv": 0.0, "cost": 0.0,
        "campaign": "", "campaign_status": "", "campaign_id": 0,
        "ag_name": "", "ag_id": 0,
        "final_url": "", "mobile_url": "",
        "field_type": "", "field_label": "",
        "perf_label": "",
        "img_url": "", "width": 0, "height": 0,
        "asset_id": 0, "asset_name": "",
        "account": account_name,
    })

    for r in rows:
        m = r.metrics; ag = r.asset_group; a = r.asset; aga = r.asset_group_asset
        key = (r.campaign.id, ag.id, a.id, aga.field_type.name)
        d = _agg[key]
        d["impr"]  += m.impressions
        d["clicks"] += m.clicks
        d["conv"]  += m.conversions
        d["cost"]  += m.cost_micros / 1e6
        d["campaign"] = r.campaign.name
        d["campaign_status"] = r.campaign.status.name
        d["campaign_id"] = r.campaign.id
        d["ag_name"] = ag.name
        d["ag_id"] = ag.id
        final_urls  = list(ag.final_urls)
        mobile_urls = list(ag.final_mobile_urls)
        d["final_url"]  = final_urls[0]  if final_urls  else ""
        d["mobile_url"] = mobile_urls[0] if mobile_urls else ""
        d["field_type"]  = aga.field_type.name
        d["field_label"] = FIELD_LABELS.get(aga.field_type.name, aga.field_type.name)
        d["perf_label"]  = aga.performance_label.name
        d["img_url"]  = a.image_asset.full_size.url or ""
        d["width"]    = a.image_asset.full_size.width_pixels
        d["height"]   = a.image_asset.full_size.height_pixels
        d["asset_id"]   = a.id
        d["asset_name"] = a.name or f"Image {a.id}"
        d["account"]    = account_name

    return list(_agg.values())

# ─── UI ───────────────────────────────────────────────────────────────────────

st.title("🖼 PMax Image Creative Performance")
st.caption("Enabled asset groups only · Conversions, CTR, Spend · Final URL + Mobile URL")

# Controls
col1, col2, col3, col4 = st.columns([1.5, 1.5, 1.5, 1])
with col1:
    start = st.date_input("From", value=pd.to_datetime("2026-01-01"))
with col2:
    end   = st.date_input("To",   value=pd.to_datetime("2026-06-09"))
with col3:
    only_enabled = st.checkbox("Enabled campaigns only", value=True)
with col4:
    view_mode = st.radio("View", ["Gallery", "Table"], horizontal=True)

# Fetch all accounts
all_rows = []
for acct_name, acct_id in all_accounts():
    with st.spinner(f"Loading {acct_name}…"):
        rows = fetch_creatives(acct_id, acct_name, str(start), str(end), only_enabled)
        all_rows.extend(rows)

if not all_rows:
    st.warning("No image assets found.")
    st.stop()

# ── FILTERS ───────────────────────────────────────────────────────────────────
campaigns  = sorted({r["campaign"] for r in all_rows})
field_types = sorted({r["field_label"] for r in all_rows})
perf_labels = sorted({r["perf_label"] for r in all_rows})

f1, f2, f3 = st.columns(3)
with f1:
    sel_campaigns = st.multiselect("Campaign", campaigns,
                                   placeholder="All campaigns")
with f2:
    sel_fields = st.multiselect("Image type", field_types,
                                placeholder="All types")
with f3:
    sel_labels = st.multiselect("Performance label", perf_labels,
                                placeholder="All labels")

filtered = all_rows
if sel_campaigns: filtered = [r for r in filtered if r["campaign"] in sel_campaigns]
if sel_fields:    filtered = [r for r in filtered if r["field_label"] in sel_fields]
if sel_labels:    filtered = [r for r in filtered if r["perf_label"] in sel_labels]
filtered.sort(key=lambda x: -x["conv"])

# ── SUMMARY METRICS ───────────────────────────────────────────────────────────
total_conv  = sum(r["conv"]  for r in filtered)
total_spend = sum(r["cost"]  for r in filtered)
total_impr  = sum(r["impr"]  for r in filtered)
total_clicks = sum(r["clicks"] for r in filtered)

m1,m2,m3,m4,m5 = st.columns(5)
m1.metric("Total Images",    len(filtered))
m2.metric("Total Conv",      f"{total_conv:.1f}")
m3.metric("Total Spend",     f"${total_spend:,.0f}")
m4.metric("Blended CTR",     f"{total_clicks/total_impr*100:.2f}%" if total_impr else "—")
m5.metric("Blended CPA",     f"${total_spend/total_conv:,.0f}" if total_conv else "—")

st.divider()

# ── TABLE VIEW ────────────────────────────────────────────────────────────────
if view_mode == "Table":
    table_rows = []
    for r in filtered:
        ctr = round(r["clicks"] / r["impr"] * 100, 2) if r["impr"] else 0
        table_rows.append({
            "Account":      r["account"],
            "Campaign":     r["campaign"],
            "Asset Group":  r["ag_name"],
            "Image Type":   r["field_label"],
            "Dims":         f"{r['width']}×{r['height']}",
            "Label":        r["perf_label"],
            "Impr":         int(r["impr"]),
            "Clicks":       int(r["clicks"]),
            "CTR%":         ctr,
            "Spend":        round(r["cost"], 0),
            "Conv":         round(r["conv"], 1),
            "CPA":          round(r["cost"] / r["conv"], 0) if r["conv"] else 0,
            "Final URL":    r["final_url"],
            "Mobile URL":   r["mobile_url"] if r["mobile_url"] != r["final_url"] else "",
            "Image URL":    r["img_url"],
        })
    df = pd.DataFrame(table_rows)
    st.dataframe(df, use_container_width=True, hide_index=True,
                 column_config={
                     "Final URL":  st.column_config.LinkColumn(),
                     "Mobile URL": st.column_config.LinkColumn(),
                     "Image URL":  st.column_config.LinkColumn("Image Link"),
                 })
    st.stop()

# ── GALLERY VIEW ──────────────────────────────────────────────────────────────
# Group by campaign
by_campaign = defaultdict(list)
for r in filtered:
    by_campaign[r["campaign"]].append(r)

for campaign_name, items in sorted(by_campaign.items(),
                                    key=lambda x: -sum(r["conv"] for r in x[1])):
    camp_conv  = sum(r["conv"] for r in items)
    camp_spend = sum(r["cost"] for r in items)

    with st.expander(
        f"**{campaign_name}** — {camp_conv:.1f} conv · ${camp_spend:,.0f} spend · {len(items)} images",
        expanded=(camp_conv > 5),
    ):
        # Group by asset group within campaign
        by_ag = defaultdict(list)
        for r in items:
            by_ag[r["ag_name"]].append(r)

        for ag_name, ag_items in sorted(by_ag.items(),
                                         key=lambda x: -sum(r["conv"] for r in x[1])):
            ag_conv = sum(r["conv"] for r in ag_items)

            # Show asset group header with URLs
            ag_final_url  = ag_items[0]["final_url"]
            ag_mobile_url = ag_items[0]["mobile_url"]

            st.markdown(f"**{ag_name}** — {ag_conv:.1f} conv")

            url_parts = []
            if ag_final_url:
                url_parts.append(f"[Final URL]({ag_final_url}): `{ag_final_url}`")
            if ag_mobile_url and ag_mobile_url != ag_final_url:
                url_parts.append(f"[Mobile URL]({ag_mobile_url}): `{ag_mobile_url}`")
            else:
                url_parts.append("Mobile URL: *(same as final URL)*")
            st.caption("  ·  ".join(url_parts))

            # Render images in rows of 4
            ag_sorted = sorted(ag_items, key=lambda x: -x["conv"])
            for row_start in range(0, len(ag_sorted), 4):
                chunk = ag_sorted[row_start:row_start+4]
                cols  = st.columns(len(chunk))
                for col, r in zip(cols, chunk):
                    with col:
                        ctr = round(r["clicks"] / r["impr"] * 100, 2) if r["impr"] else 0
                        cpa = f"${r['cost']/r['conv']:,.0f}" if r["conv"] else "—"
                        label_color = LABEL_COLOR.get(r["perf_label"], "#9E9E9E")

                        # Image
                        if r["img_url"]:
                            try:
                                st.image(r["img_url"], use_container_width=True)
                            except Exception:
                                st.markdown(f"[View Image]({r['img_url']})")
                        else:
                            st.markdown("*(no preview)*")

                        # Metrics
                        st.markdown(
                            f"<span style='background:{label_color};color:white;"
                            f"padding:1px 6px;border-radius:3px;font-size:11px'>"
                            f"{r['perf_label']}</span> &nbsp;"
                            f"<span style='font-size:11px;color:#aaa'>{r['field_label']}</span>"
                            f"<br/>{r['width']}×{r['height']}",
                            unsafe_allow_html=True,
                        )
                        st.markdown(
                            f"**Conv:** {r['conv']:.1f} &nbsp; **CPA:** {cpa}  \n"
                            f"**CTR:** {ctr}% &nbsp; **Impr:** {int(r['impr']):,}  \n"
                            f"**Spend:** ${r['cost']:,.0f}"
                        )

            st.markdown("---")
