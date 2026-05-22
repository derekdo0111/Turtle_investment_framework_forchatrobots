#!/usr/bin/env python3
"""Turtle Investment Framework - Akshare Data Collector (Phase 1A).

Facade module: re-exports all public names and defines AkshareClient
which inherits from mixin classes in akshare_modules/.

Collects 5 years of financial data from akshare and outputs
a structured data_pack_market.md file.

Usage:
    python scripts/akshare_collector.py --code 600519.SH
    python scripts/akshare_collector.py --code 600519.SH --output output/data_pack.md
    python scripts/akshare_collector.py --code 600519.SH --dry-run
"""

import argparse
import functools
import os
import sys
import time

import akshare as ak
import pandas as pd

try:
    import yfinance as yf
    _yf_available = True
except ImportError:
    _yf_available = False

from config import validate_stock_code
from format_utils import format_number, format_table, format_header

from akshare_modules import (
    HK_INCOME_MAP, HK_BALANCE_MAP, HK_CASHFLOW_MAP,
    US_INCOME_MAP, US_BALANCE_MAP, US_CASHFLOW_MAP,
    _YF_INCOME_MAP, _YF_BALANCE_MAP, _YF_CASHFLOW_MAP,
    InfrastructureMixin, YFinanceMixin, FinancialsMixin,
    OtherDataMixin, DerivedMetricsMixin, AssemblyMixin,
    WarningsCollector,
)


def akshare_retry(max_retries=3, delay=1.0):
    """Retry decorator for akshare API calls with network error handling."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    if attempt < max_retries:
                        time.sleep(delay * attempt)
                    else:
                        raise
            raise last_err
        return wrapper
    return decorator


class AkshareClient(
    InfrastructureMixin,
    YFinanceMixin,
    FinancialsMixin,
    OtherDataMixin,
    DerivedMetricsMixin,
    AssemblyMixin,
):
    """Client for akshare financial data API."""

    # No token needed — akshare is free and open source
    # Rate limiting is lighter since akshare uses public data sources

    def __init__(self):
        self.ak = ak  # Direct akshare reference for mixin use
        self._store: dict = {}
        self._yf_available = _yf_available
        self._cache_dir = os.path.join("output", ".collector_cache")
        self._fy_end_month: int = 12
        self._currency: str = "CNY"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Collect financial data from akshare",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --code 600519.SH
  %(prog)s --code 600519 --output output/data_pack_market.md
  %(prog)s --code 000858.SZ
        """,
    )
    parser.add_argument("--code", required=True,
                        help="Stock code (e.g., 600519.SH, 000858.SZ, 00700.HK)")
    parser.add_argument("--output", default="output/data_pack_market.md",
                        help="Output file path (default: output/data_pack_market.md)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print parsed arguments and exit without calling API")
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        ts_code = validate_stock_code(args.code)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("=== Dry Run ===")
        print(f"  Stock code: {args.code} -> {ts_code}")
        print(f"  Output: {args.output}")
        print(f"  Data source: akshare (free)")
        return

    client = AkshareClient()

    print(f"Collecting data for {ts_code} via akshare...")
    data_pack = client.assemble_data_pack(ts_code)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(data_pack)

    print(f"Output written to {args.output}")
    print(f"File size: {os.path.getsize(args.output):,} bytes")


if __name__ == "__main__":
    main()
