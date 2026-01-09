import socket
import time
import threading

HOST = "0.0.0.0"
PORT = 5201

print_lock = threading.Lock()

def log(msg: str):
    with print_lock:
        print(msg, flush=True)

def handle_conn(conn: socket.socket, addr):
    log(f"[server] accepted: {addr}")
    buf = b""
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            buf += data

            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line:
                    continue

                # 期待フォーマット:
                #   b"0001 F t=170... xxxxx..."
                # maxsplit=3 -> [tag, cid, t=..., pad...]
                parts = line.split(b" ", 3)
                tag = parts[0].decode(errors="replace") if len(parts) >= 1 else "????"
                cid = parts[1].decode(errors="replace") if len(parts) >= 2 else "?"
                tfield = parts[2].decode(errors="replace") if len(parts) >= 3 else ""
                pad_bytes = parts[3] if len(parts) >= 4 else b""
                pad_len = len(pad_bytes)

                # 受信した1行の長さ（改行除く）
                payload_no_nl = len(line)
                # 送信されたペイロード（改行含む）として数えるなら +1
                payload_bytes = payload_no_nl + 1

                # ヘッダ部（tag cid t=... まで＋pad前のスペース含む）の長さを実測
                header_len = payload_no_nl - pad_len

                ts = time.time()

                # 解析しやすいように key=value 形式で出す
                log(
                    f"{ts:.6f} [RECV] tag={tag} cid={cid} {tfield} "
                    f"bytes={payload_bytes} bytes_no_nl={payload_no_nl} header={header_len} pad={pad_len}"
                )
    except Exception as e:
        log(f"[server] error addr={addr}: {e!r}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
        log(f"[server] closed: {addr}")

def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(50)
    log(f"[server] listening on {HOST}:{PORT}")

    while True:
        conn, addr = s.accept()
        threading.Thread(target=handle_conn, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    main()
