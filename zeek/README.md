# zeek-inline コンテナ（Network Monitoring / IDS）

本コンテナは、攻撃者側ネットワーク（`front_net`）と被害者側ネットワーク（`back_net`）の **両方に接続されたネットワーク監視・解析コンテナ（Zeek / NIDS）** です。

Zeek を用いて、DoS 攻撃・SYN Flood・Slow HTTP 攻撃などの挙動を  
TCP/IP・L7 レベルで詳細に解析することを目的としています。

コンテナは Docker の内部ネットワークのみで動作し、外部に露出しません。

---

## 🌐 ネットワーク構成（attacker 周り）

| コンテナ              | ネットワーク               | IP                            | 役割                       |
| ----------------- | -------------------- | ----------------------------- | ------------------------ |
| attacker-inline   | front_net            | 192.168.10.10                 | 攻撃者                     |
| reverse_proxy     | front_net / back_net | 192.168.10.30 / 192.168.20.30 | 中継点（WSJFスケジューラ）          |
| victim-inline | back_net         | 192.168.20.20             | Apache Web サーバ（攻撃対象） |
| **zeek-inline**       | **front_net / back_net** | **192.168.10.2** / **192.168.20.2**   | **ネットワーク監視（IDS/NIDS）**       |

---

## 📦 インストールされている主要パッケージ

### 🔹 Zeek（メインの NIDS ツール）
- 既存の Zeek イメージ `zeek/zeek:latest` を使用
- コンテナ内で `zeek` コマンドにより pcap 解析やライブ解析が可能

### 🔹 ネットワーク基本ツール
- `iproute2`
- `iputils-ping`
- `net-tools`
- `tcpdump`（パケットキャプチャ）

### 🔹 テキストエディタ
- vim  
- nano  
- less

---

## 🐳 コンテナ設定情報

### Dockerfile

```Dockerfile
FROM zeek/zeek:latest

RUN apt update && \
    apt install -y \
      iproute2 \
      iputils-ping \
      net-tools \
      tcpdump \
      less \
      nano \
      vim \
      && apt clean && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /zeek-logs /zeek-scripts
```

### docker-compose 設定
```yaml
zeek-inline:
  build: ./zeek
  container_name: zeek-inline
  networks:
    back_net:
      ipv4_address: 192.168.20.2
    front_net:
      ipv4_address: 192.168.10.2

  # インライン監視を想定
  sysctls:
    net.ipv4.ip_forward: 1

  environment:
    - TZ=Asia/Tokyo
  cap_add:
    - NET_ADMIN
    - NET_RAW
  command: tail -f /dev/null
  volumes:
    - ./zeek/logs:/zeek-logs
    - ./zeek/scripts:/zeek-scripts
    - ./bin/zeek-color:/usr/local/bin/zeek-color
```

---

## ▶️ コンテナへのアクセス
```bash
docker exec -it zeek-inline bash
```

---

## 📁 ディレクトリ構成について
### `/zeek-scripts`
ホストの `./zeek/scripts/` と同期されています。
カスタム Zeek スクリプト（`.zeek` ファイル）を置く場所です。

例：
```pgsql
./zeek/scripts/
├── syn-flood.zeek
└── http-monitor.zeek
```

### `/zeek-logs`
ホストの `./zeek/logs/` と同期されています。
Zeek が出力するログファイルを保存するディレクトリです。

例：
```pgsql
./zeek/logs/
├── conn.log
├── http.log
├── notice.log
└── weird.log
```

### `/usr/local/bin/zeek-color`
Zeek ログのカラー表示ツールをホスト側から提供

---

## 🧪 使用例
### 1. インターフェースの確認
`zeek-inline` は `front_net` と `back_net` の 2 つの NIC を持ちます。
どのインターフェースがどのネットワークに対応しているかを確認します。

```bash
ip a
```
例：

* eth0 → 192.168.10.2（front_net）

* eth1 → 192.168.20.2（back_net）

（実際の割り当ては `ip a` で確認してください）

### 2. front_net 側のライブ解析
attacker-inline → reverse_proxy 間のトラフィックを監視：
```bash
cd /zeek-logs
zeek-color -i eth0 /zeek-scripts/your_script.zeek
```
`eth0` が `front_net` 側インタフェースであると仮定した例です。

### 3. back_net 側のライブ解析
reverse_proxy → victim-inline 間のトラフィックを監視：
```bash
cd /zeek-logs
zeek-color -i eth1 /zeek-scripts/your_script.zeek
```
`eth1` が `back_net` 側インタフェースであると仮定した例です。

---

## 🔒 注意事項
* Zeek は大量のログを生成するため、
不要な解析は行わず適宜 `logs/` を整理してください。

---

## 📝 補足：zeek でよく使うコマンドまとめ
| コマンド              | 用途                                |
| ----------------- | --------------------------------- |
| `zeek -r file.pcap`            | pcap のオフライン解析                |
| `zeek -r file.pcap script.zeek`         | カスタムスクリプト適用 |
| `less conn.log` | 通信ログの確認                     |
| `ip a`          | ネットワークインターフェース（NIC）と、それに割り当てられたIPアドレスなどの情報を一覧表示 | 
---

## 📌 バージョン情報
* Base image: `zeek/zeek:latest`

* Tools: tcpdump / ping / vim / nano など

