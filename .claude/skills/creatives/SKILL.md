---
name: creatives
description: |
  Ad creative generation skill. Uses Google Gemini Imagen to generate static ad images for Meta, LinkedIn, and Google Ads. Pulls persona and messaging from the Sprinto ICP knowledge base to produce on-brand, persona-specific creatives.
  MANDATORY TRIGGERS: create creative, generate creative, make ad, design ad, creative for, ad image, generate image, create image, Gemini creative
---

# Creatives Skill

Generates static ad creatives using Google Gemini Imagen based on platform, persona, and campaign brief.

## How It Works

1. User specifies platform, persona, and campaign angle (or asks for all)
2. Skill pulls the right messaging from the ICP knowledge base
3. Gemini Imagen generates the visual based on a detailed brief
4. Copy (headline, body, CTA) is written alongside the image
5. Output saved to `scripts/output/` as PNG + JSON copy brief

## Script

```bash
cd /Users/tanmayjn/ads-skills && source venv/bin/activate && pip install requests python-dotenv && python .claude/skills/creatives/scripts/generate_creative.py --creative all
```

### Options

| Flag | Values | Description |
|------|--------|-------------|
| `--creative` | `speed`, `expert`, `deal`, `multiframework`, `all` | Which creative to generate |

## Available Creatives

| Name | Persona | Angle |
|------|---------|-------|
| `speed` | SMB Tech CTO | SOC 2 in 2 weeks, zero dev hours |
| `expert` | SMB Business CTO | Expert support included, no consultant fees |
| `deal` | SMB Business CTO | Compliance as sales advantage |
| `multiframework` | MM Tech CTO | 4 frameworks, 1 platform |

## Output

Each run produces:
- `output/creative_{name}.png` - the generated image
- `output/creative_{name}_copy.json` - headline, body, CTA for the ad

## Adding New Creatives

To add a new creative brief, add an entry to `CREATIVE_BRIEFS` in `generate_creative.py`:

```python
"your_name": {
    "persona": "Who this targets",
    "platform": "Meta / LinkedIn / Google",
    "headline": "Ad headline",
    "body": "Primary text body",
    "cta": "CTA button text",
    "image_prompt": "Detailed visual description for Gemini Imagen"
}
```

## Rules

1. Always pull messaging angles from the ICP knowledge base - never invent claims
2. Never use banned messaging (see CLAUDE.md rules and ICP doc)
3. All images are 1:1 (square) for Meta feed by default
4. New concepts go into Testing Campaign first - never straight to Scaling
