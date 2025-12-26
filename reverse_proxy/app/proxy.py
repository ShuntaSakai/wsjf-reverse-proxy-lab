import asyncio
import time

# test backend
BACKNET_HOST = "seq-server"
BACKNET_PORT = 5201

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 5201

BUFFER_SIZE = 4096

# ===== Global shared state (ALL connections share this) =====
scheduling_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
seq_state = {"v": 0}            # global sequence for tie-break
seq_lock = asyncio.Lock()       # protect seq_state
active_sessions = {}            # {peername: session_obj}


class ConnectionSession:
    """接続ごとのセッション情報を管理するクラス"""
    def __init__(self, client_info):
        self.client_info = client_info
        self.start_time = time.time()
        self.total_bytes = 0
        self.last_score = 0.0

    def get_priority_score(self):
        # 優先度指標 = bits/sec（bpsが大きいほど score は小さくなる）
        duration = time.time() - self.start_time
        if duration < 0.1:
            duration = 0.1
        bps = (self.total_bytes * 8) / duration
        self.last_score = 1.0 / (bps + 1.0)
        return self.last_score


async def monitor_task():
    """1秒おきに現在の接続スコアを一覧表示する(デバッグ用)"""
    while True:
        await asyncio.sleep(1)
        if not active_sessions:
            continue

        print("\n" + "=" * 70)
        print(f"{'Client Address':<25} | {'Score':<12} | {'TotalBytes':<10}")
        print("-" * 70)
        for addr, session in list(active_sessions.items()):
            print(f"{str(addr):<25} | {session.last_score:<12.6f} | {session.total_bytes:<10}")
        print("=" * 70 + "\n")


def parse_tag_cid(line: bytes):
    # 期待フォーマット: b"0001 F t=..."
    parts = line.split(b" ", 2)
    tag = parts[0].decode(errors="ignore") if len(parts) >= 1 else "????"
    cid = parts[1].decode(errors="ignore") if len(parts) >= 2 else "?"
    return tag, cid


async def client_to_queue(reader: asyncio.StreamReader,
                          session: ConnectionSession):
    """
    front(クライアント)から readuntil('\n') で 1行単位に読み、
    グローバル優先度キューに入れる
    """
    try:
        while True:
            try:
                line = await reader.readuntil(b"\n")
            except asyncio.IncompleteReadError:
                break

            if not line:
                break

            session.total_bytes += len(line)
            priority = session.get_priority_score()

            tag, cid = parse_tag_cid(line)
            print(f"[Enqueue]  tag={tag} cid={cid} pri={priority:.6f} from {session.client_info}")

            async with seq_lock:
                seq_state["v"] += 1
                seq = seq_state["v"]

            # PriorityQueue: (priority, seq, data, session)
            await scheduling_queue.put((priority, seq, line, session))

    except Exception as e:
        print(f"[client_to_queue] error: {e!r}")


async def connect_backnet_forever():
    """バックエンドへ 1 本だけ接続し続ける（切れたら再接続）"""
    while True:
        try:
            r, w = await asyncio.open_connection(BACKNET_HOST, BACKNET_PORT)
            print(f"[backnet] connected to {BACKNET_HOST}:{BACKNET_PORT}")
            return r, w
        except Exception as e:
            print(f"[backnet] connect failed: {e!r} (retry in 1s)")
            await asyncio.sleep(1)


async def backnet_drain_task(back_reader: asyncio.StreamReader):
    """
    back -> proxy の読み取り（デモでは捨てる）
    ※HTTP等でレスポンスを返す用途では、ここは設計から作り直しが必要
    """
    try:
        while True:
            data = await back_reader.read(BUFFER_SIZE)
            if not data:
                break
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[backnet_drain] error: {e!r}")


async def scheduler_loop():
    """
    グローバル優先度キューから取り出して、バックエンド1本へ送る
    （priority が小さいほど先）
    """
    back_reader, back_writer = await connect_backnet_forever()
    drain_task = asyncio.create_task(backnet_drain_task(back_reader))

    while True:
        priority, seq, data, session = await scheduling_queue.get()
        try:
            # デモ用：少し遅らせる（並び替えが見えやすい）
            await asyncio.sleep(0.05)

            tag, cid = parse_tag_cid(data)
            print(f"[Scheduler] tag={tag} cid={cid} pri={priority:.6f} seq={seq} qsize={scheduling_queue.qsize()}")

            try:
                back_writer.write(data)
                await back_writer.drain()
            except Exception as e:
                print(f"[Scheduler] backnet write failed: {e!r}")

                # 送れなかった分は「捨てずに戻す」(先頭へ戻すのは難しいので同priorityで再投入)
                await scheduling_queue.put((priority, seq, data, session))

                # 接続張り直し
                try:
                    drain_task.cancel()
                except Exception:
                    pass
                try:
                    back_writer.close()
                    await back_writer.wait_closed()
                except Exception:
                    pass

                back_reader, back_writer = await connect_backnet_forever()
                drain_task = asyncio.create_task(backnet_drain_task(back_reader))

        finally:
            scheduling_queue.task_done()


async def proxy_connection(front_reader: asyncio.StreamReader,
                           front_writer: asyncio.StreamWriter):
    """
    新規クライアント接続：
      front -> (global WSJF queue) -> back(1本)
    """
    front_info = front_writer.get_extra_info("peername")
    session = ConnectionSession(front_info)
    active_sessions[front_info] = session
    print(f"[proxy] new connection from {front_info}")

    task = None
    try:
        task = asyncio.create_task(client_to_queue(front_reader, session))
        await task
    except Exception as e:
        print(f"[proxy] error: {e!r}")
    finally:
        active_sessions.pop(front_info, None)
        try:
            front_writer.close()
            await front_writer.wait_closed()
        except Exception:
            pass
        print(f"[proxy] Closed connection: {front_info}")


async def main():
    asyncio.create_task(monitor_task())
    asyncio.create_task(scheduler_loop())  # ★全接続共通スケジューラ1個

    server = await asyncio.start_server(proxy_connection, host=LISTEN_HOST, port=LISTEN_PORT)
    addr = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    print(f"[proxy] listening on {addr}")

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
