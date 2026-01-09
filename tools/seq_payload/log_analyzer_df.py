#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# DF 値の算出をする

import os
import re
import sys
from datetime import datetime
from typing import Optional, Tuple, Dict

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


LOG_PATTERN = (
    r'(?P<ts>\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+'
    r'\[(?P<event>\w+)\]\s+'
    r'tag=(?P<tag>\S+)\s+'
    r'cid=(?P<cid>\S+)\s+'
    r'pri=(?P<pri>[\d.eE-]+)'
)

RE_SEQ = re.compile(r"\bseq=(\d+)\b")
RE_QSIZE = re.compile(r"\bqsize=(\d+)\b")
RE_BYTES = re.compile(r"\bbytes=(\d+)\b")


def parse_ts(s: str) -> pd.Timestamp:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return pd.to_datetime(s)


def parse_log_file(file_path: str) -> Optional[pd.DataFrame]:
    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        return None

    rows = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.search(LOG_PATTERN, line)
            if not m:
                continue

            d = m.groupdict()
            d["timestamp"] = parse_ts(d["ts"])

            seq_m = RE_SEQ.search(line)
            qsize_m = RE_QSIZE.search(line)
            bytes_m = RE_BYTES.search(line)

            d["seq"] = int(seq_m.group(1)) if seq_m else None
            d["qsize"] = int(qsize_m.group(1)) if qsize_m else None
            d["bytes"] = int(bytes_m.group(1)) if bytes_m else None

            try:
                d["pri"] = float(d["pri"])
            except Exception:
                pass

            rows.append(d)

    if not rows:
        print(f"No data found in log file: {file_path}")
        return None

    return pd.DataFrame(rows)


def pair_enqueue_scheduler(df: pd.DataFrame) -> Optional[Tuple[pd.DataFrame, pd.DataFrame]]:
    df_enq = df[df["event"] == "Enqueue"].copy()
    df_sch = df[df["event"] == "Scheduler"].copy()

    if df_enq.empty or df_sch.empty:
        print(f"Warning: Enqueue({len(df_enq)}) or Scheduler({len(df_sch)}) data is missing.")
        return None

    df_enq = df_enq[["timestamp", "tag", "cid", "pri", "bytes"]].rename(
        columns={"timestamp": "ts_enq", "bytes": "bytes_enq"}
    )
    df_sch_only = df_sch[["timestamp", "tag", "cid", "seq", "qsize", "bytes"]].rename(
        columns={"timestamp": "ts_sch", "bytes": "bytes_sch"}
    )

    keys = sorted(
        set(map(tuple, df_enq[["tag", "cid"]].drop_duplicates().values))
        | set(map(tuple, df_sch_only[["tag", "cid"]].drop_duplicates().values))
    )

    paired_rows = []
    skipped_scheduler = 0
    unmatched_enqueue = 0

    for (tag, cid) in keys:
        enq_g = (
            df_enq[(df_enq["tag"] == tag) & (df_enq["cid"] == cid)]
            .sort_values("ts_enq")
            .reset_index(drop=True)
        )
        sch_g = (
            df_sch_only[(df_sch_only["tag"] == tag) & (df_sch_only["cid"] == cid)]
            .sort_values("ts_sch")
            .reset_index(drop=True)
        )

        i = 0
        j = 0
        while i < len(enq_g) and j < len(sch_g):
            ts_e = enq_g.loc[i, "ts_enq"]
            ts_s = sch_g.loc[j, "ts_sch"]

            if ts_s < ts_e:
                skipped_scheduler += 1
                j += 1
                continue

            bytes_val = sch_g.loc[j, "bytes_sch"]
            if bytes_val is None or (isinstance(bytes_val, float) and pd.isna(bytes_val)):
                bytes_val = enq_g.loc[i, "bytes_enq"]

            paired_rows.append(
                {
                    "tag": tag,
                    "cid": cid,
                    "pri": enq_g.loc[i, "pri"],
                    "ts_enq": ts_e,
                    "ts_sch": ts_s,
                    "seq": sch_g.loc[j, "seq"],
                    "qsize": sch_g.loc[j, "qsize"],
                    "bytes": bytes_val,
                }
            )
            i += 1
            j += 1

        if i < len(enq_g):
            unmatched_enqueue += (len(enq_g) - i)

    if not paired_rows:
        print("Error: No matching Enqueue -> Scheduler pairs found (after time-order pairing).")
        return None

    combined = pd.DataFrame(paired_rows)
    combined["wait_time"] = (combined["ts_sch"] - combined["ts_enq"]).dt.total_seconds() * 1000.0

    if skipped_scheduler or unmatched_enqueue:
        print(f"[pairing info] skipped_scheduler(before enqueue)={skipped_scheduler}, unmatched_enqueue(no scheduler)={unmatched_enqueue}")

    return combined, df_sch_only


