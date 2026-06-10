#!/bin/bash
set -e

cd /Users/tanmayjn/ads-skills

# Add Homebrew to PATH (cron runs with minimal environment)
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

LOG="/Users/tanmayjn/ads-skills/refresh_report.log"
echo "--- $(date) ---" >> "$LOG"

python3 generate_pmax_images.py >> "$LOG" 2>&1

cp PMax_Image_Performance.html vercel-deploy/index.html
vercel --prod --cwd vercel-deploy >> "$LOG" 2>&1

echo "Done." >> "$LOG"
