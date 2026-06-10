"""
Campaign Performance Analyzer — Autonomous Mode
Run: streamlit run campaign_analyzer.py
"""

import sys
import calendar
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from collections import defaultdict

sys.path.insert(0, ".claude/skills/google-ads/scripts")
from client import get_client, get_customer_id

st.set_page_config(page_title="Campaign Analyzer", layout="wide", page_icon="📊")

# ─── API ──────────────────────────────────────────────────────────────────────

@st.cache_resource
def _init():
    c = get_client()
    cid = get_customer_id(None)
    return c, cid

def ga(version="v24"):
    c, _ = _init()
    return c.get_service("GoogleAdsService", version=version)

def cid():
    _, c = _init()
    return c

# ─── FETCH ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def fetch_campaigns():
    rows = list(ga().search(customer_id=cid(), query="""
        SELECT campaign.id, campaign.name, campaign.status,
            campaign.advertising_channel_type,
            campaign.bidding_strategy_type,
            campaign_budget.amount_micros,
            metrics.cost_micros, metrics.conversions, metrics.impressions
        FROM campaign
        WHERE campaign.status != 'REMOVED'
        AND segments.date BETWEEN '2026-05-01' AND '2026-06-08'
        ORDER BY metrics.cost_micros DESC
    """))
    data = {}
    for r in rows:
        k = r.campaign.id
        if k not in data:
            data[k] = {
                "id": k, "name": r.campaign.name,
                "status": r.campaign.status.name,
                "type": r.campaign.advertising_channel_type.name,
                "bidding": r.campaign.bidding_strategy_type.name,
                "budget": r.campaign_budget.amount_micros / 1e6,
                "cost": 0.0, "conv": 0.0, "impr": 0,
            }
        data[k]["cost"]  += r.metrics.cost_micros / 1e6
        data[k]["conv"]  += r.metrics.conversions
        data[k]["impr"]  += r.metrics.impressions
    return list(data.values())

@st.cache_data(ttl=300)
def fetch_monthly(campaign_id):
    rows = list(ga().search(customer_id=cid(), query=f"""
        SELECT segments.month,
            metrics.impressions, metrics.clicks, metrics.cost_micros,
            metrics.conversions, metrics.all_conversions,
            metrics.conversions_value, metrics.all_conversions_value,
            metrics.search_impression_share,
            metrics.search_budget_lost_impression_share,
            metrics.search_rank_lost_impression_share
        FROM campaign
        WHERE campaign.id = {campaign_id}
        AND segments.date BETWEEN '2025-01-01' AND '2026-06-30'
        ORDER BY segments.month DESC
    """))
    agg = defaultdict(lambda: {k: 0.0 for k in
        ["impr","clicks","cost","conv","all_conv","conv_val","all_conv_val","is_","budget_lost","rank_lost","n"]})
    for r in rows:
        m = r.metrics; mo = r.segments.month[:7]; d = agg[mo]
        d["impr"]       += m.impressions
        d["clicks"]     += m.clicks
        d["cost"]       += m.cost_micros / 1e6
        d["conv"]       += m.conversions
        d["all_conv"]   += m.all_conversions
        d["conv_val"]   += m.conversions_value
        d["all_conv_val"] += m.all_conversions_value
        d["is_"]        += m.search_impression_share
        d["budget_lost"] += m.search_budget_lost_impression_share
        d["rank_lost"]  += m.search_rank_lost_impression_share
        d["n"]          += 1
    records = []
    for mo, d in sorted(agg.items()):
        n = max(d["n"], 1); cost = d["cost"]; conv = d["conv"]
        records.append({
            "Month": mo, "Impr": int(d["impr"]), "Clicks": int(d["clicks"]),
            "CTR%": round(d["clicks"]/d["impr"]*100,2) if d["impr"] else 0,
            "Spend": round(cost,0), "Conv": round(conv,1),
            "All Conv": round(d["all_conv"],1),
            "CPA": round(cost/conv,0) if conv else 0,
            "ROAS": round(d["conv_val"]/cost,2) if cost else 0,
            "Conv Value": round(d["conv_val"],0),
            "Search IS%": round(d["is_"]/n*100,1),
            "Budget Lost IS%": round(d["budget_lost"]/n*100,1),
            "Rank Lost IS%": round(d["rank_lost"]/n*100,1),
        })
    return pd.DataFrame(records)

