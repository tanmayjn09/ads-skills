"""
Ad Creative Generator using Claude (Anthropic API).
Generates static ad images as SVG, then renders to PNG.
"""
import os
import sys
import argparse
import json
import re
from pathlib import Path
from dotenv import load_dotenv
import anthropic
import cairosvg

load_dotenv(Path(__file__).parent.parent.parent.parent.parent / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

CREATIVE_BRIEFS = {
    "speed": {
        "persona": "SMB Tech CTO",
        "platform": "Meta (Facebook/Instagram)",
        "headline": "SOC 2 in 2 weeks. Zero dev hours.",
        "body": "Automated evidence from AWS, GitHub, Terraform, and JIRA.\nZero developer hours after setup.",
        "cta": "Book a Demo",
        "visual_concept": (
            "Dark theme. Mulberry (#650A41) background dominates. "
            "Split comparison: Left side shows '6 months' in faded text with a strikethrough, "
            "right side shows '2 weeks' in bold Texas yellow-green (#DDF07E). "
            "Small integration badges (AWS, GitHub, Terraform) in off-white pills at the bottom. "
            "Clean flat geometric layout. No gradients, no shadows."
        )
    },
    "expert": {
        "persona": "SMB Business CTO",
        "platform": "Meta (Facebook/Instagram)",
        "headline": "Expert support included.\nNo consultant fees.",
        "body": "Two dedicated compliance leads at no extra cost.\nPre-vetted auditor network included.",
        "cta": "Book a Demo",
        "visual_concept": (
            "Light theme. Off-white (#F6F5F2) background. "
            "Two columns: Left column has '$300/hr Consultant' label on a card with a red X mark. "
            "Right column has 'Sprinto Expert - Included' on a Mulberry (#650A41) card with white checkmark. "
            "Bold, flat card design. No gradients. Texas yellow-green (#DDF07E) accent on CTA."
        )
    },
    "deal": {
        "persona": "SMB Business CTO",
        "platform": "Meta (Facebook/Instagram)",
        "headline": "Turn compliance into\na sales advantage.",
        "body": "Stop losing enterprise deals to security questionnaires.\nGet audit-ready in weeks, not months.",
        "cta": "Book a Demo",
        "visual_concept": (
            "Dark theme. Mulberry Wood (#1F0214) background. "
            "Two deal stage cards connected by an arrow. "
            "Left card: 'Security Review - Blocked' in muted light text with a lock icon. "
            "Right card: 'Deal Closed' on a Texas yellow-green (#DDF07E) background with dark text and checkmark. "
            "Minimal pipeline visualization. Flat geometric shapes only."
        )
    },
    "multiframework": {
        "persona": "MM Tech CTO",
        "platform": "Meta (Facebook/Instagram)",
        "headline": "4 frameworks. 1 platform.\nNo duplicate work.",
        "body": "SOC 2 + ISO 27001 + GDPR + HIPAA.\nShared controls map once, comply everywhere.",
        "cta": "Book a Demo",
        "visual_concept": (
            "Light theme. Off-white (#F6F5F2) background. "
            "2x2 grid of compliance badge cards: SOC 2, ISO 27001, GDPR, HIPAA. "
            "Each card in Mulberry (#650A41) with white text. "
            "Converging lines pointing down to a single platform bar labeled 'Sprinto' in Texas yellow-green (#DDF07E). "
            "Clean, technical, flat design. No gradients, no shadows."
        )
    }
}

SVG_SYSTEM_PROMPT = """You are an expert B2B ad designer. Generate a 1080x1080px SVG for a Meta ad.

BRAND: Sprinto (compliance automation SaaS)

COLOR PALETTE:
- Mulberry: #650A41 (primary - use for backgrounds, key elements, CTAs)
- Texas: #DDF07E (accent - yellow-green, use for highlights and key numbers on dark backgrounds)
- Mulberry Wood: #1F0214 (dark backgrounds)
- Off-white: #F6F5F2 (light backgrounds)
- White: #FFFFFF (text on dark, card fills)
- Light text on dark bg: #E8E0E6

TYPOGRAPHY (use generic system fonts that render in SVG):
- All text: font-family="Arial, sans-serif" (Instrument Sans substitute)
- Accent word in headline: font-style="italic" or font-weight="800" to differentiate

LOGO (top-left corner, always):
- Draw a rounded rectangle (rx="8") 48x48px filled with #650A41
- Inside it, white letter "S" bold centered
- Next to it: text "SPRINTO" in #650A41, font-weight="700", font-size="20"
- Logo group positioned at x="48" y="48"

CTA BUTTON (bottom center):
- Rectangle filled #650A41, rounded corners rx="8", width ~280px, height ~56px
- White text centered inside, font-weight="600", font-size="18"
- OR: Rectangle filled #DDF07E with dark text #1F0214 if on light background

DESIGN RULES (strict):
- NO gradients (no linearGradient, no radialGradient)
- NO drop shadows (no filter, no feDropShadow)
- NO strokes on logo elements
- Flat geometric shapes ONLY (rect, circle, polygon, line, path)
- Minimal elements - fewer shapes = better
- High contrast text - always legible
- Match the visual_concept theme (light or dark) specified in the brief

STRUCTURE (always in this order):
1. Background rectangle (full 1080x1080)
2. Logo group top-left
3. Main visual (cards, split layout, grid, etc.)
4. Headline text (large, bold)
5. Body text (smaller)
6. CTA button group bottom-center

Return ONLY a complete, valid, fully-closed SVG. Must end with </svg>.
No explanation, no markdown fences, no XML comments."""


def generate_svg(brief: dict) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Create a 1080x1080px SVG ad for Sprinto with these specs:

HEADLINE: {brief['headline']}
BODY TEXT: {brief['body']}
CTA: {brief['cta']}
VISUAL CONCEPT: {brief['visual_concept']}
PERSONA: {brief['persona']}

Return only the SVG code."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        messages=[
            {"role": "user", "content": prompt}
        ],
        system=SVG_SYSTEM_PROMPT
    )

    svg_text = message.content[0].text.strip()
    svg_text = re.sub(r'^```(?:svg|xml)?\n?', '', svg_text)
    svg_text = re.sub(r'\n?```$', '', svg_text)
    return svg_text.strip()


