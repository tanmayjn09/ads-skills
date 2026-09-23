# LinkedIn Campaign Groups

This is the single source of truth for named campaign groups on the Sprinto HQ USA LinkedIn account (Account ID: 509954586).

When the user refers to a group by name, always use the exact campaign IDs listed here — never fetch all-account data when a group name is specified.

---

## Portco Campaigns
**Aliases:** "Portco", "Portfolio campaigns", "Portco LinkedIn ads", "Portco ads"
**Audience:** Portcos
**Nature:** BAU
**Account:** Sprinto HQ USA (509954586)

| Campaign ID | Campaign Name |
|---|---|
| 757702203 | NA \| ABM \| Portco \| Carousel Ad |
| 810050083 | ABM \| Portco \| Single IMG \| MOFU |
| 811051903 | ABM \| Portco \| Doc Ads \| MOFU |
| 812056653 | ABM \| Portco \| Single IMG \| LG \| BOFU |
| 757101503 | EMEA & India \| ABM \| Portco \| Image Ad |
| 757202383 | EMEA & India \| ABM \| Portco \| Video Ad |
| 757302423 | NA \| ABM \| Portco \| Video Ad |
| 757602173 | NA \| ABM \| Portco \| Image Ad |
| 758001463 | EMEA & India \| ABM \| Portco \| Carousel Ad |
| 809904993 | NA \| ABM \| Portco \| IMG |
| 810353093 | ABM \| Portco \| Doc Ads \| Single IMG \| LG \| MOFU |
| 810735453 | ABM \| Portco \| Video Ads \| TOFU |
| 811435133 | ABM \| Portco \| Carousel \| MOFU |

---

## Reporting: Google Sheet
**Sheet:** VC Portco + Investor_Rubrik
**URL:** https://docs.google.com/spreadsheets/d/1p9xz83RtKmcGkaMWzQaqb058JZEOezV7/edit
**Tab:** Summary - BAU
**Portco row locations:**
- Spend → Row 14 (E=All time, F=Last 4 weeks, G=Last week)
- Impressions → Row 20 (E=All time, F=Last 4 weeks, G=Last week)
- Clicks → Row 26 (E=All time, F=Last 4 weeks, G=Last week)
- Column G header (G13, G19, G25) → "Week of [last Sunday date]"

**Update schedule:** Every Monday — data always ends on the previous Sunday (Mon-Sun weeks)

---

## VC Campaigns
**Aliases:** "VC campaigns", "VC brand ads", "VC ads", "Investor campaigns"
**Audience:** VCs
**Nature:** BAU
**Account:** Sprinto HQ USA (509954586)

| Campaign ID | Campaign Name |
|---|---|
| 729009523 | BA \| ABM \| Investor \| TL \| Article |
| 727609963 | BA \| ABM \| Investor \| TL \| Video |
| 769602503 | BA \| ABM \| Investor \| TL \| Image |
| 823613073 | VC \| TL \| Image Ads |
| 823813133 | VC \| TL \| Video Ads |
| 848313313 | VC \| TL \| Article Ads |
| 888510303 | VC \| TL \| Carousel Ads |

---

## ROI Ads (Creative Group)
**Aliases:** "ROI ads", "ROI compliance ads", "VC + Portco ROI", "ROI-report-derived ads"
**Account:** Sprinto HQ USA (509954586)
**Note:** These are creative/ad IDs, not campaign IDs. Use `pivot=CREATIVE` when fetching analytics.

| Creative ID | Ad Name | Source |
|---|---|---|
| 1521301163 | Ad_7_3Sep2026 — The ROI of compliance, by the numbers | VC \| TL \| Image Ads |
| 1521361633 | Ad_8_3Sep2026 — The ROI of compliance, by the numbers | VC \| TL \| Image Ads |
| 1521391413 | Ad_9_3Sep2026 — The ROI of compliance, by the numbers | VC \| TL \| Image Ads |
| 1448077033 | The Business ROI of Compliance 2026 | ABM \| Portco \| Doc Ads \| MOFU |

---

## How to Add New Groups
Add a new section following the same format above:
- Group name + aliases
- Audience and Nature labels
- Table of campaign IDs
