#!/usr/bin/env python3
"""FastAPI server for deploying the Leaderboard web page

Provides static file serving and API endpoints to regenerate leaderboard
"""
from __future__ import annotations

import argparse
import asyncio
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from browseruse_bench.leaderboard.generator import (
    LeaderboardError,
    generate_leaderboard,
    get_regenerate_timeout_seconds,
)
from browseruse_bench.utils import EXPERIMENTS_DIR, REPO_ROOT, setup_logger

logger = setup_logger("benchmark-server")

app = FastAPI(
    title="BrowserUse Bench Leaderboard",
    description="Leaderboard web server for browser agent benchmarks",
    version="1.0.0"
)

# Enable CORS to allow cross-origin access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Recommended to restrict to specific domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file directory - use absolute paths
EXPERIMENTS_ROOT = (REPO_ROOT / EXPERIMENTS_DIR).resolve()
LEADERBOARD_HTML = EXPERIMENTS_ROOT / "leaderboard.html"


@app.get("/", response_class=HTMLResponse)
async def root():
    """Main page, returns leaderboard.html"""
    if not LEADERBOARD_HTML.exists():
        return HTMLResponse(
            content="<h1>Leaderboard not found</h1><p>Please generate the leaderboard first.</p>",
            status_code=404
        )
    html_content = LEADERBOARD_HTML.read_text(encoding='utf-8')
    # Path handling is already implemented in the template, no need to handle it here
    return HTMLResponse(content=html_content)


@app.get("/api/status")
async def get_status():
    """Get server status"""
    return {
        "status": "running",
        "leaderboard_exists": LEADERBOARD_HTML.exists(),
        "experiments_dir": str(EXPERIMENTS_ROOT),
    }


@app.post("/api/regenerate")
async def regenerate_leaderboard():
    """Regenerate leaderboard"""
    try:
        timeout_seconds = get_regenerate_timeout_seconds()
        output_path = await asyncio.wait_for(
            asyncio.to_thread(generate_leaderboard, "leaderboard.html", None),
            timeout=timeout_seconds,
        )
        return {
            "status": "success",
            "message": "Leaderboard regenerated successfully",
            "output_path": str(output_path),
        }
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=500,
            detail="Generation timed out"
        )
    except LeaderboardError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Generation failed: {exc}",
        )
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Generation error: {exc}",
        )


# Mount static file directory (for serving images, JSON, etc.)
if EXPERIMENTS_ROOT.exists():
    app.mount("/experiments", StaticFiles(directory=str(EXPERIMENTS_ROOT)), name="experiments")
    logger.info(f"[SUCCESS] Static file service mounted: /experiments -> {EXPERIMENTS_ROOT}")
else:
    logger.warning(f"[WARNING] Warning: experiments directory does not exist: {EXPERIMENTS_ROOT}")


def run_server(host: str, port: int, reload: bool) -> None:
    logger.info("[INFO] Starting Leaderboard Web Server...")
    logger.info("   Address: http://%s:%s", host, port)
    logger.info("   Home: http://%s:%s/", host, port)
    logger.info("   API Docs: http://%s:%s/docs", host, port)
    logger.info("   Status: http://%s:%s/api/status", host, port)
    logger.info("   Regenerate: POST http://%s:%s/api/regenerate", host, port)
    logger.info("[INFO] Path Info:")
    logger.info("   REPO_ROOT: %s", REPO_ROOT)
    logger.info("   EXPERIMENTS_DIR: %s", EXPERIMENTS_ROOT)
    logger.info("   LEADERBOARD_HTML: %s", LEADERBOARD_HTML)
    logger.info("   Static files exist: %s", EXPERIMENTS_ROOT.exists())
    logger.info("   Leaderboard exists: %s", LEADERBOARD_HTML.exists())
    logger.info("Tips:")
    logger.info("   - Generate benchmark data first: uv run scripts/run.py ...")
    logger.info("   - Refresh leaderboard: uv run scripts/leaderboard.py")
    logger.info("Press Ctrl+C to stop server")

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Start Leaderboard Web Server")
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Server listen address (default: 0.0.0.0, allows external access)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Server port (default: 8000)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (development mode)"
    )

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    run_server(args.host, args.port, args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