@st.cache_data(ttl=300)
def fetch_channel(campaign_id, start, end):
    rows = list(ga().search(customer_id=cid(), query=f"""
        SELECT segments.ad_network_type,
            metrics.impressions, metrics.clicks, metrics.cost_micros,
            metrics.conversions, metrics.conversions_value
        FROM campaign
        WHERE campaign.id = {campaign_id}
        AND segments.date BETWEEN '{start}' AND '{end}'
    """))
    agg = defaultdict(lambda: {"impr":0,"clicks":0,"cost":0.0,"conv":0.0,"val":0.0})
    for r in rows:
        k = r.segments.ad_network_type.name; m = r.metrics
        agg[k]["impr"]  += m.impressions;  agg[k]["clicks"] += m.clicks
        agg[k]["cost"]  += m.cost_micros/1e6; agg[k]["conv"] += m.conversions
        agg[k]["val"]   += m.conversions_value
    records = []
    for ch, d in sorted(agg.items(), key=lambda x: -x[1]["conv"]):
        cost=d["cost"]; conv=d["conv"]
        records.append({"Channel":ch,"Impr":int(d["impr"]),"Clicks":int(d["clicks"]),
            "CTR%":round(d["clicks"]/d["impr"]*100,2) if d["impr"] else 0,
            "Spend":round(cost,0),"Conv":round(conv,1),
            "CPA":round(cost/conv,0) if conv else 0,
            "ROAS":round(d["val"]/cost,2) if cost else 0})
    df = pd.DataFrame(records)
    if not df.empty:
        ts=df["Spend"].sum(); tc=df["Conv"].sum()
        df["% Spend"]=(df["Spend"]/ts*100).round(1) if ts else 0
        df["% Conv"]=(df["Conv"]/tc*100).round(1) if tc else 0
    return df

@st.cache_data(ttl=300)
def fetch_location(campaign_id, start, end):
    rows = list(ga().search(customer_id=cid(), query=f"""
        SELECT campaign.id, geographic_view.location_type,
            segments.geo_target_city, segments.geo_target_region,
            metrics.impressions, metrics.clicks,
            metrics.cost_micros, metrics.conversions
        FROM geographic_view
        WHERE campaign.id = {campaign_id}
        AND geographic_view.location_type = LOCATION_OF_PRESENCE
        AND segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY metrics.conversions DESC LIMIT 50
    """))
    agg = defaultdict(lambda: {"impr":0,"clicks":0,"cost":0.0,"conv":0.0,"region_id":""})
    for r in rows:
        city_id = r.segments.geo_target_city.split("/")[-1] if r.segments.geo_target_city else "unknown"
        m=r.metrics; agg[city_id]["impr"]+=m.impressions; agg[city_id]["clicks"]+=m.clicks
        agg[city_id]["cost"]+=m.cost_micros/1e6; agg[city_id]["conv"]+=m.conversions
        agg[city_id]["region_id"]=r.segments.geo_target_region.split("/")[-1] if r.segments.geo_target_region else ""
    all_ids=set(agg.keys())|{v["region_id"] for v in agg.values() if v["region_id"]}
    names=resolve_geo(all_ids)
    records=[]
    for city_id,d in sorted(agg.items(),key=lambda x:-x[1]["conv"]):
        if d["impr"]<10: continue
        cost=d["cost"]; conv=d["conv"]
        records.append({"City":names.get(city_id,city_id),"Region":names.get(d["region_id"],d["region_id"]),
            "Impr":int(d["impr"]),"Clicks":int(d["clicks"]),
            "CTR%":round(d["clicks"]/d["impr"]*100,2) if d["impr"] else 0,
            "Spend":round(cost,0),"Conv":round(conv,1),
            "CPA":round(cost/conv,0) if conv else 0})
    return pd.DataFrame(records)

@st.cache_data(ttl=300)
def fetch_asset_groups_monthly(campaign_id):
    rows = list(ga().search(customer_id=cid(), query=f"""
        SELECT asset_group.id, asset_group.name, asset_group.status,
            segments.month, metrics.impressions, metrics.clicks,
            metrics.cost_micros, metrics.conversions
        FROM asset_group
        WHERE campaign.id = {campaign_id}
        AND segments.date BETWEEN '2025-01-01' AND '2026-06-30'
        ORDER BY segments.month DESC
    """))
    _data = defaultdict(lambda: defaultdict(lambda: {"impr":0,"clicks":0,"cost":0.0,"conv":0.0}))
    ag_meta = {}
    for r in rows:
        ag_id=r.asset_group.id
        ag_meta[ag_id]={"name":r.asset_group.name,"status":r.asset_group.status.name}
        mo=r.segments.month[:7]; d=_data[ag_id][mo]
        d["impr"]+=r.metrics.impressions; d["clicks"]+=r.metrics.clicks
        d["cost"]+=r.metrics.cost_micros/1e6; d["conv"]+=r.metrics.conversions
    data={ag_id:{mo:dict(v) for mo,v in months.items()} for ag_id,months in _data.items()}
    return data, ag_meta

