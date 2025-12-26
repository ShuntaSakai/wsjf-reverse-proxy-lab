import socket
import time
import threading

HOST = "0.0.0.0"
PORT = 5201

# 複数スレッドからの print が混ざらないようにする
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

                # 期待フォーマット例: "0001 F t=... ...."
                parts = line.split(b" ", 2)
                tag = parts[0].decode(errors="replace") if len(parts) >= 1 else "????"
                cid = parts[1].decode(errors="replace") if len(parts) >= 2 else "?"
                ts = time.time()

                log(f"[server] {ts:.6f} addr={addr} RECV tag={tag} cid={cid} len={len(line)}")
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
