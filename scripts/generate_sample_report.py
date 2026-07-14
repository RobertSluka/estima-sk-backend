#!/usr/bin/env python3
"""
Generate a sample property valuation PDF locally — no database required.

It renders the mock report from `src.services.reports.mock` and writes both the
standalone HTML (always) and the PDF (if WeasyPrint's native stack is available)
to the artifacts/ directory. Writing the HTML unconditionally means you get a
useful, inspectable artifact even on a machine without Pango/Cairo installed.

Usage:
    python -m scripts.generate_sample_report                # full sample
    python -m scripts.generate_sample_report --sparse       # fallback-states sample
    python -m scripts.generate_sample_report --out mydir    # custom output dir

Run it inside the tools container to get the PDF too (see README):
    docker compose run --rm ml-api python -m scripts.generate_sample_report
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.services.reports import mock
from src.services.reports.pdf import render_html, render_pdf


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a sample Estima PDF report.")
    parser.add_argument("--sparse", action="store_true",
                        help="Use the sparse sample (missing vision/location/comparables) to show fallbacks.")
    parser.add_argument("--out", default="artifacts", help="Output directory (default: artifacts).")
    parser.add_argument("--name", default=None, help="Base filename (default: sample_report[_sparse]).")
    args = parser.parse_args()

    report = mock.sparse_report() if args.sparse else mock.sample_report()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = args.name or ("sample_report_sparse" if args.sparse else "sample_report")

    # HTML always — useful even without the PDF engine.
    html_path = out_dir / f"{base}.html"
    html_path.write_text(render_html(report), encoding="utf-8")
    print(f"✓ Wrote HTML  → {html_path}")

    # PDF if the native stack is present.
    pdf_path = out_dir / f"{base}.pdf"
    try:
        pdf_path.write_bytes(render_pdf(report))
        print(f"✓ Wrote PDF   → {pdf_path}")
    except ImportError as exc:
        print(f"! Skipped PDF (WeasyPrint not available): {exc}", file=sys.stderr)
        print("  Open the HTML above, or run inside the Docker tools container "
              "where the native libraries are installed.", file=sys.stderr)
        return 0
    except Exception as exc:  # pragma: no cover - surface any renderer error clearly
        print(f"✗ PDF generation failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