@st.cache_data(ttl=300)
def fetch_assets(campaign_id, start, end):
    rows = list(ga("v21").search(customer_id=cid(), query=f"""
        SELECT asset_group.name, asset_group.status,
            asset_group_asset.field_type, asset_group_asset.performance_label,
            asset.id, asset.text_asset.text, asset.type, asset.name,
            asset.youtube_video_asset.youtube_video_id,
            metrics.impressions, metrics.clicks, metrics.cost_micros,
            metrics.conversions, metrics.all_conversions
        FROM asset_group_asset
        WHERE campaign.id = {campaign_id}
        AND segments.date BETWEEN '{start}' AND '{end}'
    """))
    _assets = defaultdict(lambda: {"impr":0,"clicks":0,"cost":0.0,"conv":0.0,
                                    "all_conv":0.0,"perf":"","field":"",
                                    "group":"","group_status":"","asset_id":""})
    for r in rows:
        m=r.metrics; a=r.asset; aga=r.asset_group_asset; ft=aga.field_type.name
        if ft in ("HEADLINE","DESCRIPTION","LONG_HEADLINE"):
            text=a.text_asset.text or ""
        elif ft=="YOUTUBE_VIDEO":
            text=a.youtube_video_asset.youtube_video_id or a.name or f"[VIDEO:{a.id}]"
        else:
            text=a.name or f"[{ft}:{a.id}]"
        key=(r.asset_group.name,ft,text); d=_assets[key]
        d["impr"]+=m.impressions; d["clicks"]+=m.clicks
        d["cost"]+=m.cost_micros/1e6; d["conv"]+=m.conversions
        d["all_conv"]+=m.all_conversions; d["perf"]=aga.performance_label.name
        d["field"]=ft; d["group"]=r.asset_group.name
        d["group_status"]=r.asset_group.status.name; d["asset_id"]=str(a.id)
    return dict(_assets)

@st.cache_data(ttl=300)
def fetch_images(campaign_id, start, end):
    rows = list(ga("v21").search(customer_id=cid(), query=f"""
        SELECT
            asset_group.id, asset_group.name, asset_group.status,
            asset_group.final_urls, asset_group.final_mobile_urls,
            asset_group_asset.field_type, asset_group_asset.performance_label,
            asset.id, asset.name,
            asset.image_asset.full_size.url,
            asset.image_asset.full_size.width_pixels,
            asset.image_asset.full_size.height_pixels,
            metrics.impressions, metrics.clicks,
            metrics.conversions, metrics.cost_micros
        FROM asset_group_asset
        WHERE campaign.id = {campaign_id}
        AND asset_group.status = ENABLED
        AND asset_group_asset.field_type IN (
            MARKETING_IMAGE, SQUARE_MARKETING_IMAGE, PORTRAIT_MARKETING_IMAGE
        )
        AND segments.date BETWEEN '{start}' AND '{end}'
    """))
    _agg = defaultdict(lambda: {
        "impr":0,"clicks":0,"conv":0.0,"cost":0.0,
        "ag_name":"","ag_status":"","field_type":"",
        "perf":"","img_url":"","width":0,"height":0,
        "final_url":"","mobile_url":"",
    })
    for r in rows:
        m=r.metrics; ag=r.asset_group; a=r.asset; aga=r.asset_group_asset
        key=(ag.id, a.id, aga.field_type.name)
        d=_agg[key]
        d["impr"]  += m.impressions;  d["clicks"] += m.clicks
        d["conv"]  += m.conversions;  d["cost"]   += m.cost_micros/1e6
        d["ag_name"]   = ag.name;     d["ag_status"] = ag.status.name
        d["field_type"] = aga.field_type.name
        d["perf"]      = aga.performance_label.name
        d["img_url"]   = a.image_asset.full_size.url or ""
        d["width"]     = a.image_asset.full_size.width_pixels
        d["height"]    = a.image_asset.full_size.height_pixels
        final_urls     = list(ag.final_urls)
        mobile_urls    = list(ag.final_mobile_urls)
        d["final_url"]  = final_urls[0]  if final_urls  else ""
        d["mobile_url"] = mobile_urls[0] if mobile_urls else ""
    return list(_agg.values())

FIELD_LABELS = {
    "MARKETING_IMAGE":          "Landscape 1.91:1",
    "SQUARE_MARKETING_IMAGE":   "Square 1:1",
    "PORTRAIT_MARKETING_IMAGE": "Portrait 4:5",
}
LABEL_BG = {"BEST":"#4CAF50","GOOD":"#8BC34A","LOW":"#F44336",
            "LEARNING":"#9E9E9E","PENDING":"#9E9E9E","UNKNOWN":"#9E9E9E"}

