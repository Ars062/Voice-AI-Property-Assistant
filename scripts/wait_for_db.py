"""Wait until PostgreSQL accepts connections, then exit 0."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.db import health  # noqa: E402


def main(timeout: int = 90) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = health()
        if status.get("ok"):
            print(f"database ready: {status}")
            return 0
        print(f"waiting for database... ({status.get('error', 'not ready')})")
        time.sleep(2)
    print("database did not become ready in time.", file=sys.stderr)
    print("Is Docker running? Try: docker compose up -d", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
