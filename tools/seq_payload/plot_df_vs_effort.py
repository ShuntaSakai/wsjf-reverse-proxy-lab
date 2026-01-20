#!/usr/bin/env python3
# tools/seq_payload/plot_df_vs_effort.py
#
# Usage:
#   python3 tools/seq_payload/plot_df_vs_effort.py out/df_sweep_YYYYMMDD_HHMMSS.csv
# Options:
#   --out out/df_vs_effort.png
#   --logx
#   --title "DF vs S_effort_bps (pad sweep)"
#   --annotate-all
#   --annotate-first-last

import argparse
import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt


def _to_float(x: str):
    if x is None:
        return None
    s = str(x).strip()
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(x: str):
    if x is None:
        return None
    s = str(x).strip()
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def load_rows(csv_path: Path):
    rows = []
    with csv_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            pad = _to_int(r.get("pad"))
            s_eff = _to_float(r.get("S_effort_bps"))
            df = _to_float(r.get("DF"))
            if pad is None or s_eff is None or df is None:
                # skip incomplete lines
                continue
            rows.append((pad, s_eff, df))
    return rows


def pick_annotations(rows, mode_all: bool, mode_first_last: bool):
    if not rows:
        return []

    # sort by S_effort for stable annotation placement
    rows_sorted = sorted(rows, key=lambda t: t[1])
    if mode_all:
        return rows_sorted

    if mode_first_last:
        return [rows_sorted[0], rows_sorted[-1]]

    # default: annotate min-pad and max-pad if they exist
    min_pad = min(rows_sorted, key=lambda t: t[0])
    max_pad = max(rows_sorted, key=lambda t: t[0])
    ann = [min_pad]
    if max_pad != min_pad:
        ann.append(max_pad)
    return ann


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=str, help="results csv (pad,S_effort_bps,DF,...)")
    ap.add_argument("--out", type=str, default="", help="output image path (png)")
    ap.add_argument("--logx", action="store_true", help="use log scale on x-axis")
    ap.add_argument("--title", type=str, default="DF vs S_effort_bps (pad sweep)")
    ap.add_argument("--annotate-all", action="store_true", help="annotate every point with pad=")
    ap.add_argument("--annotate-first-last", action="store_true", help="annotate only first/last by x")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    rows = load_rows(csv_path)
    if not rows:
        raise SystemExit("No valid rows found (need pad, S_effort_bps, DF).")

    pads = [p for (p, _, _) in rows]
    xs = [x for (_, x, _) in rows]
    ys = [y for (_, _, y) in rows]

    # default output path
    if args.out.strip():
        out_path = Path(args.out)
    else:
        out_path = csv_path.with_suffix(".df_vs_effort.png")

    plt.figure()
    plt.scatter(xs, ys)
    plt.xlabel("S_effort_bps")
    plt.ylabel("DF")
    plt.title(args.title)
    plt.grid(True)

    if args.logx:
        # avoid log(0)
        if any(x <= 0 for x in xs):
            print("[WARN] --logx ignored because some S_effort_bps <= 0")
        else:
            plt.xscale("log")

    ann_rows = pick_annotations(
        rows,
        mode_all=args.annotate_all,
        mode_first_last=args.annotate_first_last,
    )

    # annotate with simple offsets that don't depend on colors/styles
    for (pad, x, y) in ann_rows:
        label = f"pad={pad}"
        # offset a bit; in log scale, use multiplicative-ish shift
        dx = 0.0
        dy = 0.0
        if args.logx:
            dx = x * 0.02
        else:
            dx = (max(xs) - min(xs)) * 0.01
        dy = (max(ys) - min(ys)) * 0.01 if max(ys) != min(ys) else 0.001
        plt.annotate(label, (x, y), xytext=(x + dx, y + dy))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    print(f"[ok] saved: {out_path}")


if __name__ == "__main__":
    main()
