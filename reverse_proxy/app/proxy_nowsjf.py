import asyncio
import os
import time
from collections import deque

# ===== config =====
BACKNET_HOST = os.getenv("BACKNET_HOST", "seq-server")
BACKNET_PORT = int(os.getenv("BACKNET_PORT", "5201"))

LISTEN_HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "5201"))

BUFFER_SIZE = int(os.getenv("BUFFER_SIZE", "4096"))

# 送信前に必ず入れる遅延（秒）
SEND_DELAY_SEC = float(os.getenv("SEND_DELAY_SEC", "0.05"))

# ===== Global FIFO queue (shared by ALL connections) =====
# “queue.queue” を通す = この deque が実体（FIFO）
queue_queue: deque = deque()
queue_cv = asyncio.Condition()

# logging / seq
seq_state = {"v": 0}
seq_lock = asyncio.Lock()

active_sessions = {}  # {peername: session_obj}


class ConnectionSession:
    def __init__(self, client_info):
        self.client_info = client_info
        self.start_time = time.time()
        self.total_bytes = 0
        self.last_score = 0.0  # 互換用に残す（WSJFでは未使用）

    def update_score(self):
        duration = time.time() - self.start_time
        if duration < 0.1:
            duration = 0.1
        bps = (self.total_bytes * 8) / duration
        self.last_score = 1.0 / (bps + 1.0)
        return self.last_score


def parse_tag_cid(line: bytes):
    parts = line.split(b" ", 2)
    tag = parts[0].decode(errors="ignore") if len(parts) >= 1 else "????"
    cid = parts[1].decode(errors="ignore") if len(parts) >= 2 else "?"
    return tag, cid


def qsize() -> int:
    return len(queue_queue)


async def q_put(item):
    async with queue_cv:
        queue_queue.append(item)
        queue_cv.notify()


async def q_put_front(item):
    async with queue_cv:
        queue_queue.appendleft(item)
        queue_cv.notify()


async def q_get():
    async with queue_cv:
        while not queue_queue:
            await queue_cv.wait()
        return queue_queue.popleft()


async def connect_backnet_forever():
    while True:
        try:
            r, w = await asyncio.open_connection(BACKNET_HOST, BACKNET_PORT)
            print(f"[backnet] connected to {BACKNET_HOST}:{BACKNET_PORT}")
            return r, w
        except Exception as e:
            print(f"[backnet] connect failed: {e!r} (retry in 1s)")
            await asyncio.sleep(1)


async def backnet_drain_task(back_reader: asyncio.StreamReader):
    try:
        while True:
            data = await back_reader.read(BUFFER_SIZE)
            if not data:
                break
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[backnet_drain] error: {e!r}")


async def sender_loop():
    """
    ★ backend 接続は1本だけ
    ★ FIFO キューから取り出して順に送る
    ★ 送信前に SEND_DELAY_SEC を必ず入れる
    """
    back_reader, back_writer = await connect_backnet_forever()
    drain_task = asyncio.create_task(backnet_drain_task(back_reader))

    while True:
        seq, line, session, tag, cid, msg_bytes = await q_get()
        try:
            # 遅延（ここが「backend に送る前」の統一遅延ポイント）
            if SEND_DELAY_SEC > 0:
                await asyncio.sleep(SEND_DELAY_SEC)

            print(
                f"[Scheduler] tag={tag} cid={cid} pri=0.000000 "
                f"seq={seq} qsize={qsize()} bytes={msg_bytes}"
            )

            back_writer.write(line)
            await back_writer.drain()

        except Exception as e:
            print(f"[Scheduler] backnet write failed: {e!r}")

            # 送れなかった分は FIFO を壊さないため先頭に戻す
            await q_put_front((seq, line, session, tag, cid, msg_bytes))

            # 再接続
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


async def client_to_queue(front_reader: asyncio.StreamReader, session: ConnectionSession):
    """
    front から1行ずつ読み → FIFO キュー(queue_queue)へ投入
    """
    try:
        while True:
            try:
                line = await front_reader.readuntil(b"\n")
            except asyncio.IncompleteReadError:
                break

            if not line:
                break

            msg_bytes = len(line)
            session.total_bytes += msg_bytes
            session.update_score()  # monitor用

            tag, cid = parse_tag_cid(line)

            async with seq_lock:
                seq_state["v"] += 1
                seq = seq_state["v"]

            # Enqueueログ（qsizeは put 前/後どっちでも良いが、ここは put 前の値）
            print(
                f"[Enqueue]  tag={tag} cid={cid} pri=0.000000 bytes={msg_bytes} "
                f"seq={seq} from {session.client_info}"
            )

            await q_put((seq, line, session, tag, cid, msg_bytes))

    except Exception as e:
        print(f"[client_to_queue] error: {e!r}")


async def proxy_connection(front_reader: asyncio.StreamReader, front_writer: asyncio.StreamWriter):
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


async def monitor_task():
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


async def main():
    # 送信側ループ（backend 1本 + FIFO）
    asyncio.create_task(sender_loop())

    # optional
    asyncio.create_task(monitor_task())

    server = await asyncio.start_server(proxy_connection, host=LISTEN_HOST, port=LISTEN_PORT)
    addr = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    print(f"[proxy] listening on {addr} (SEND_DELAY_SEC={SEND_DELAY_SEC})")

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
