#!/usr/bin/env python3
"""Compatibility entry point for the frozen P0 public-API probe driver.

The implementation is shared with the older ``run_v1_local_probes`` name so
there is exactly one session lifecycle: new session, public scan/actions, then
one post-session ``trigger_eval``. Raw records remain under ignored
``experiments/raw/`` and no retry is performed after a protocol failure.
"""

from __future__ import annotations

from run_v1_local_probes import main


if __name__ == "__main__":
    raise SystemExit(main())
