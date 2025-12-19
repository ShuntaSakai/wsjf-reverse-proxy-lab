# gemini 3.0-pro に生成させたもの

import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Dict, Tuple

BACKNET_HOST = "victim-inline"
BACKNET_PORT = 80
LISTEN_HOST  = "0.0.0.0"
LISTEN_PORT  = 80

BUFFER_SIZE = 4096

# victim の「同時処理スレッド数 N」のつもり
MAX_SLOTS = 20

# 1回目が来ない接続は切る / 2回目が来ない接続も切る
FIRST_TIMEOUT  = 5.0
SECOND_TIMEOUT = 10.0

# 1回目だけ来て止まる接続が無制限に溜まるのを防ぐ pending 上限
MAX_PENDING = 200

# ヘッダ終端が来ない接続を切る
HARD_HEADER_TIMEOUT = 15.0
MAX_HEADER_BYTES = 64 * 1024

# "strict_slide" or "avg_gap"
P_MODE = "avg_gap"

RESP_503 = (
    b"HTTP/1.1 503 Service Unavailable\r\n"
    b"Connection: close\r\n"
    b"Content-Length: 0\r\n"
    b"\r\n"
)

async def send_503_and_close(writer: asyncio.StreamWriter):
    try:
        writer.write(RESP_503)
        await writer.drain()
    except Exception:
        pass
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass

def force_connection_close_on_request(buffered: bytes) -> bytes:
    """
    keep-alive だと 1 接続がスロットを占有し続けるので、
    frontend->backend のリクエストを Connection: close に強制。
    """
    try:
        head, sep, rest = buffered.partition(b"\r\n\r\n")
        if not sep:
            return buffered

        lines = head.split(b"\r\n")
        if not lines:
            return buffered

        req_line = lines[0]
        hdr_lines = lines[1:]

        new_hdr_lines = []
        has_conn = False

        for line in hdr_lines:
            if not line:
                continue
            lower = line.lower()

            if lower.startswith(b"proxy-connection:"):
                continue

            if lower.startswith(b"connection:"):
                new_hdr_lines.append(b"Connection: close")
                has_conn = True
            else:
                new_hdr_lines.append(line)

        if not has_conn:
            new_hdr_lines.append(b"Connection: close")

        new_header = b"\r\n".join([req_line] + new_hdr_lines) + b"\r\n\r\n"
        return new_header + rest
    except Exception:
        return buffered

async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        while True:
            data = await reader.read(BUFFER_SIZE)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

@dataclass
class Slot:
    conn_id: int
    P: float
    front_writer: asyncio.StreamWriter
    back_writer: Optional[asyncio.StreamWriter] = None
    tasks: Optional[Tuple[asyncio.Task, asyncio.Task]] = None

class SlotManager:
    def __init__(self, max_slots: int):
        self.max_slots = max_slots
        self.lock = asyncio.Lock()
        self.slots: Dict[int, Slot] = {}

    async def admit(self, slot: Slot) -> Tuple[bool, Optional[Slot]]:
        """
        return: (admitted, evicted_slot)
        """
        async with self.lock:
            if len(self.slots) < self.max_slots:
                self.slots[slot.conn_id] = slot
                return True, None

            worst = max(self.slots.values(), key=lambda s: s.P)

            if slot.P < worst.P:
                del self.slots[worst.conn_id]
                self.slots[slot.conn_id] = slot
                return True, worst

            return False, None

    async def update_P(self, conn_id: int, newP: float):
        # avg_gap は平均なので上下し得る。ここでは「その時点の推定P」をそのまま反映する。
        # （攻撃耐性を優先するなら max(過去P, newP) にするのもアリ）
        async with self.lock:
            s = self.slots.get(conn_id)
            if s:
                s.P = newP

    async def update_P_and_maybe_evict_self(self, conn_id: int, newP: float) -> Optional[Slot]:
        """avg_gap 用: P を更新した結果「自分が最悪(P最大)」になったら追い出し対象として返す。

        - スロットが満杯のときのみ発動（空きがあるなら追い出す必要がない）
        - 「後から P が悪化した接続を追い出す」を実現するため、返すのは **更新した接続自身** のみ
        """
        async with self.lock:
            s = self.slots.get(conn_id)
            if not s:
                return None

            s.P = newP

            if len(self.slots) < self.max_slots:
                return None

            worst = max(self.slots.values(), key=lambda x: x.P)
            if worst.conn_id == conn_id:
                return worst

            return None

    async def attach_backend(self, conn_id: int, back_writer: asyncio.StreamWriter,
                             tasks: Tuple[asyncio.Task, asyncio.Task]):
        async with self.lock:
            s = self.slots.get(conn_id)
            if s:
                s.back_writer = back_writer
                s.tasks = tasks

    async def release(self, conn_id: int):
        async with self.lock:
            slot = self.slots.pop(conn_id, None)

        if not slot:
            return

        if slot.back_writer:
            try:
                slot.back_writer.close()
                await slot.back_writer.wait_closed()
            except Exception:
                pass

        if slot.tasks:
            for t in slot.tasks:
                t.cancel()
            try:
                await asyncio.gather(*slot.tasks, return_exceptions=True)
            except Exception:
                pass

    async def evict(self, slot: Slot):
        try:
            await send_503_and_close(slot.front_writer)
        except Exception:
            pass
        await self.release(slot.conn_id)

slot_mgr = SlotManager(MAX_SLOTS)
_pending_sema = asyncio.Semaphore(MAX_PENDING)
_conn_seq = 0