@st.cache_data(ttl=300)
def fetch_combinations(campaign_id):
    rows = list(ga("v21").search(customer_id=cid(), query=f"""
        SELECT asset_group_top_combination_view.resource_name,
            asset_group_top_combination_view.asset_group_top_combinations,
            asset_group.id, asset_group.name, asset_group.status
        FROM asset_group_top_combination_view
        WHERE campaign.id = {campaign_id}
    """))
    asset_ids=set(); combos=[]
    for r in rows:
        view=r.asset_group_top_combination_view
        combo_type=view.resource_name.split("~")[-1]
        for i,combo in enumerate(view.asset_group_top_combinations):
            served=[]
            for sa in combo.asset_combination_served_assets:
                aid=sa.asset.split("/")[-1]; asset_ids.add(aid)
                served.append((aid,sa.served_asset_field_type.name))
            combos.append({"ag_name":r.asset_group.name,"ag_status":r.asset_group.status.name,
                "type":combo_type,"rank":i+1,"served":served})
    if not asset_ids:
        return combos, {}
    id_list=",".join([f"'customers/{cid()}/assets/{i}'" for i in asset_ids])
    asset_rows=list(ga("v21").search(customer_id=cid(), query=f"""
        SELECT asset.resource_name, asset.text_asset.text, asset.type,
               asset.name, asset.youtube_video_asset.youtube_video_id
        FROM asset WHERE asset.resource_name IN ({id_list})
    """))
    id_to_text={}
    for r in asset_rows:
        aid=r.asset.resource_name.split("/")[-1]
        id_to_text[aid]=(r.asset.text_asset.text
            or r.asset.youtube_video_asset.youtube_video_id
            or r.asset.name or f"[{r.asset.type_.name}]")
    return combos, id_to_text

@st.cache_data(ttl=300)
def resolve_geo(ids_set):
    if not ids_set: return {}
    ids=[i for i in ids_set if i and i!="unknown"]
    out={}
    for i in range(0,len(ids),50):
        batch=ids[i:i+50]
        names=",".join([f"'geoTargetConstants/{x}'" for x in batch])
        try:
            for r in ga().search(customer_id=cid(), query=f"""
                SELECT geo_target_constant.id, geo_target_constant.name,
                       geo_target_constant.country_code
                FROM geo_target_constant
                WHERE geo_target_constant.resource_name IN ({names})
            """):
                g=r.geo_target_constant
                out[str(g.id)]=f"{g.name} ({g.country_code})"
        except Exception:
            pass
    return out

# ─── AUTO-DETECT PERIODS ──────────────────────────────────────────────────────

def month_end(m):
    y,mo=int(m[:4]),int(m[5:7])
    return f"{m}-{calendar.monthrange(y,mo)[1]:02d}"

def auto_periods(monthly_df):
    df = monthly_df.sort_values("Month").reset_index(drop=True)
    if df.empty or len(df) < 2:
        return None

    # Find best 3-month window (peak period)
    best_start, best_avg = 0, 0
    for i in range(max(1, len(df)-2)):
        avg = df.iloc[i:i+3]["Conv"].mean()
        if avg > best_avg:
            best_avg = avg; best_start = i

    peak_rows  = df.iloc[best_start:best_start+3]
    peak_start = peak_rows.iloc[0]["Month"]
    peak_end   = peak_rows.iloc[-1]["Month"]

    # Current period = last 2 full months (skip partial current month if < 15th)
    recent = df[df["Month"] > peak_end].sort_values("Month", ascending=False)
    if recent.empty:
        # Campaign may have peaked at end of data
        recent = df.tail(2)

    current_rows  = recent.head(2).sort_values("Month")
    current_start = current_rows.iloc[0]["Month"]
    current_end   = current_rows.iloc[-1]["Month"]

    # Find inflection: first month after peak where conv < 50% of peak avg
    after_peak = df[df["Month"] > peak_end].sort_values("Month")
    inflection = None
    for _, row in after_peak.iterrows():
        if row["Conv"] < best_avg * 0.5:
            inflection = row["Month"]; break
    if inflection is None and not after_peak.empty:
        inflection = after_peak.iloc[0]["Month"]

    return {
        "peak_start":     peak_start + "-01",
        "peak_end":       month_end(peak_end),
        "current_start":  current_start + "-01",
        "current_end":    month_end(current_end),
        "peak_months":    peak_rows["Month"].tolist(),
        "current_months": current_rows["Month"].tolist(),
        "peak_conv_avg":  round(best_avg, 1),
        "current_conv_avg": round(current_rows["Conv"].mean(), 1),
        "current_conv_total": round(current_rows["Conv"].sum(), 1),
        "peak_conv_total":    round(peak_rows["Conv"].sum(), 1),
        "inflection":     inflection,
    }

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def style_df(df, conv_col="Conv", cpa_col="CPA"):
    s = df.style
    if conv_col in df.columns and df[conv_col].max() > 0:
        s = s.background_gradient(subset=[conv_col], cmap="RdYlGn")
    if cpa_col in df.columns and df[cpa_col].max() > 0:
        s = s.background_gradient(subset=[cpa_col], cmap="RdYlGn_r")
    return s

def asset_df(assets, field_type):
    rows = []
    for (grp,ft,text),d in assets.items():
        if ft!=field_type or not text: continue
        cost=d["cost"]; conv=d["conv"]
        rows.append({"Asset":text[:90],"Group":d["group"][:24],"Status":d["group_status"],
            "Label":d["perf"],"Impr":int(d["impr"]),"Clicks":int(d["clicks"]),
            "CTR%":round(d["clicks"]/d["impr"]*100,2) if d["impr"] else 0,
            "Spend":round(cost,0),"Conv":round(conv,1),"All Conv":round(d["all_conv"],1),
            "CPA":round(cost/conv,0) if conv else 0})
    if not rows: return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("Conv",ascending=False)

