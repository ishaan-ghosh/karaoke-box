from __future__ import annotations

import multiprocessing

from app.desktop import safe_main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(safe_main())
