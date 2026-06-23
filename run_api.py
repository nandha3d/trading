"""Start FastAPI backend. Run from project root: py run_api.py"""
import os

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("BACKEND_PORT", "8001"))
    reload_enabled = os.getenv("BACKEND_RELOAD", "0").lower() in {"1", "true", "yes"}
    uvicorn.run("api.main:app", host="0.0.0.0", port=port, reload=reload_enabled)
