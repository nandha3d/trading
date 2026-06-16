# Pull-based deploy

The VPS pulls from GitHub on a timer instead of GitHub pushing over SSH. This
removes the inbound-SSH dependency that caused intermittent
`dial tcp ***:22: i/o timeout` failures in GitHub Actions (rotating runner IPs
vs. firewall / fail2ban).

## How it works

- `scripts/deploy_pull.sh` — checks if `origin/main` is ahead; if so pulls,
  conditionally reinstalls Python deps / rebuilds the frontend, then restarts
  the `trading` service.
- `deploy/trading-deploy.service` — oneshot unit that runs the script under
  `flock` (no overlapping deploys).
- `deploy/trading-deploy.timer` — fires 1 min after boot, then every 2 min.

## One-time setup on the VPS

```bash
# 1. Get these files onto the server (first time only)
cd /opt/trading && git pull --ff-only origin main

# 2. Install the unit files + make the script executable
chmod +x /opt/trading/scripts/deploy_pull.sh
sudo cp /opt/trading/deploy/trading-deploy.service /etc/systemd/system/
sudo cp /opt/trading/deploy/trading-deploy.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trading-deploy.timer

# 3. Verify
systemctl status trading-deploy.timer
sudo systemctl start trading-deploy.service   # force one run now
journalctl -u trading-deploy.service -n 50 --no-pager
```

After this, every `git push` to `main` lands on the site within ~2 minutes with
no GitHub Actions / SSH involved.

## Notes

- Runs as root (system timer) so `systemctl restart trading` and writes under
  `/opt/trading` work. If the repo is owned by another user, adjust `User=` in
  the service unit and grant that user sudo for the restart.
- To change cadence, edit `OnUnitActiveSec` in the timer, then
  `sudo systemctl daemon-reload && sudo systemctl restart trading-deploy.timer`.
- To pause auto-deploy: `sudo systemctl disable --now trading-deploy.timer`.