def delta_arrow(a, b, higher_is_better=True):
    if a == 0: return "—"
    pct = (b - a) / abs(a) * 100
    arrow = "▲" if pct > 0 else "▼"
    good  = (pct > 0) == higher_is_better
    color = "green" if good else "red"
    return f":{color}[{arrow} {abs(pct):.0f}%]"

# ─── MAIN ─────────────────────────────────────────────────────────────────────

st.title("📊 Campaign Analyzer")

with st.spinner("Loading campaigns…"):
    campaigns = fetch_campaigns()

opts = {}
for c in campaigns:
    icon = "🟢" if c["status"] == "ENABLED" else "⚪"
    opts[f"{icon}  {c['name']}  ·  ${c['cost']:,.0f} last 30d"] = c["id"]

selected   = st.selectbox("Select Campaign", list(opts.keys()))
campaign_id = opts[selected]
meta        = next(c for c in campaigns if c["id"] == campaign_id)

# Campaign header
c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("Status",  meta["status"])
c2.metric("Type",    meta["type"])
c3.metric("Bidding", meta["bidding"].replace("_"," "))
c4.metric("Daily Budget", f"${meta['budget']:,.0f}")
c5.metric("Last 30d Spend", f"${meta['cost']:,.0f}")

st.divider()

# ── LOAD & AUTO-DETECT ────────────────────────────────────────────────────────
with st.spinner("Loading performance history…"):
    monthly = fetch_monthly(campaign_id)

if monthly.empty:
    st.warning("No data found for this campaign.")
    st.stop()

periods = auto_periods(monthly)
if not periods:
    st.warning("Not enough monthly data to auto-detect periods.")
    st.stop()

# ── SECTION 1 · WHAT THE DATA SAYS ───────────────────────────────────────────
st.header("What the Data Says")

drop_pct = round((1 - periods["current_conv_avg"] / periods["peak_conv_avg"]) * 100) if periods["peak_conv_avg"] else 0
st.markdown(f"""
**Peak period:** {periods['peak_months'][0]} → {periods['peak_months'][-1]}  ·
**{periods['peak_conv_total']:.0f} total conv**  ·  avg {periods['peak_conv_avg']:.1f}/month

**Current period:** {periods['current_months'][0]} → {periods['current_months'][-1]}  ·
**{periods['current_conv_total']:.0f} total conv**  ·  avg {periods['current_conv_avg']:.1f}/month

**Performance dropped {drop_pct}% from peak.**
{"Inflection point: " + periods['inflection'] if periods['inflection'] else ""}
""")

# ── SECTION 2 · MONTHLY TREND ─────────────────────────────────────────────────
st.header("Monthly Trend")

df_asc = monthly.sort_values("Month")

fig = go.Figure()
# Shade peak period
if periods["peak_months"]:
    fig.add_vrect(x0=periods["peak_months"][0], x1=periods["peak_months"][-1],
                  fillcolor="rgba(76,175,80,0.12)", line_width=0,
                  annotation_text="Peak", annotation_position="top left")
# Shade current period
if periods["current_months"]:
    fig.add_vrect(x0=periods["current_months"][0], x1=periods["current_months"][-1],
                  fillcolor="rgba(244,67,54,0.10)", line_width=0,
                  annotation_text="Current", annotation_position="top right")

fig.add_bar(x=df_asc["Month"], y=df_asc["Conv"], name="Conv",
            marker_color=["#4CAF50" if m in periods["peak_months"]
                          else "#F44336" if m in periods["current_months"]
                          else "#90A4AE" for m in df_asc["Month"]])
fig.add_scatter(x=df_asc["Month"], y=df_asc["Spend"], name="Spend ($)",
                line=dict(color="#2196F3", width=2), yaxis="y2")
fig.add_scatter(x=df_asc["Month"], y=df_asc["Search IS%"], name="Search IS%",
                line=dict(color="#FF9800", width=1.5, dash="dot"), yaxis="y3")

fig.update_layout(
    yaxis =dict(title="Conversions", side="left"),
    yaxis2=dict(title="Spend ($)", side="right", overlaying="y"),
    yaxis3=dict(title="IS%", overlaying="y", side="right",
                anchor="free", position=1.0, showgrid=False, range=[0,100]),
    height=340, margin=dict(t=20,b=10),
    legend=dict(orientation="h", y=1.08),
)
st.plotly_chart(fig, use_container_width=True)

with st.expander("Full monthly table"):
    st.dataframe(style_df(monthly.sort_values("Month", ascending=False)),
                 use_container_width=True, hide_index=True)

st.divider()

