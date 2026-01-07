# WSJF Reverse Proxy Lab（saeki/reverse-proxy-lab/tools/seq_payload）使い方・順序入れ替え検証 

`reverse_proxy` が **受信したデータ片を優先度付きキューで並び替えてバックエンドへ送信する**挙動を、**番号付きペイロード**で再現性高く検証するためのものです。

---

## 0. 何を確認したいのか（ゴール）

確認したいのは次の 2 点です。

1. `reverse_proxy` が **送信順序（back へ書き込む順）を入れ替えている**こと  
2. 入れ替えた結果が **バックエンド（seq-server）にその順で届いている**こと  

ここでは、これを確実に見るために

- `numbered_client.py`（番号付きペイロードを送る）
- `numbered_server.py`（番号を受信順に表示する）
- `docker-compose.yaml` に `seq-client` / `seq-server` を追加

しています。

---

## 1. コンポーネントの役割

### 1.1 reverse_proxy（プロキシ本体）

- クライアント（seq-client）から TCP で受け取ったデータを `PriorityQueue` に積む
- `PriorityQueue` から **優先度が小さいデータ**を先に取り出し、バックエンドへ送る
- その結果、「到着順」と「送信順」が一致しない（入れ替わる）ことがあります

### 1.2 numbered_client.py（= seq-client）

**役割：検証用の入力を作る**

- `0001`, `0002`, … の **連番タグ, tag** を含む小さな payload を
- `reverse_proxy:5201` に TCP で送る
- `SENT: 0001 ...` のように「送った順」をログに出す

### 1.3 numbered_server.py（= seq-server）

**役割：検証用の観測点（バックエンド側）**

- `0.0.0.0:5201` で待ち受ける
- 受信したデータから先頭 4 文字などの `tag` を読み、
  `RECV: 0007 ...` のように「受け取った順」をログに出す

### 1.4 docker-compose.yaml に seq-client / seq-server を追加した理由

「順序の入れ替え」を確実に検証するための **最小構成のテスト用サービス**です。

- `victim-inline`（Apache/HTTP）だと、HTTP の構造が絡んで順序確認が面倒＆壊れやすい
- `seq-client` / `seq-server` は TCP の最小構成なので、順序検証が簡単で確実

---

## 2. HOST="0.0.0.0" と PORT=5201 とは？

- `PORT=5201`：通信の「入口番号」（TCP ポート）
- `HOST="0.0.0.0"`：**このコンテナが持つ全ての IP で待ち受ける**（bind する）

つまり `seq-server` が

```py
HOST="0.0.0.0"
PORT=5201
```

なら「コンテナ内のどの IP 宛てに来ても、5201 番で受ける」という意味です。

---

## 3. まず動かす（クイックスタート）

### 3.1 起動

```bash
docker compose up --build -d
```

### 3.2 ログ（別ターミナル推奨）

```bash
# プロキシ
docker compose logs -f --tail=200 reverse_proxy

# バックエンド（受信順の観測）
docker compose logs -f --tail=200 seq-server
```

### 3.3 クライアントを流す（番号付きペイロード送信）

```bash
docker compose run --rm seq-client
```

---

## 4. 「順序が入れ替わった」ことの確認方法

順序確認は、以下 3 つのログを見ます。

1. **seq-client**：送信順（SENT）
2. **reverse_proxy**：送信順（Scheduler send）
3. **seq-server**：受信順（RECV）

### 4.1 reverse_proxy で送信順（send順）を見る

`proxy.py` の `scheduler_loop()` で、送るときに tag をログします。

```py
tag = data[:4].decode(errors="ignore")
print(f"[Scheduler] send tag={tag} pri={priority:.6f} from {session.client_info}")
```

ログ例：

```text
[Scheduler] send tag=0008 ...
[Scheduler] send tag=0011 ...
[Scheduler] send tag=0010 ...
```

### 4.2 reverse_proxy で受信順（enqueue順）も見たい場合

`client_to_queue()` 側にもログを入れると「受け取った順」と「送った順」の差が明確になります。

```py
session.total_bytes += len(data)
priority = session.get_priority_score()

tag = data[:4].decode(errors="ignore")
print(f"[Enqueue] recv tag={tag} pri={priority:.6f} from {session.client_info}")

await scheduling_queue.put((priority, data, session))
```

### 4.3 seq-server で受信順を見る

`seq-server` のログ例：

```text
RECV: 0001 ...
RECV: 0002 ...
RECV: 0005 ...
RECV: 0004 ...
```

---

## 5. 判定ルール（入れ替えたと言える条件）

### 5.1 入れ替わっていない（単調増加）

- reverse_proxy の send：`0001, 0002, 0003, 0004, ...`
- seq-server の RECV：`0001, 0002, 0003, 0004, ...`

### 5.2 入れ替わっている（単調増加でない）

- reverse_proxy の send が `... 0008, 0011, 0010, 0009, ...` のように **番号が前後**
- seq-server の RECV も同じ順で届く

このとき

- 「プロキシが send の順番を入れ替えた」
- 「その結果がバックエンドに届いた」

が示せます。

---

## 6. proxy.py の「並び替え基準」

この実装では、`ConnectionSession.get_priority_score()` により

- `bps = (total_bytes * 8) / duration`
- `score = 1 / (bps + 1)`

を計算し、その `score` を `priority` として使います。

つまり

- **bps が大きい（速い接続/速く見えるタイミング）ほど priority が小さい**
- **priority が小さいデータが先に送られる**

という基準です。

## 6. ログ解析スクリプト

`log_anaryzer.py` は `out/experiment_raw.log` を解析し、以下のグラフを生成します。
1. 各リクエストの待ち時間（Enqueue から Scheduler send まで）
2. キューサイズの推移（Scheduler イベントの qsize）
3. 各 CID ごとの待ち時間分布（ヒストグラム）

- グラフは `out/analysis_{timestamp}.png` に保存されます。

### 使い方
最初に以下のコマンドを実行して `out/experiment_raw.log` に標準出力の内容を保存します。
```bash
docker compose logs -f --tail=0 --timestamps reverse_proxy | egrep --line-buffered '\[Enqueue\]|\[Scheduler\]|\[proxy\]|\[backnet\]' | stdbuf -oL tee -a out/experiment_raw.log | stdbuf -oL perl -pe 'if(/\[Enqueue\]/){$_="\e[32m".$_}elsif(/\[Scheduler\]/){$_="\e[31m".$_}s/(cid=F)/\e[34m$1\e[39m/g;s/(cid=S)/\e[33m$1\e[39m/g;s/\n/\e[0m\n/;'
```

その後、別のターミナルで以下のような2接続シミュレーションを開始するコマンドを実行します。
```bash
stty -tostop 2>/dev/null || true

docker compose run --rm -T -e CID=F -e MODE=fast -e COUNT=600 seq-client \
python numbered_client.py </dev/null \
&
docker compose run --rm -T -e CID=S -e MODE=slow -e COUNT=60 seq-client \
python numbered_client.py </dev/null \

wait
echo "done"
```
COUNTの値が送信するペイロードの数になります。

このコマンドを実行して、ログの収集が終わったら、`log_anaryzer.py`を実行して解析を行います。
```bash
python tools/seq_payload/log_anaryzer.py
```

実行後に `out/analysis_{timestamp}.png` にグラフが保存されます。