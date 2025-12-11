# victim コンテナ（Ubuntu + Apache2／バック側 Web サーバ）
本コンテナは**バック側ネットワーク（back_net）**に配置された Apache Web サーバで、攻撃者（attacker-inline）からの HTTP リクエスト・DoS・Slowloris などの攻撃を**reverse_proxy（WSJF スケジューラ付きリバースプロキシ）を経由して受信する**役割を持ちます。

コンテナは外部ネットワークへは接続されず、`back_net` のみに参加することで完全な閉域環境で安全に攻撃挙動を観察できます。

---

## 🌐 ネットワーク構成（victim 周り）

| コンテナ              | ネットワーク               | IP                            | 役割                       |
| ----------------- | -------------------- | ----------------------------- | ------------------------ |
| attacker-inline   | front_net            | 192.168.10.10                 | 攻撃者                      |
| reverse_proxy     | front_net / back_net | 192.168.10.30 / 192.168.20.30 | 中継点（WSJFスケジューラ）          |
| **victim-inline** | **back_net**         | **192.168.20.20**             | **Apache Web サーバ（攻撃対象）** |
| zeek-inline       | front_net / back_net | 192.168.10.2 / 192.168.20.2   | ネットワーク監視（IDS/NIDS）       |

attacker は victim へ直接到達できず、**すべての HTTP リクエストは reverse_proxy → victim-inline**へ転送されます。

これにより、

* プロキシ前後のトラフィック差分

* WSJF による優先度制御の効果

* victim のスレッド枯渇や遅延挙動

などを安全に観測できます。

---

## 📦 インストールされている主要パッケージ

### 🔹 ネットワーク基本ツール
- `iproute2`
- `iputils-ping`
- `net-tools`
- `tcpdump`

### 🔹 Web サーバ（メイン）
- `Apache2（mpm_event）`  
  - 本コンテナ起動時に自動で開始
  - `apache2ctl -D FOREGROUND` でフォアグラウンド起動

### 🔹 テキストエディタ
- vim  
- nano

---

## 🐳 コンテナ設定情報

### Dockerfile
```Dockerfile
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt update && \
    apt install -y \
      apache2 \
      iproute2 iputils-ping net-tools \
      iptables tcpdump \
      less vim nano \
      && apt clean && rm -rf /var/lib/apt/lists/*

RUN echo "ServerName victim" >> /etc/apache2/apache2.conf
RUN a2enmod reqtimeout

EXPOSE 80
CMD ["/usr/sbin/apache2ctl", "-D", "FOREGROUND"]

WORKDIR /workspace
```

### docker-compose 設定

```yaml
victim-inline:
  build: ./victim
  container_name: victim-inline
  cap_add:
    - NET_ADMIN
    - NET_RAW
  networks:
    back_net:
      ipv4_address: 192.168.20.20
  command: apachectl -D FOREGROUND
  volumes:
    - ./victim/data:/var/www/html
```

---

## ▶️ コンテナへのアクセス
```bash
docker exec -it victim-inline bash
```

---

## 📁 `/workspace` ディレクトリについて
* ホストの `./victim_apache/data/` と同期されています
* Apache のログ保存、HTML 配置、テストスクリプトなどに使用可能

例：
```pgsql
./victim/data/
└── html/
    ├── index.html
    └── test.json
```

* ここに置いたファイルが victim-inline 上の /var/www/html として公開されます。

* reverse_proxy → victim-inline の L7 実験で便利。

---

## 🧪 使用例

### ▼ 1. Apache の状態確認
**Apache が起動しているか**
```bash
ps aux | grep apache2
```
**ポート 80 が LISTEN しているか**
```bash
ss -lntp | grep :80
```

### ▼ 2. Apache の再起動方法
```bash
apache2ctl restart
```

### ▼ 3. Apache のスレッド数（MPM event）の変更方法
**設定ファイルの場所**
```bash
/etc/apache2/mods-available/mpm_event.conf
```
編集：
```bash
nano /etc/apache2/mods-available/mpm_event.conf
```
**設定項目（例）**
```apache
<IfModule mpm_event_module>
    StartServers             2
    MinSpareThreads         25
    MaxSpareThreads         75
    ThreadLimit             64
    ThreadsPerChild         25
    MaxRequestWorkers      150
    MaxConnectionsPerChild   0
</IfModule>
```
重要パラメータ：

| パラメータ                 | 説明                                       |
| --------------------- | ---------------------------------------- |
| **ThreadsPerChild**   | 子プロセスごとのスレッド数                            |
| **MaxRequestWorkers** | 同時処理できる最大スレッド数（ThreadsPerChild × 子プロセス数） |
| **ThreadLimit**       | ThreadsPerChild の上限値                     |


**スレッド数変更後は、サーバの再起動（▼ 2. Apache の再起動方法）を行う**

### ▼ 4. Apache のログ確認
**アクセスログ**
```pgsql
/var/log/apache2/access.log
```
**エラーログ**
```lua
/var/log/apache2/error.log
```

### ▼ 5. tcpdump によるトラフィック収集
```bash
tcpdump -i eth0 -w /workspace/capture.pcap
```
* reverse_proxy → victim の実際のフローを観察可能
* Zeek や Wireshark で解析可能。

---

## 🔒 注意事項
* victim-inline は攻撃を受けるために設計されたコンテナです。
攻撃ツールをインストールしないことを推奨します。

* Apache の設定を緩めすぎるとコンテナがフリーズする可能性があります。
設定実験を行う際は注意してください。

* `back_net` のみへ接続しており外部へ露出しません。

---

## 📝 補足：よく使う Linux / Apache コマンド
| コマンド                                 | 用途                  |
| ------------------------------------ | ------------------- |
| `ss -lnt`                            | LISTEN 中の TCP ポート確認 |
| `ps aux`                             | プロセス確認              |
| `apache2ctl restart`                 | Apache の再起動         |
| `apache2ctl configtest`              | 設定ファイルの構文チェック       |
| `grep -R`                            | 設定の検索               |
| `tail -f /var/log/apache2/error.log` | エラーログ監視             |


---

## 📌 バージョン情報
* Base image: `ubuntu:22.04`

* Tools: tcpdump / ping / vim / nano など

* Apache MPM: event