# ── FETCH COMPARISON DATA ─────────────────────────────────────────────────────
with st.spinner("Running deep analysis…"):
    p_s, p_e = periods["peak_start"],    periods["peak_end"]
    c_s, c_e = periods["current_start"], periods["current_end"]

    ch_peak = fetch_channel(campaign_id, p_s, p_e)
    ch_curr = fetch_channel(campaign_id, c_s, c_e)
    loc_peak = fetch_location(campaign_id, p_s, p_e)
    loc_curr = fetch_location(campaign_id, c_s, c_e)
    ag_data, ag_meta = fetch_asset_groups_monthly(campaign_id)
    assets_peak = fetch_assets(campaign_id, p_s, p_e)
    assets_curr = fetch_assets(campaign_id, c_s, c_e)
    assets_all  = fetch_assets(campaign_id, "2025-01-01", "2026-06-30")
    imgs_peak = fetch_images(campaign_id, p_s, p_e)
    imgs_curr = fetch_images(campaign_id, c_s, c_e)
    combos, id_to_text = fetch_combinations(campaign_id)

# ── SECTION 3 · ROOT CAUSE: ASSET GROUPS ─────────────────────────────────────
st.header("Root Cause — What Changed")

st.subheader("Asset Groups: Peak vs Now")

ag_rows = []
for ag_id, months in ag_data.items():
    m = ag_meta[ag_id]
    peak_conv = sum(months.get(mo, {}).get("conv",0) for mo in periods["peak_months"])
    curr_conv = sum(months.get(mo, {}).get("conv",0) for mo in periods["current_months"])
    total_conv = sum(d["conv"] for d in months.values())
    active_months = sorted([mo for mo,d in months.items() if d["conv"]>0 or d["impr"]>0])
    first_seen = active_months[0] if active_months else "—"
    last_seen  = active_months[-1] if active_months else "—"
    ag_rows.append({
        "Asset Group":  m["name"],
        "Status":       m["status"],
        "First Seen":   first_seen,
        "Last Seen":    last_seen,
        "Peak Conv":    round(peak_conv,1),
        "Current Conv": round(curr_conv,1),
        "Lifetime Conv":round(total_conv,1),
    })

paused_winners = []
new_groups     = []

if ag_rows:
    ag_df = pd.DataFrame(ag_rows).sort_values("Lifetime Conv", ascending=False)
    st.dataframe(ag_df, use_container_width=True, hide_index=True)
    paused_winners = [(r["Asset Group"], r["Lifetime Conv"], r["Last Seen"])
                      for _,r in ag_df.iterrows()
                      if r["Status"]=="PAUSED" and r["Lifetime Conv"]>5]
    new_groups     = [(r["Asset Group"], r["Current Conv"], r["First Seen"])
                      for _,r in ag_df.iterrows()
                      if r["Status"]=="ENABLED" and r["Peak Conv"]==0]
else:
    st.info("No asset group data — this campaign type may not use asset groups, or data is unavailable for the selected date range.")

if paused_winners:
    for name, lc, last in paused_winners:
        st.error(f"**{name}** — {lc:.0f} lifetime conv, now PAUSED. Last active: {last}")

if new_groups:
    for name, cc, first in new_groups:
        st.warning(f"**{name}** — new group, active from {first}, only {cc:.0f} conv during current period")

st.divider()

# ── SECTION 4 · CHANNEL BREAKDOWN ────────────────────────────────────────────
st.header("Channel Breakdown: Peak vs Now")

col1, col2 = st.columns(2)
with col1:
    st.caption(f"Peak  ({p_s} → {p_e})")
    if not ch_peak.empty:
        st.dataframe(style_df(ch_peak), use_container_width=True, hide_index=True)

with col2:
    st.caption(f"Current  ({c_s} → {c_e})")
    if not ch_curr.empty:
        st.dataframe(style_df(ch_curr), use_container_width=True, hide_index=True)

# Channel shifts
if not ch_peak.empty and not ch_curr.empty:
    for ch in ch_peak["Channel"].tolist():
        rp = ch_peak[ch_peak["Channel"]==ch]
        rc = ch_curr[ch_curr["Channel"]==ch]
        if rp.empty or rc.empty: continue
        cp = rp.iloc[0]["Conv"]; cc_val = rc.iloc[0]["Conv"]
        if cp > 2 and cc_val < cp * 0.6:
            drop = round((1-cc_val/cp)*100)
            st.error(f"**{ch}**: {cp:.1f} conv (peak) → {cc_val:.1f} conv (current) — {drop}% drop")

st.divider()

# ── SECTION 5 · LOCATION BREAKDOWN ───────────────────────────────────────────
st.header("Location Breakdown: Peak vs Now")

col1, col2 = st.columns(2)
with col1:
    st.caption(f"Peak  ({p_s} → {p_e})")
    if not loc_peak.empty:
        st.dataframe(style_df(loc_peak), use_container_width=True, hide_index=True)