def _sum_bytes_in_window(df: pd.DataFrame, time_col: str, cid: str, t0: pd.Timestamp, t1: pd.Timestamp) -> float:
    sub = df[df["cid"] == cid].copy()
    sub = sub.dropna(subset=[time_col])
    if sub.empty:
        return 0.0
    if "bytes" not in sub.columns or sub["bytes"].isna().all():
        return float("nan")
    sub = sub[(sub[time_col] >= t0) & (sub[time_col] <= t1)]
    if sub.empty:
        return 0.0
    return float(sub["bytes"].fillna(0).sum())


def _bps_from_sum_bytes(total_bytes: float, dur_s: float) -> float:
    if dur_s <= 0:
        return 0.0
    if pd.isna(total_bytes):
        return float("nan")
    return (total_bytes * 8.0) / dur_s


def calc_df_baseline_drain(
    baseline_combined: pd.DataFrame,
    attack_combined: pd.DataFrame,
    attack_raw_df: pd.DataFrame,
) -> Dict:
    base_f = baseline_combined[baseline_combined["cid"] == "F"].dropna(subset=["ts_sch"]).sort_values("ts_sch")
    if base_f.empty:
        return {"note": "baseline に Scheduler cid=F が無く、T を決められません", "DF": float("nan")}

    base_t0 = base_f["ts_sch"].iloc[0]
    base_t1 = base_f["ts_sch"].iloc[-1]
    T = (base_t1 - base_t0).total_seconds()
    if T <= 0:
        return {"note": "baseline の T が 0 以下になりました", "DF": float("nan")}

    atk_f = attack_combined[attack_combined["cid"] == "F"].dropna(subset=["ts_sch"]).sort_values("ts_sch")
    if atk_f.empty:
        return {"note": "attack に Scheduler cid=F が無く、比較窓を作れません", "DF": float("nan")}

    atk_t0 = atk_f["ts_sch"].iloc[0]
    atk_t1 = atk_t0 + pd.to_timedelta(T, unit="s")

    base_w0 = base_t0
    base_w1 = base_t0 + pd.to_timedelta(T, unit="s")

    base_F_bytes = _sum_bytes_in_window(baseline_combined, "ts_sch", "F", base_w0, base_w1)
    atk_F_bytes = _sum_bytes_in_window(attack_combined, "ts_sch", "F", atk_t0, atk_t1)

    F_base_bps = _bps_from_sum_bytes(base_F_bytes, T)
    F_attack_bps = _bps_from_sum_bytes(atk_F_bytes, T)

    enq_s = attack_raw_df[attack_raw_df["event"] == "Enqueue"].copy()
    enq_s = enq_s.dropna(subset=["timestamp"])
    enq_s = enq_s[enq_s["cid"] == "S"].copy()
    if enq_s.empty or ("bytes" not in enq_s.columns) or enq_s["bytes"].isna().all():
        S_effort_bps = float("nan")
        S_effort_bytes = float("nan")
    else:
        enq_s_win = enq_s[(enq_s["timestamp"] >= atk_t0) & (enq_s["timestamp"] <= atk_t1)]
        S_effort_bytes = float(enq_s_win["bytes"].fillna(0).sum())
        S_effort_bps = _bps_from_sum_bytes(S_effort_bytes, T)

    if pd.isna(F_base_bps) or pd.isna(F_attack_bps) or pd.isna(S_effort_bps):
        return {
            "note": "bytes= が不足していて DF を算出できません（baseline/attack/S effort のどこかが NaN）",
            "T": T,
            "attack_window": (atk_t0, atk_t1),
            "baseline_window": (base_w0, base_w1),
            "F_base_bps": F_base_bps,
            "F_attack_bps": F_attack_bps,
            "S_effort_bps": S_effort_bps,
            "lost_F_bps": float("nan"),
            "DF": float("nan"),
        }

    lost_F_bps = max(0.0, F_base_bps - F_attack_bps)
    DF = (lost_F_bps / S_effort_bps) if S_effort_bps > 0 else float("inf")

    base_F_cnt = int(baseline_combined[(baseline_combined["cid"] == "F") & (baseline_combined["ts_sch"].between(base_w0, base_w1))].shape[0])
    atk_F_cnt = int(attack_combined[(attack_combined["cid"] == "F") & (attack_combined["ts_sch"].between(atk_t0, atk_t1))].shape[0])
    atk_S_enq_cnt = int(enq_s[(enq_s["timestamp"].between(atk_t0, atk_t1))].shape[0]) if not enq_s.empty else 0

    return {
        "note": "",
        "T": T,
        "attack_window": (atk_t0, atk_t1),
        "baseline_window": (base_w0, base_w1),
        "F_base_bps": F_base_bps,
        "F_attack_bps": F_attack_bps,
        "S_effort_bps": S_effort_bps,
        "lost_F_bps": lost_F_bps,
        "DF": DF,
        "base_F_cnt_in_T": base_F_cnt,
        "atk_F_cnt_in_T": atk_F_cnt,
        "base_F_bytes_in_T": base_F_bytes,
        "atk_F_bytes_in_T": atk_F_bytes,
        "atk_S_enq_cnt_in_T": atk_S_enq_cnt,
        "atk_S_effort_bytes_in_T": S_effort_bytes,
    }


