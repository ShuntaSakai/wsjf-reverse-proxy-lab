import asyncio # 処理を並行処理するためのライブラリ（参考記事：https://qiita.com/automation2025/items/797c23a7655898f61e7d (第8章)）
import time # 時刻取得用

BACKNET_HOST = "victim-inline"  # back_net 側のホスト名（Docker の内部 DNS でコンテナ間から名前解決できる）
BACKNET_PORT = 80               # Apache 側のリッスンポート
LISTEN_HOST  = "0.0.0.0"        # front_net 側で待ち受け（全てのインターフェース）
LISTEN_PORT  = 80               # attacker がアクセスするポート

BUFFER_SIZE = 4096              # 一度に読み込む最大バイト数              

scheduling_queue = asyncio.PriorityQueue() # 全接続のデータを管理する優先度付きキュー(値の小さい順に取り出す)
active_sessions = {} # 現在アクティブな接続セッションを管理する辞書 {peername: session_obj}

class ConnectionSession: 
    """ 接続ごとのセッション情報を管理するクラス """
    def __init__(self, client_info):
        self.client_info = client_info
        self.start_time = time.time()
        self.total_bytes = 0
        self.last_score = 0.0

    def get_priority_score(self): # 優先度指標 = bits/sec
        duration = time.time() - self.start_time
        if duration < 0.1:
            duration = 0.1  # 0除算防止

        bps = (self.total_bytes * 8) / duration  # ビット毎秒に変換
        self.last_score = 1.0 / (bps + 1.0) # bpsが大きいほどスコアが小さくなる（優先度が高くなる）

        return self.last_score # bpsが大きいほどスコアが小さくなる（優先度が高くなる）

async def monitor_task():
    """1秒おきに現在の接続スコアを一覧表示する(デバッグ用)"""
    while True:
        await asyncio.sleep(1)
        if not active_sessions:
            continue
    
        print("\n" + "="*50)
        print(f"{'Client Address':<25} | {'Score (lower is better)':<20}")
        print("-" * 50)
        for addr, session in list(active_sessions.items()):
            print(f"{str(addr):<25} | {session.last_score:.6f}")
        print("="*50 + "\n")

async def client_to_queue(reader, writer, session): # 非同期関数
    """クライアント(フロント)からデータを受け取り、優先度付きキューに入れる"""
    try:
        while True:
            data = await reader.read(BUFFER_SIZE) # データが届くまで待機
            if not data:
                break
        
            session.total_bytes += len(data)
            priority = session.get_priority_score()

            # 優先度が低すぎる（スコアが高い）場合の切断ロジック
            # if (time.time() - session.start_time) > 5.0 and priority > 0.95:
            #     print(f"!!! [Guard] Terminating slow connection: {session.client_info}")
            #     break

            await scheduling_queue.put((priority, data, session)) # キューにデータを入れる(キューが満杯の場合は待機)

    except Exception as e:
        print(f"[client_to_queue] {e}")
    finally:
        writer.close()

async def scheduler_loop(back_writer):
    """キューから最も優先度が高いデータを取り出し、サーバへ送る"""
    while True:
        priority, data, session = await scheduling_queue.get() # キューにデータが入るまで非同期で待機
        try:
            print(f"[Scheduler] Sending data: Priority={priority:.6f} from {session.client_info}")
            back_writer.write(data) # データをバックに書き込む
            await back_writer.drain() # 書き込みバッファが空になるまで待機
        except Exception as e:
            print(f"[scheduler_loop] {e}")
        finally:
            scheduling_queue.task_done()

"""
attacker からの新規接続を処理（非同期関数）
victim-inline:80 に接続して、双方向にパイプする。
"""
async def proxy_connection(front_reader: asyncio.StreamReader,
                        front_writer: asyncio.StreamWriter):
    front_info = front_writer.get_extra_info("peername") # 接続元情報を取得
    session = ConnectionSession(front_info)

    active_sessions[front_info] = session
    print(f"[proxy] new connection from {front_info}")

    try:
        back_reader, back_writer = await asyncio.open_connection(
            BACKNET_HOST, BACKNET_PORT # ここで back_net 側のコンテナに TCP 接続を張る
        )
        input_task = asyncio.create_task(
            client_to_queue(front_reader, front_writer, session) # クライアントからの入力を監視してキューに入れるタスク
        )  
        sched_task = asyncio.create_task(
            scheduler_loop(back_writer) # キューからデータを取り出してバックエンドへ送るスケジューラ
        )

        async def response_pipe():
            # back -> front のデータ転送を行う関数
            # レスポンスは優先度制御なし
            while True:
                data = await back_reader.read(BUFFER_SIZE)
                if not data: break
                front_writer.write(data)
                await front_writer.drain()

        resp_task = asyncio.create_task(response_pipe())

        await asyncio.wait({input_task, resp_task}, return_when=asyncio.FIRST_COMPLETED)

    except Exception as e:
        print(f"[proxy] failed to connect backnet: {e}")
        front_writer.close()
        return
    finally:
        active_sessions.pop(front_info, None)
        front_writer.close()
        for t in [input_task, sched_task, resp_task]:
            if not t.done():
                t.cancel()
        print(f"[proxy] Closed connection: {front_info}")
    # front -> back, back -> front を並列に動かす
    # task1 = asyncio.create_task(pipe(front_reader, back_writer)) # front_net（attacker）から来たデータを backnet（victim）に流す
    # task2 = asyncio.create_task(pipe(back_reader, front_writer)) # backnet（victim）から来たデータを front_net（attacker）に流す

    # どちらかが終わるまで待つ
    # await asyncio.wait({task1, task2}, return_when=asyncio.FIRST_COMPLETED)

    # 片方が終わったら、残りのタスクもキャンセル
    # for t in (task1, task2):
    #     if not t.done():
    #         t.cancel()

    # print(f"[proxy] connection from {front_info} closed")


async def main():
    asyncio.create_task(monitor_task())  # モニタリングタスクを起動
    server = await asyncio.start_server(
        proxy_connection,
        host=LISTEN_HOST,
        port=LISTEN_PORT,
    )

    addr = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    print(f"[proxy] listening on {addr}") # プロキシがどのアドレスで listen しているか

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())