with col2:
    st.caption(f"Current  ({c_s} → {c_e})")
    if not loc_curr.empty:
        st.dataframe(style_df(loc_curr), use_container_width=True, hide_index=True)

if not loc_peak.empty and not loc_curr.empty:
    cities_peak = set(loc_peak[loc_peak["Conv"]>0]["City"].tolist())
    cities_curr_zero = set(loc_curr[loc_curr["Conv"]==0]["City"].tolist()) if "City" in loc_curr.columns else set()
    lost = cities_peak & cities_curr_zero
    for city in list(lost)[:5]:
        conv_p = loc_peak[loc_peak["City"]==city].iloc[0]["Conv"]
        st.warning(f"**{city}**: {conv_p:.1f} conv during peak, 0 during current")

st.divider()

# ── SECTION 6 · ASSET PERFORMANCE ────────────────────────────────────────────
st.header("Asset Performance: What Was Working vs Now")

for field_type in ["HEADLINE","DESCRIPTION","LONG_HEADLINE"]:
    df_p = asset_df(assets_peak, field_type)
    df_c = asset_df(assets_curr, field_type)
    if df_p.empty and df_c.empty: continue
    st.subheader(field_type.replace("_"," ").title())
    col1, col2 = st.columns(2)
    with col1:
        st.caption(f"Peak  ({p_s} → {p_e})")
        if not df_p.empty:
            st.dataframe(style_df(df_p), use_container_width=True, hide_index=True)
        else:
            st.caption("No data.")
    with col2:
        st.caption(f"Current  ({c_s} → {c_e})")
        if not df_c.empty:
            st.dataframe(style_df(df_c), use_container_width=True, hide_index=True)
        else:
            st.caption("No data.")

# Assets that were converting in peak but gone now
peak_top = sorted(
    [(k,v) for k,v in assets_peak.items() if k[1]=="HEADLINE" and k[2] and v["conv"]>0],
    key=lambda x: -x[1]["conv"]
)[:10]

gone = []
for (grp,ft,text),d in peak_top:
    curr_d = assets_curr.get((grp,ft,text), None)
    curr_conv = curr_d["conv"] if curr_d else 0
    if d["conv"] >= 2 and curr_conv < d["conv"] * 0.3:
        gone.append((text, d["conv"], curr_conv, d["group_status"]))

if gone:
    st.markdown("**Headlines that drove peak conversions but disappeared or collapsed:**")
    for text, peak_c, curr_c, status in gone:
        note = "GROUP PAUSED" if status == "PAUSED" else f"now {curr_c:.1f} conv"
        st.error(f"'{text[:80]}' — {peak_c:.1f} conv (peak) → {note}")

st.divider()

# ── SECTION 7 · IMAGE CREATIVES ───────────────────────────────────────────────
st.header("Image Creatives")

def render_img_gallery(imgs, period_label):
    if not imgs:
        st.caption("No image data.")
        return
    by_ag = defaultdict(list)
    for r in imgs:
        by_ag[r["ag_name"]].append(r)
    for ag_name, items in sorted(by_ag.items(), key=lambda x: -sum(i["conv"] for i in x[1])):
        ag_conv  = sum(i["conv"]  for i in items)
        final_url  = items[0]["final_url"]
        mobile_url = items[0]["mobile_url"]
        st.markdown(f"**{ag_name}** — {ag_conv:.1f} conv")
        url_line = f"Final URL: `{final_url}`"
        if mobile_url and mobile_url != final_url:
            url_line += f"  ·  Mobile URL: `{mobile_url}`"
        else:
            url_line += "  ·  Mobile: *(same)*"
        st.caption(url_line)
        sorted_imgs = sorted(items, key=lambda x: (-x["conv"], -x["impr"]))
        for chunk_start in range(0, len(sorted_imgs), 4):
            chunk = sorted_imgs[chunk_start:chunk_start+4]
            cols  = st.columns(len(chunk))
            for col, r in zip(cols, chunk):
                with col:
                    ctr = round(r["clicks"]/r["impr"]*100, 2) if r["impr"] else 0
                    cpa = f"${r['cost']/r['conv']:,.0f}" if r["conv"] else "—"
                    bg  = LABEL_BG.get(r["perf"], "#9E9E9E")
                    if r["img_url"]:
                        try:
                            st.image(r["img_url"], use_container_width=True)
                        except Exception:
                            st.markdown(f"[View]({r['img_url']})")
                    else:
                        st.markdown("*(no preview)*")
                    st.markdown(
                        f"<span style='background:{bg};color:#fff;padding:1px 5px;"
                        f"border-radius:3px;font-size:10px'>{r['perf']}</span> "
                        f"<span style='font-size:10px;color:#888'>"
                        f"{FIELD_LABELS.get(r['field_type'], r['field_type'])} · "
                        f"{r['width']}×{r['height']}</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"Conv **{r['conv']:.1f}** · CPA **{cpa}**  \n"
                        f"CTR **{ctr}%** · Impr **{int(r['impr']):,}**  \n"
                        f"Spend **${r['cost']:,.0f}**"
                    )

