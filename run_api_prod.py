"""Service runner. Auto-reloads api/ on file changes so service restarts are not
needed for code edits. Run from project root: python run_api_prod.py"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=["api"],
        workers=1,
    )
