#!/usr/bin/env python3
"""Compatibility entry point for the fail-closed P0 probe analyser."""

from __future__ import annotations

from analyze_v1_local_probes import main


if __name__ == "__main__":
    raise SystemExit(main())
