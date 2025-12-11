# attacker コンテナ（Kali Linux／フロント側クライアント）

本コンテナは、Kali Linux をベースにした **攻撃生成用コンテナ** です。  
DoS / Slow HTTP / ポートスキャン / ブルートフォースなどの攻撃トラフィックを、  **フロント側ネットワーク（front_net）** 上から生成するために使用します。

attacker-inline は `front_net` 内でのみ動作し、  同じく `front_net` に接続された **WSJF付きリバースプロキシ（reverse_proxy）** を経由して  バック側の Web サーバ（victim-inline）へアクセスします。

> ⚠️ すべて **自分の管理下のマシン内の閉域環境のみ** で利用すること。  
> 外部ネットワークへの攻撃は禁止です。

---

## 🌐 ネットワーク構成（attacker 周り）

| コンテナ              | ネットワーク               | IP                            | 役割                       |
| ----------------- | -------------------- | ----------------------------- | ------------------------ |
| **attacker-inline**   | **front_net**            | **192.168.10.10**                 | **攻撃者**                     |
| reverse_proxy     | front_net / back_net | 192.168.10.30 / 192.168.20.30 | 中継点（WSJFスケジューラ）          |
| victim-inline | back_net         | 192.168.20.20             | Apache Web サーバ（攻撃対象） |
| zeek-inline       | front_net / back_net | 192.168.10.2 / 192.168.20.2   | ネットワーク監視（IDS/NIDS）       |


attacker-inline 自身は `back_net` へは直接接続されておらず、  
**reverse_proxy を経由した通信のみが victim-inline へ届く** 構成になっています。

---

## 📦 インストールされている主要ツール

### 🔹 ネットワーク基本ツール
- `iproute2`（`ip` コマンド）
- `iputils-ping`
- `net-tools`（`ifconfig` / `netstat`）
- `tcpdump`

### 🔹 攻撃用ツール
- **slowhttptest**  
  - Slowloris / Slow Headers 攻撃を生成  
- **hping3**  
  - SYN Flood / 任意 TCP パケット生成  
- **patator**  
  - SSH などの brute-force 試行ツール  
- **nmap**  
  - ポートスキャン・サービスディスカバリ  

### 🔹 テキストエディタ
- vim
- nano

---

## 🐳 コンテナ設定情報

### Dockerfile
```Dockerfile
FROM kalilinux/kali-rolling

RUN apt update && \
    apt install -y \
      iproute2 \
      iputils-ping \
      net-tools \
      tcpdump \
      slowhttptest \
      hping3 \
      patator \
      hydra \
      curl \
      nmap \
      vim \
      nano \
      && apt clean && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリ
WORKDIR /workspace
```


### docker-compose 設定

```yaml
services:
  attacker-inline:
    build: ./attacker
    container_name: attacker-inline
    cap_add:
      - NET_ADMIN
      - NET_RAW
    networks:
      front_net:
        ipv4_address: 192.168.10.10
    command: tail -f /dev/null
    volumes:
      - ./attacker/data:/workspace
```

---

## ▶️ コンテナへのアクセス
```bash
docker exec -it attacker-inline bash
```

---

## 📁 `/workspace` ディレクトリについて
* ホストの `./attacker/data/` と同期されています
* 攻撃ログ、pcap、メモ、スクリプトの格納に利用できます

例：
```pgsql
./attacker/data/
└── test1/
    ├── capture.pcap
    └── notes.txt
```

---

## 🧪 使用例（攻撃再現）
以下では、**reverse_proxy（192.168.10.30）を攻撃対象**として指定します。
reverse_proxy から victim-inline へ HTTP リクエストが中継されることを想定しています。

### ▼ 1. Ping / 疎通確認
```bash
ping 192.168.10.30
```

### ▼ 2. 正常リクエスト（HTTP GET）
```bash
curl http://192.168.10.30/
```

### ▼ 3. Slowloris（Slow Headers）攻撃
```bash
slowhttptest -c 20 -H -g -i 10 -r 20 -t GET \
  -u http://192.168.10.30/ \
  -x 24 -s 30
```
効果：
* reverse_proxy / victim-inline 側で「ヘッダを送り切らない HTTP 接続」が多数発生

* Zeek（zeek-inline）で、プロキシ前後のフローの違いを観測可能

### ▼ 4. SYN Flood 攻撃
```bash
hping3 -S --flood 192.168.10.30 -p 8080
```
効果：
* reverse_proxy の受け付ける SYN が大量に増加

* proxy 側・victim 側双方の挙動を Zeek ログで比較できる

### ▼ 5. 全ポートスキャン
```bash
nmap -sS -p- 192.168.10.30
```

---

## 🔒 注意事項
* 本環境は**Docker の internal network（front_net / back_net）上の閉域環境**で動くように設計されています。

* 絶対に外部ネットワークへ向けた攻撃に使用しないでください。

* 実験は attacker-inline・reverse_proxy・victim-inline・zeek-inline の各コンテナ間に限定してください。

---

## 📝 補足：attacker でよく使う Linux コマンド
| コマンド                                 | 用途                       |
| ------------------------------------ | ------------------------ |
| `ip a`                               | IP アドレスの確認               |
| `ip route`                           | ルーティングテーブルの確認            |
| `ss -lnt`                            | TCP LISTEN ポートの確認        |
| `tcpdump -i eth0`                    | attacker 側インタフェースのパケット観測 |
| `tcpdump -i eth0 host 192.168.10.30` | reverse_proxy との通信だけを観測  |


---

## 📌 バージョン情報
* Base image: `kalilinux/kali-rolling`

* Tools: slowhttptest / hping3 / patator / nmap / tcpdump / ping など
