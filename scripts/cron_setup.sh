#!/usr/bin/env bash
# Server cron setup for trade.animazon.in
#
# All times UTC (IST = UTC + 5:30)
#
# Usage:
#   chmod +x scripts/cron_setup.sh
#   ./scripts/cron_setup.sh          # installs cron entries
#   ./scripts/cron_setup.sh --show   # print crontab, don't install
#
# Assumes:
#   APP_DIR = /opt/trading  (adjust APP_DIR below to your actual deploy path)
#   Python  = venv at $APP_DIR/.venv/bin/python
#   Logs    = $APP_DIR/logs/

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/trading}"
PYTHON="$APP_DIR/.venv/bin/python"
LOG="$APP_DIR/logs"

CRON_ENTRIES="
# -----------------------------------------------------------------------
# Options Backtest Platform — data collection jobs
# All times UTC.  IST = UTC+5:30.  Weekdays only (1-5).
# -----------------------------------------------------------------------

# [16:15 IST = 10:45 UTC] Angel One post-market 1-min candle collect
45 10 * * 1-5 mkdir -p $LOG && cd $APP_DIR && $PYTHON scripts/collect_angel_daily.py >> $LOG/angel_daily.log 2>&1

# [16:30 IST = 11:00 UTC] NSE Bhav EOD (free, no auth, all strikes + OI)
0 11 * * 1-5 mkdir -p $LOG && cd $APP_DIR && $PYTHON scripts/fetch_eod_bhav.py >> $LOG/bhav_eod.log 2>&1

# [09:00 IST = 03:30 UTC] Rotate logs older than 30 days
30 3 * * 1-5 find $LOG -name '*.log' -mtime +30 -delete
"

if [[ "${1:-}" == "--show" ]]; then
    echo "$CRON_ENTRIES"
    exit 0
fi

# Append to existing crontab (won't duplicate if run again because we check)
MARKER="# Options Backtest Platform"
CURRENT=$(crontab -l 2>/dev/null || true)

if echo "$CURRENT" | grep -qF "$MARKER"; then
    echo "Cron entries already installed. Run 'crontab -e' to edit manually."
    exit 0
fi

(echo "$CURRENT"; echo "$CRON_ENTRIES") | crontab -
echo "Cron entries installed. Verify with: crontab -l"

# ---- systemd live feed service ----
if command -v systemctl &>/dev/null; then
    echo ""
    echo "Installing Angel One live feed systemd service..."
    SVCDIR="/etc/systemd/system"

    # Patch APP_DIR into the service file
    sed "s|/opt/trading|$APP_DIR|g" "$APP_DIR/scripts/angelone_feed.service" \
        > "$SVCDIR/angelone_feed.service"

    # Start timer (market open 09:00 IST = 03:30 UTC)
    cat > "$SVCDIR/angelone_feed_start.timer" <<TIMER
[Unit]
Description=Start Angel One feed at market open
[Timer]
OnCalendar=Mon-Fri 03:30:00 UTC
Persistent=false
[Install]
WantedBy=timers.target
TIMER

    cat > "$SVCDIR/angelone_feed_start.service" <<SVC
[Unit]
Description=Trigger Angel One feed start
[Service]
Type=oneshot
ExecStart=/bin/systemctl start angelone_feed.service
SVC

    # Stop timer (market close 15:35 IST = 10:05 UTC)
    cat > "$SVCDIR/angelone_feed_stop.timer" <<TIMER
[Unit]
Description=Stop Angel One feed at market close
[Timer]
OnCalendar=Mon-Fri 10:05:00 UTC
Persistent=false
[Install]
WantedBy=timers.target
TIMER

    cat > "$SVCDIR/angelone_feed_stop.service" <<SVC
[Unit]
Description=Trigger Angel One feed stop
[Service]
Type=oneshot
ExecStart=/bin/systemctl stop angelone_feed.service
SVC

    systemctl daemon-reload
    systemctl enable angelone_feed_start.timer angelone_feed_stop.timer
    systemctl start  angelone_feed_start.timer angelone_feed_stop.timer
    echo "Systemd timers enabled. Check: systemctl list-timers"
else
    echo "(systemd not found — skipping live feed service install)"
fi

echo ""
echo "One-time Upstox backfill (run manually, needs valid token first):"
echo "  $PYTHON scripts/backfill_upstox.py --days 60"
echo ""
echo "Upstox token page (open once in browser to authorize backfill):"
echo "  https://trade.animazon.in/api/oauth/upstox"
