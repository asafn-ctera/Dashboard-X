#!/usr/bin/env python3
"""Entry point for Dashboard-X."""

import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import load_config


def main() -> None:
    import uvicorn

    config = load_config()
    port = config.dashboard.port

    print(
        f"\n"
        f"  Dashboard-X\n"
        f"  http://localhost:{port}\n"
        f"  Press Ctrl+C to stop\n"
    )

    try:
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass

    uvicorn.run("app.main:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