tab_peak, tab_curr = st.tabs([
    f"Peak  ({p_s} → {p_e})",
    f"Current  ({c_s} → {c_e})",
])
with tab_peak:
    render_img_gallery(imgs_peak, "Peak")
with tab_curr:
    render_img_gallery(imgs_curr, "Current")

st.divider()

# ── SECTION 9 · TOP COMBINATIONS ─────────────────────────────────────────────
st.header("Top Combinations Running Now")

curr_combos = [c for c in combos if c["ag_status"]=="ENABLED"]
if not curr_combos:
    curr_combos = combos  # fallback: show all

for combo_type in ["TEXT","IMAGE"]:
    items = [c for c in curr_combos if c["type"]==combo_type]
    if not items: continue
    st.subheader(combo_type)
    for c in sorted(items, key=lambda x: x["rank"])[:5]:
        slots = defaultdict(list)
        for aid, ft in c["served"]:
            slots[ft].append(id_to_text.get(aid, f"[{aid}]"))
        slot_order = ["HEADLINE_1","HEADLINE_2","HEADLINE_3","DESCRIPTION_1","DESCRIPTION_2","LONG_HEADLINE"]
        rows = []
        for ft in slot_order:
            for text in slots.get(ft,[]):
                conv,cpa,spend,label = "—","—","—","—"
                for (grp,field,t),d in assets_all.items():
                    if t==text or (text and t and text[:80]==t[:80]):
                        conv=round(d["conv"],1); label=d["perf"]
                        spend=f"${d['cost']:,.0f}"
                        cpa=f"${d['cost']/d['conv']:,.0f}" if d["conv"] else "—"
                        break
                rows.append({"Slot":ft,"Asset":text[:90],"Label":label,"Spend":spend,"Conv":conv,"CPA":cpa})
        if rows:
            with st.expander(f"Rank #{c['rank']}  ·  {c['ag_name']}", expanded=(c["rank"]<=2)):
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.divider()

# ── SECTION 10 · VERDICT ─────────────────────────────────────────────────────
st.header("Verdict: Pattern or One-Time Change?")

# Determine pattern vs trigger
inflection = periods.get("inflection","")

# Check if IS collapsed (rank issue = external pattern) vs asset swap (internal trigger)
recent_rank_loss = monthly[monthly["Month"]>=inflection]["Rank Lost IS%"].mean() if inflection else 0
recent_budget_loss = monthly[monthly["Month"]>=inflection]["Budget Lost IS%"].mean() if inflection else 0
is_quality_issue  = recent_rank_loss > 40
is_budget_issue   = recent_budget_loss > 30
is_asset_swap     = bool(paused_winners)
is_new_group_fail = bool(new_groups)

verdict_parts = []
if is_asset_swap:
    verdict_parts.append(
        f"**Primary trigger (internal change):** The high-performing asset group(s) — "
        f"{', '.join([n for n,_,_ in paused_winners])} — were paused around {inflection}. "
        f"These held {sum(lc for _,lc,_ in paused_winners):.0f} lifetime conversions. "
        f"This is a **one-time change**, not a market pattern."
    )
if is_new_group_fail:
    verdict_parts.append(
        f"**Replacement group is underperforming:** {', '.join([n for n,_,_ in new_groups])} "
        f"took over but hasn't replicated results. The machine learning period may not be complete, "
        f"or the creative quality is weaker."
    )
if is_quality_issue:
    verdict_parts.append(
        f"**Quality signal degraded:** Rank Lost IS averaged {recent_rank_loss:.0f}% after the inflection. "
        f"This means Google's auction ranking dropped — weaker assets = lower ad quality scores."
    )
if is_budget_issue:
    verdict_parts.append(
        f"**Budget is also constraining reach:** Budget Lost IS at {recent_budget_loss:.0f}%. "
        f"Even with budget, the quality drop is the main issue."
    )
if not verdict_parts:
    verdict_parts.append("No single dominant trigger identified. Review the monthly trends and asset group changes above.")

for p in verdict_parts:
    st.markdown(f"- {p}")

# Prioritized actions
st.markdown("---")
st.markdown("**What to do:**")
if is_asset_swap and paused_winners:
    st.error(f"1. Re-enable the paused asset group(s): **{', '.join([n for n,_,_ in paused_winners])}** — this is the fastest lever.")
if is_new_group_fail and new_groups:
    st.warning(f"2. Audit the replacement group assets. Add the headlines and descriptions from the old winning group back in.")
if is_quality_issue:
    st.warning(f"3. Improve asset quality in the active group — add more headline/description variants, high-quality images, and video.")
st.info("4. Do NOT change bids or budgets until the asset issue is resolved. Budget efficiency will improve automatically once quality recovers.")

st.divider()
st.caption("Not available via Google Ads API for PMax: Auction Insights · Location × Combination · Video View metrics · Absolute Top IS")
