# Automated Deployment Guide (Hostinger VPS)

This guide documents the automated and manual deployment solutions configured for the Options Trading Backtest Platform on your **Hostinger VPS** (`187.127.177.121`, user `root`).

---

## 🛠️ 1. One-Time VPS Setup (Initial Server Provisioning)

We have created an automated server provisioning script, `deploy/setup_vps.sh`. This script handles package installation (Git, Python 3, Node.js v20, Nginx), setup of `.env`, python virtual environments, building the React UI, Nginx reverse proxy routing (port 80 to FastAPI port 8000), systemd service management, and data collection crons.

### How to Run:
1. **Ensure the repository folder is created on the VPS:**
   The application must live under `/opt/trading` on the server. If this is a fresh VPS, clone the repo or copy the files there first:
   ```bash
   git clone <your-repo-url> /opt/trading
   ```
2. **Copy and run the setup script on the VPS:**
   You can copy the setup script from your local machine to the server and run it:
   ```bash
   # From your local machine:
   scp deploy/setup_vps.sh root@187.127.177.121:/tmp/
   
   # SSH into the VPS and execute:
   ssh root@187.127.177.121
   sudo bash /tmp/setup_vps.sh
   ```

After running the script, your API service will be running, Nginx will reverse proxy port 80 to port 8000, and auto-deploy and market data feeds will be set up!

---

## 🚀 2. Local Manual Deployment (Instant Push-button)

If you have just made changes locally and want to push them to the server and rebuild the app **immediately** (without waiting for the 2-minute pull timer), use the local deployment scripts. 

The scripts verify local Git status, push commits to GitHub, connect to the VPS via SSH, pull the latest code, selectively rebuild/install dependencies only if changed (`requirements.txt` or `frontend/` folder), and restart the backend.

### On Windows PowerShell:
Run from the project root directory:
```powershell
.\deploy\deploy_ssh.ps1
```
*To force a rebuild and service restart regardless of code change detection, use:*
```powershell
.\deploy\deploy_ssh.ps1 --force
```

### On macOS, Linux, or Git Bash (Windows):
Run from the project root directory:
```bash
bash deploy/deploy_ssh.sh
```
*To force a rebuild and service restart:*
```bash
bash deploy/deploy_ssh.sh --force
```

---

## 🕒 3. Pull-Based Automated Deployment (Timer-based)

If you push to your GitHub repository and don't want to run the local manual deploy scripts, the Hostinger VPS runs a pull-based timer in the background.

- **Timer Service:** `trading-deploy.timer` triggers `trading-deploy.service` which executes `scripts/deploy_pull.sh`.
- **Frequency:** Runs 1 minute after boot, then every **2 minutes**.
- **Efficiency:** The script fetches `origin/main` quietly. If there are no new commits, it exits instantly without consuming system resources.
- **Selective Builds:** If changes are detected, it pulls, selectively runs `pip install` (if `requirements.txt` changed) and `npm run build` (if `frontend/` changed), and restarts `trading.service`.

### Useful Systemd Commands:
Run these on the VPS to manage/check services:

- **Check API Status:** `systemctl status trading`
- **Check Deploy Timer:** `systemctl status trading-deploy.timer`
- **Force Run Auto-Deploy Now:** `sudo systemctl start trading-deploy.service`
- **View Deploy Logs:** `journalctl -u trading-deploy.service -n 50 --no-pager`
- **View API Logs:** `journalctl -u trading.service -n 100 -f --no-pager`

---

## 📁 4. Application Configuration

### Environment Variables (`.env`)
Make sure to open `/opt/trading/.env` on the VPS and fill in your actual API keys (Alice Blue, Upstox, Angel One, Kaggle) so that data collection and trading operations run correctly:
```bash
nano /opt/trading/.env
```

### Nginx Reverse Proxy
Nginx is configured to serve the React application and API routing transparently on standard HTTP port 80.
- Nginx Config Path: `/etc/nginx/sites-available/trading`
- Symbolic Link: `/etc/nginx/sites-enabled/trading`
- FastAPI & Static Frontend: Runs via `trading.service` locally on port `8000`.
