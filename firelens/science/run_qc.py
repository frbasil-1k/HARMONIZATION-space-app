#!/usr/bin/env python3
"""FireLens Phase 1 — one-command quality control run.

Usage
-----
    python science/run_qc.py                                  # full dataset, gate review
    python science/run_qc.py --punjab-test                     # 17:00 handoff file
    python science/run_qc.py --input data/test_punjab_2020_viirs.csv --punjab-test

Runs the eight checks, writes the three sanity plots and exports ``science/gaps.csv``.
Exit status: 0 if every check passed, 1 if any check failed, 2 if the file could not be
loaded. A failed plot or gap export is reported but does not silently turn into a pass.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

# Allow running as `python science/run_qc.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from qc_pipeline import (  # noqa: E402
    SENSORS,
    UTTARAKHAND,
    export_gaps,
    generate_sanity_plots,
    load_data,
    run_quality_checks,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the FireLens Phase 1 QC, plots and gap export in one command.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input",
        default="data/district_monthly.csv",
        help="CSV to check (must follow docs/data-contract.md)",
    )
    parser.add_argument(
        "--punjab-test",
        action="store_true",
        help="treat --input as the partial 17:00 Punjab test file (skips the 132-month grid rule)",
    )
    parser.add_argument(
        "--figures-dir",
        default="science/figures",
        help="directory for the three sanity PNGs",
    )
    parser.add_argument(
        "--gaps-output",
        default="science/gaps.csv",
        help="path for the gap list",
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.10,
        help="clear-view coverage floor below which a row counts as a gap",
    )
    parser.add_argument(
        "--uttarakhand-district",
        default=None,
        help="district for plot 3 (e.g. Nainital); auto-picked from Uttarakhand if omitted",
    )
    parser.add_argument(
        "--dpi", type=int, default=200, help="resolution of the saved PNGs"
    )
    parser.add_argument(
        "--no-plots", action="store_true", help="run checks and gaps only"
    )
    return parser.parse_args(argv)


def _pick_uttarakhand_district(df, requested: str | None) -> str:
    """Use the requested district, or the most active Uttarakhand district available."""
    if requested:
        return requested

    uk = df[df["state"].astype("string").str.strip().str.casefold() == UTTARAKHAND.casefold()]
    if uk.empty:
        return "Nainital"  # no Uttarakhand rows; plot 3 will render its "not found" panel

    from qc_pipeline import add_metrics  # local import keeps module import cheap

    scored = (
        add_metrics(uk)
        .dropna(subset=["activity"])
        .groupby(["state", "district"])["activity"]
        .mean()
        .sort_values(ascending=False)
    )
    if scored.empty:
        return str(uk["district"].iloc[0])
    state, district = scored.index[0]
    print(f"  plot 3 district (auto): {state} / {district}")
    return f"{state}: {district}"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    input_path = Path(args.input)

    if not input_path.is_file():
        print(f"ERROR: input file not found: {input_path.resolve()}", file=sys.stderr)
        if args.punjab_test:
            print(
                "The 17:00 handoff file is expected at "
                "data/test_punjab_2020_viirs.csv. Pass --input if it lives elsewhere.",
                file=sys.stderr,
            )
        return 2

    label = "Punjab test file" if args.punjab_test else "full dataset"
    print(f"FireLens QC — {label}: {input_path}")

    try:
        df = load_data(input_path)
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR: could not load {input_path}: {exc}", file=sys.stderr)
        return 2

    print(
        f"  {len(df):,} rows | {df['state'].nunique()} states | "
        f"{df['district'].nunique()} districts | sensors: "
        f"{', '.join(sorted(df['sensor'].dropna().unique()))}"
    )

    results = run_quality_checks(df, is_full_dataset=not args.punjab_test)

    exit_code = 0 if all(results.values()) else 1

    if not args.no_plots:
        district = _pick_uttarakhand_district(df, args.uttarakhand_district)
        try:
            generate_sanity_plots(df, district, output_dir=args.figures_dir, dpi=args.dpi)
        except Exception:  # a broken plot must not hide the check results above
            print("\nERROR: plot generation failed:", file=sys.stderr)
            traceback.print_exc()
            exit_code = 1

    try:
        export_gaps(df, output_path=args.gaps_output, min_coverage=args.min_coverage)
    except Exception:
        print("\nERROR: gap export failed:", file=sys.stderr)
        traceback.print_exc()
        exit_code = 1

    failed = [name for name, ok in results.items() if not ok]
    if failed:
        print("FAILED checks: " + "; ".join(failed))
        print("Send the failing detail to R1 with the row counts above.")
    else:
        print(f"All {len(results)} checks passed ({len(SENSORS)} sensors checked).")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
