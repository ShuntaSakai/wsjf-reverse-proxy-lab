import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import re
import os
import sys
from datetime import datetime

# GUIがない環境でも必ず保存できるようにする
import matplotlib
matplotlib.use("Agg")

# ログ抽出用の正規表現 (柔軟性を高めています)
LOG_PATTERN = r'(?P<ts>\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+\[(?P<event>\w+)\]\s+tag=(?P<tag>\S+)\s+cid=(?P<cid>\S+)\s+pri=(?P<pri>[\d.eE-]+)'

# ログのタイムスタンプを計算可能な形式に変換
def parse_ts(s):
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return pd.to_datetime(s)

# ログの解析と整理
def process_logs(file_path):
    data = []
    if not os.path.exists(file_path):
        print(f"Error: File not found {file_path}")
        return None
    # ログファイルの読み込みと解析
    # (key)、時間、イベントタイプ、タグ、CID、優先度、(シーケンス番号、キューサイズ)を抽出
    # 0  2026-01-07T04:18:06.174516499Z  Enqueue  0001   F  0.000006 2026-01-07 04:18:06.174516499+00:00  NaN    NaN
    with open(file_path, 'r') as f:
        for line in f:
            match = re.search(LOG_PATTERN, line)
            if match:
                entry = match.groupdict()
                # 追加情報の抽出
                seq_match = re.search(r'seq=(\d+)', line)
                qsize_match = re.search(r'qsize=(\d+)', line)
                
                entry['timestamp'] = parse_ts(entry['ts'])
                entry['seq'] = int(seq_match.group(1)) if seq_match else None
                entry['qsize'] = int(qsize_match.group(1)) if qsize_match else None
                data.append(entry)

    if not data:
        print("No data found in log file.")
        return None

    df = pd.DataFrame(data)
    
    # EnqueueとSchedulerを分離
    df_enq = df[df['event'] == 'Enqueue'][['timestamp', 'tag', 'cid', 'pri']].rename(columns={'timestamp': 'ts_enq'})
    df_sch = df[df['event'] == 'Scheduler'][['timestamp', 'tag', 'cid', 'seq', 'qsize']].rename(columns={'timestamp': 'ts_sch'})

    if df_enq.empty or df_sch.empty:
        print(f"Warning: Enqueue({len(df_enq)}) or Scheduler({len(df_sch)}) data is missing.")
        return None

    # tag と cid をキーに結合
    combined = pd.merge(df_enq, df_sch, on=['tag', 'cid'])

    if combined.empty:
        print("Error: No matching Enqueue and Scheduler events found.")
        return None

    # 待ち時間を計算
    combined['wait_time'] = (combined['ts_sch'] - combined['ts_enq']).dt.total_seconds() * 1000
    return combined, df[df['event'] == 'Scheduler']

# --- メイン処理 ---
out_dir = "out"
os.makedirs(out_dir, exist_ok=True)
input_file = 'out/experiment_raw.log'

result = process_logs(input_file)

if result:
    combined, df_sch_only = result

    # 統計情報の出力
    print("\n=== 待ち時間統計 (ms) ===")
    stats = combined.groupby('cid')['wait_time'].describe()
    print(stats)
    
    # 平均待ち時間の比較計算
    avg_f = combined[combined['cid'] == 'F']['wait_time'].mean()
    avg_s = combined[combined['cid'] == 'S']['wait_time'].mean()
    if pd.notnull(avg_f) and pd.notnull(avg_s) and avg_f > 0:
        print(f"\n[比較] 平均待ち時間 S/F比: {avg_s / avg_f:.2f}倍")


    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 15))

    # 1. 待ち時間のプロット
    for cid in combined['cid'].unique():
        subset = combined[combined['cid'] == cid]
        ax1.scatter(subset['ts_enq'], subset['wait_time'], label=f'CID: {cid}', s=15, alpha=0.6)
    ax1.set_ylabel('Wait Time (ms)')
    ax1.set_title('Request Wait Time Over Time')
    ax1.legend()
    ax1.grid(True)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))

    # 2. キューサイズのプロット
    ax2.plot(df_sch_only['timestamp'], df_sch_only['qsize'], color='black', label='Queue Size', linewidth=1)
    ax2.set_ylabel('Queue Size')
    ax2.set_title('Queue Size Trend')
    ax2.legend()
    ax2.grid(True)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))

    # 3. 待ち時間の分布（ヒストグラム）
    colors = {'F': 'blue', 'S': 'orange'}
    for cid in combined['cid'].unique():
        subset = combined[combined['cid'] == cid]
        ax3.hist(subset['wait_time'], bins=30, alpha=0.5, label=f'CID: {cid}', color=colors.get(cid, None))
    ax3.set_xlabel('Wait Time (ms)')
    ax3.set_ylabel('Frequency')
    ax3.set_title('Distribution of Wait Times')
    ax3.legend()
    ax3.grid(True)

    out_path = f"{out_dir}/analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    plt.tight_layout()
    plt.savefig(out_path)
    print(f"Success: Chart saved to {out_path}")
else:
    print("Failed to generate plot due to missing data.")