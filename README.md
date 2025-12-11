# InlineDefender – Docker ベース攻撃・防御・監視実験環境
InlineDefender は、攻撃生成・Web サーバ・ネットワーク監視を**フロントネットワーク / バックネットワークの 2 層構造**で再現した Docker ベースの閉域テストベッドです。

本環境では、

* 攻撃者（attacker-inline）

* リバースプロキシ（reverse_proxy / WSJF スケジューラ実装予定）

* 被害者 Web サーバ（victim-inline / Apache）

* 監視者（zeek-inline / IDS）

の 4 要素を独立したコンテナとして構築し、DoS、Slow HTTP、スケジューリング、ネットワーク監視などのL3〜L7 レベルの挙動を安全に観測できるように設計されています。

> ※ すべて 自分の管理下のマシンのみで使用すること。
外部ネットワークへの攻撃トラフィック送信は禁止です。

---

## 📁 ディレクトリ構成
```
InlineDefender/
├── attacker/          
│   ├── Dockerfile
│   └── data/
│
├── reverse_proxy/     
│   ├── Dockerfile
│   └── proxy.py   # 実装箇所
│
├── victim/            
│   ├── Dockerfile
│   └── data/         
│
├── zeek/
│   ├── Dockerfile   
│   ├── logs/         
│   └── scripts/       
│
└── docker-compose.yml

```


---

## 🧩 各コンテナの役割

### **attacker-inline（攻撃者クライアント）**
Kali Linux ベースの攻撃生成環境。
Slowloris、Slow Headers、SYN Flood、Brute force、スキャンなどを実行可能。

* 利用ツール：slowhttptest / hping3 / nmap / hydra など

* ネットワーク：front_net（192.168.10.10）

攻撃トラフィックは**直接 victim には届かず、reverse_proxy を経由**する。

---

### **reverse_proxy（WSJF スケジューリング付きリバースプロキシ）**
フロントネット（攻撃者側）とバックネット（Web サーバ側）を接続する中継点。

* front_net: 192.168.10.30

* back_net: 192.168.20.30

* L7 リダイレクト／負荷制御／WSJF キュー管理（実装予定）

このコンテナを通すことで、

* 攻撃トラフィック混在時の優先度制御

* victim の負荷変動の観測

* Zeek による プロキシ前後差分の解析

が可能となる。

---

### **victim-inline（被害者 Web サーバ）**
Apache HTTP Server を搭載した被害者役コンテナ。

* IP：192.168.20.20（back_net）

* /var/www/html に victim/data/ がマウントされる
→ 実験用 HTML / API / 大容量ファイルを自由に配置可能

* Slow HTTP / DoS / 同時接続枯渇などの挙動観察に利用

---

### **zeek-inline（ネットワーク監視 / IDS）**
front_net・back_net の**両方に接続された 2 ネットワーク監視用コンテナ**。

* front_net: 192.168.10.2

* back_net: 192.168.20.2

* sysctl により ip_forward=1（インライン動作も可能）

* /zeek-scripts にカスタム検知スクリプトを配置

* /zeek-logs に Zeek のログが保存される

Zeek により、

* プロキシ前後のトラフィック差

* 攻撃パターン（SYN Flood、Slowloris）

* HTTP メタデータ

などを L7 まで可視化可能。

---

## 🌐 Docker ネットワーク構成

本環境では **2 つの独立した内部ネットワーク**を使用します：

**front_net（攻撃者側）**
| コンテナ            | IP            |
| --------------- | ------------- |
| attacker-inline | 192.168.10.10 |
| reverse_proxy   | 192.168.10.30 |
| zeek-inline     | 192.168.10.2  |

**back_net（被害者側）**
| コンテナ          | IP            |
| ------------- | ------------- |
| victim-inline | 192.168.20.20 |
| reverse_proxy | 192.168.20.30 |
| zeek-inline   | 192.168.20.2  |

※ すべて internal: true のため外部インターネットには出られず、完全閉域で安全に攻撃・防御の挙動分析が行える。

---

## 🚀 起動方法

### 1. コンテナのビルド & 起動
```bash
docker compose up --build -d
```

### 2. 各コンテナへのアクセス
```bash
docker exec -it attacker-inline bash
docker exec -it reverse_proxy bash
docker exec -it victim-inline bash
docker exec -it zeek-inline bash
```

---

## 🔒 注意事項

- 外部ネットワークに向けた攻撃は **絶対に実行しないこと**
- この環境は **完全な閉域**（Docker の internal network）で動作する
- 学習目的であり、実運用環境への適用は推奨しない