def plot_wait_and_queue(
    combined: pd.DataFrame,
    df_sch_only: pd.DataFrame,
    out_dir: str,
    title_suffix: str = "",
):
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 15))

    for cid in sorted(combined["cid"].unique()):
        sub = combined[combined["cid"] == cid]
        ax1.scatter(sub["ts_enq"], sub["wait_time"], label=f"CID: {cid}", s=15, alpha=0.6)

    ax1.set_ylabel("Wait Time (ms)")
    ax1.set_title("Request Wait Time Over Time" + (f" | {title_suffix}" if title_suffix else ""))
    ax1.legend()
    ax1.grid(True)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))

    df_sch_only = df_sch_only.sort_values("ts_sch")
    ax2.plot(df_sch_only["ts_sch"], df_sch_only["qsize"], linewidth=1, label="Queue Size")
    ax2.set_ylabel("Queue Size")
    ax2.set_title("Queue Size Trend")
    ax2.legend()
    ax2.grid(True)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))

    for cid in sorted(combined["cid"].unique()):
        sub = combined[combined["cid"] == cid]
        ax3.hist(sub["wait_time"], bins=30, alpha=0.5, label=f"CID: {cid}")

    ax3.set_xlabel("Wait Time (ms)")
    ax3.set_ylabel("Frequency")
    ax3.set_title("Distribution of Wait Times")
    ax3.legend()
    ax3.grid(True)

    out_path = os.path.join(out_dir, f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    plt.tight_layout()
    plt.savefig(out_path)
    print(f"Success: Chart saved to {out_path}")


def main():
    out_dir = "out"
    os.makedirs(out_dir, exist_ok=True)

    if len(sys.argv) < 2:
        print("Usage: python log_analyzer.py <attack_log> [baseline_log]")
        sys.exit(1)

    attack_file = sys.argv[1]
    baseline_file = sys.argv[2] if len(sys.argv) >= 3 else None

    df_atk_raw = parse_log_file(attack_file)
    if df_atk_raw is None:
        print("Failed to parse attack log.")
        return

    atk_pair = pair_enqueue_scheduler(df_atk_raw)
    if atk_pair is None:
        print("Failed to pair attack log.")
        return

    combined_atk, df_sch_only_atk = atk_pair

    print("\n=== [ATTACK] 待ち時間統計 (ms) ===")
    print(combined_atk.groupby("cid")["wait_time"].describe())

    avg_f = combined_atk.loc[combined_atk["cid"] == "F", "wait_time"].mean()
    avg_s = combined_atk.loc[combined_atk["cid"] == "S", "wait_time"].mean()
    if pd.notnull(avg_f) and pd.notnull(avg_s) and avg_f > 0:
        print(f"\n[ATTACK 比較] 平均待ち時間 S/F比: {avg_s / avg_f:.2f}倍")

    title_suffix = ""

    if baseline_file:
        df_base_raw = parse_log_file(baseline_file)
        if df_base_raw is None:
            print("Failed to parse baseline log.")
            return

        base_pair = pair_enqueue_scheduler(df_base_raw)
        if base_pair is None:
            print("Failed to pair baseline log.")
            return

        combined_base, _ = base_pair

        dfres = calc_df_baseline_drain(combined_base, combined_atk, df_atk_raw)

        print("\n=== DF (bps-based, baseline-drain-duration) ===")
        if dfres.get("note"):
            print(dfres["note"])
        else:
            atk_w0, atk_w1 = dfres["attack_window"]
            base_w0, base_w1 = dfres["baseline_window"]
            T = dfres["T"]
            print(f"attack_window  : {atk_w0} .. {atk_w1}  (dur={T:.3f}s)")
            print(f"baseline_window: {base_w0} .. {base_w1}  (dur={T:.3f}s)")
            print(f"F_base_bps     : {dfres['F_base_bps']}")
            print(f"F_attack_bps   : {dfres['F_attack_bps']}")
            print(f"S_effort_bps   : {dfres['S_effort_bps']}   (Enqueue-based)")
            print(f"lost_F_bps     : {dfres['lost_F_bps']}")
            print(f"DF             : {dfres['DF']}")
            print(f"[sanity] base_F_cnt_in_T={dfres['base_F_cnt_in_T']}, atk_F_cnt_in_T={dfres['atk_F_cnt_in_T']}, atk_S_enq_cnt_in_T={dfres['atk_S_enq_cnt_in_T']}")
            print(f"[sanity] base_F_bytes_in_T={dfres['base_F_bytes_in_T']}, atk_F_bytes_in_T={dfres['atk_F_bytes_in_T']}, atk_S_effort_bytes_in_T={dfres['atk_S_effort_bytes_in_T']}")

            title_suffix = f"DF={dfres['DF']:.4f}  lost_F={dfres['lost_F_bps']:.1f}bps (T={T:.3f}s)"

    plot_wait_and_queue(combined_atk, df_sch_only_atk, out_dir, title_suffix=title_suffix)


if __name__ == "__main__":
    main()