async def proxy_connection(front_reader: asyncio.StreamReader,
                           front_writer: asyncio.StreamWriter):
    global _conn_seq
    _conn_seq += 1
    conn_id = _conn_seq

    # pending 上限
    try:
        await asyncio.wait_for(_pending_sema.acquire(), timeout=0.05)
    except asyncio.TimeoutError:
        await send_503_and_close(front_writer)
        return

    admitted = False
    pending_released = False

    try:
        # 1回目
        try:
            first = await asyncio.wait_for(front_reader.read(BUFFER_SIZE), FIRST_TIMEOUT)
        except asyncio.TimeoutError:
            await send_503_and_close(front_writer)
            return

        if not first:
            await send_503_and_close(front_writer)
            return

        t1 = time.monotonic()
        buffered = first

        # avg_gap 用
        t_prev = t1
        sum_gap = 0.0
        gap_cnt = 0

        evicted = None

        if P_MODE == "strict_slide":
            # 2回目が来た瞬間に P=t2-t1 を確定して判定（超厳密）
            try:
                second = await asyncio.wait_for(front_reader.read(BUFFER_SIZE), SECOND_TIMEOUT)
            except asyncio.TimeoutError:
                await send_503_and_close(front_writer)
                return

            if not second:
                await send_503_and_close(front_writer)
                return

            t2 = time.monotonic()
            buffered += second

            P = t2 - t1
            new_slot = Slot(conn_id=conn_id, P=P, front_writer=front_writer)
            admitted, evicted = await slot_mgr.admit(new_slot)
            if not admitted:
                await send_503_and_close(front_writer)
                return
            if evicted is not None:
                await slot_mgr.evict(evicted)

            _pending_sema.release()
            pending_released = True

        else:
            # ===== avg_gap: 動的に P を更新しながら運用する =====
            if b"\r\n\r\n" in buffered:
                # ヘッダが1回目だけで終わっている場合は gap が取れないので P=0 で即 admit
                P = 0.0
                new_slot = Slot(conn_id=conn_id, P=P, front_writer=front_writer)
                admitted, evicted = await slot_mgr.admit(new_slot)
                if not admitted:
                    await send_503_and_close(front_writer)
                    return
                if evicted is not None:
                    await slot_mgr.evict(evicted)

                _pending_sema.release()
                pending_released = True

            else:
                # 2回目で最初の gap が取れる → この瞬間に暫定Pで admit（置換判定）
                try:
                    second = await asyncio.wait_for(front_reader.read(BUFFER_SIZE), SECOND_TIMEOUT)
                except asyncio.TimeoutError:
                    await send_503_and_close(front_writer)
                    return

                if not second:
                    await send_503_and_close(front_writer)
                    return

                now = time.monotonic()
                buffered += second

                sum_gap += (now - t_prev)
                gap_cnt += 1
                t_prev = now

                P_est = sum_gap / gap_cnt  # = (t2-t1) と同じ
                new_slot = Slot(conn_id=conn_id, P=P_est, front_writer=front_writer)
                admitted, evicted = await slot_mgr.admit(new_slot)
                if not admitted:
                    await send_503_and_close(front_writer)
                    return
                if evicted is not None:
                    await slot_mgr.evict(evicted)

                # slot を掴めたので pending からは卒業
                _pending_sema.release()
                pending_released = True

        # ヘッダ終端まで受ける（backendにはまだ繋がない）
        header_deadline = t1 + HARD_HEADER_TIMEOUT

        while b"\r\n\r\n" not in buffered:
            if len(buffered) >= MAX_HEADER_BYTES:
                await send_503_and_close(front_writer)
                return

            remain = header_deadline - time.monotonic()
            if remain <= 0:
                await send_503_and_close(front_writer)
                return

            try:
                chunk = await asyncio.wait_for(front_reader.read(BUFFER_SIZE), remain)
            except asyncio.TimeoutError:
                await send_503_and_close(front_writer)
                return

            if not chunk:
                await send_503_and_close(front_writer)
                return

            buffered += chunk

            # avg_gap はここで「動的更新」
            if P_MODE == "avg_gap" and admitted:
                now = time.monotonic()
                sum_gap += (now - t_prev)
                gap_cnt += 1
                t_prev = now

                P_est = sum_gap / gap_cnt
                evicted_self = await slot_mgr.update_P_and_maybe_evict_self(conn_id, P_est)
                if evicted_self is not None:
                    # 自分が最悪になった = 後から P が悪化した接続を即座に追い出す
                    await slot_mgr.evict(evicted_self)
                    return

        # keep-alive 対策
        buffered = force_connection_close_on_request(buffered)

        # backend接続
        try:
            back_reader, back_writer = await asyncio.open_connection(BACKNET_HOST, BACKNET_PORT)
        except Exception:
            await send_503_and_close(front_writer)
            return

        try:
            back_writer.write(buffered)
            await back_writer.drain()
        except Exception:
            await send_503_and_close(front_writer)
            try:
                back_writer.close()
                await back_writer.wait_closed()
            except Exception:
                pass
            return

        task1 = asyncio.create_task(pipe(front_reader, back_writer))
        task2 = asyncio.create_task(pipe(back_reader, front_writer))
        await slot_mgr.attach_backend(conn_id, back_writer, (task1, task2))

        await asyncio.wait({task1, task2}, return_when=asyncio.FIRST_COMPLETED)

        for t in (task1, task2):
            if not t.done():
                t.cancel()
        try:
            await asyncio.gather(task1, task2, return_exceptions=True)
        except Exception:
            pass

        try:
            front_writer.close()
            await front_writer.wait_closed()
        except Exception:
            pass

        try:
            back_writer.close()
            await back_writer.wait_closed()
        except Exception:
            pass

    finally:
        if admitted:
            await slot_mgr.release(conn_id)
        if not pending_released:
            _pending_sema.release()

async def main():
    server = await asyncio.start_server(proxy_connection, LISTEN_HOST, LISTEN_PORT)
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
