import socket
import time
import random
import sys

HOST = sys.argv[1] if len(sys.argv) >= 2 else "reverse-proxy"
PORT = int(sys.argv[2]) if len(sys.argv) >= 3 else 5201

'''
これは何？：「順序が分かるデータ」を意図的に流すプログラム。
0001, 0002, 0003, … みたいな連番タグを付けた小さいペイロードを、一定間隔（またはランダム間隔）で reverse_proxy に TCP で送る。
'''

def main():
    s = socket.create_connection((HOST, PORT))
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print(f"[client] connected to {HOST}:{PORT}", flush=True)

    for i in range(1, 31):
        payload = f"{i:04d} t={time.time():.6f}\n".encode()
        s.sendall(payload)
        print(f"[client] SENT: {payload.decode().rstrip()}", flush=True)
        time.sleep(random.choice([0.01, 0.02, 0.05, 0.2]))

    s.close()
    print("[client] closed", flush=True)

if __name__ == "__main__":
    main()
