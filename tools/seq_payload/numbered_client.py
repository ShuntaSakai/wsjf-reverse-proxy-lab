import socket
import time
import random
import sys

# 使い方: python numbered_client.py <host> <port>
HOST = sys.argv[1] if len(sys.argv) >= 2 else "reverse-proxy"
PORT = int(sys.argv[2]) if len(sys.argv) >= 3 else 5201

def main():
    s = socket.create_connection((HOST, PORT))
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # まとめ送信を減らす
    print(f"[client] connected to {HOST}:{PORT}", flush=True)

    # 目視しやすい程度に少量、かつ間隔を揺らして priority を変動させる
    for i in range(1, 31):
        # 0001 のような固定幅 + 送信時刻も付ける（tcpdump/ログの突き合わせが楽）
        payload = f"{i:04d} t={time.time():.6f}\n".encode()
        s.sendall(payload)
        print(f"[client] SENT: {payload.decode().rstrip()}", flush=True)

        # 間隔を意図的にランダム化（遅い/速いが混ざる）
        time.sleep(random.choice([0.01, 0.02, 0.05, 0.2]))

    s.close()
    print("[client] closed", flush=True)

if __name__ == "__main__":
    main()