def svg_to_png(svg_content: str, output_path: Path) -> str:
    cairosvg.svg2png(
        bytestring=svg_content.encode("utf-8"),
        write_to=str(output_path),
        output_width=1080,
        output_height=1080
    )
    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description="Generate Sprinto ad creatives using Claude")
    parser.add_argument("--creative", choices=list(CREATIVE_BRIEFS.keys()) + ["all"], default="all",
                        help="Which creative to generate (default: all)")
    args = parser.parse_args()

    if not ANTHROPIC_API_KEY:
        print("Error: ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    to_generate = list(CREATIVE_BRIEFS.items()) if args.creative == "all" else [(args.creative, CREATIVE_BRIEFS[args.creative])]

    for name, brief in to_generate:
        print(f"\nGenerating: {name} ({brief['persona']})")
        print(f"Headline: {brief['headline']}")

        print("  Generating SVG with Claude...")
        svg = generate_svg(brief)

        svg_path = OUTPUT_DIR / f"creative_{name}.svg"
        with open(svg_path, "w") as f:
            f.write(svg)

        print("  Rendering to PNG...")
        png_path = OUTPUT_DIR / f"creative_{name}.png"
        svg_to_png(svg, png_path)
        print(f"  Saved: {png_path}")

        copy_path = OUTPUT_DIR / f"creative_{name}_copy.json"
        with open(copy_path, "w") as f:
            json.dump({
                "name": name,
                "persona": brief["persona"],
                "platform": brief["platform"],
                "headline": brief["headline"],
                "body": brief["body"],
                "cta": brief["cta"],
                "image_file": str(png_path)
            }, f, indent=2)

    print(f"\nDone. Files saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
