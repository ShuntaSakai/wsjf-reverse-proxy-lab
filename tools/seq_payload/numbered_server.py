import socket
import time

HOST = "0.0.0.0"
PORT = 5201

def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(1)
    print(f"[server] listening on {HOST}:{PORT}", flush=True)

    conn, addr = s.accept()
    print(f"[server] accepted: {addr}", flush=True)

    buf = b""
    while True:
        data = conn.recv(4096)
        if not data:
            break
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            ts = time.time()
            print(f"[server] {ts:.6f} RECV: {line.decode(errors='replace')}", flush=True)

    print("[server] connection closed", flush=True)

if __name__ == "__main__":
    main()
