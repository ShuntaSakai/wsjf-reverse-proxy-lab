import socket, time, random, sys, os

HOST = sys.argv[1] if len(sys.argv) >= 2 else os.getenv("HOST", "reverse_proxy")
PORT = int(sys.argv[2]) if len(sys.argv) >= 3 else int(os.getenv("PORT", "5201"))

MODE = os.getenv("MODE", "mid")   # fast / mid / slow
CID  = os.getenv("CID", "X")[:1]  # 1文字（F/S など）

COUNT = int(os.getenv("COUNT", "30"))
PRESET = {
    "fast": {"min_sleep": 0.001, "max_sleep": 0.005, "pad": 2000},
    "mid":  {"min_sleep": 0.01,  "max_sleep": 0.2,   "pad": 0},
    "slow": {"min_sleep": 0.2,   "max_sleep": 0.5,   "pad": 0},
}
if MODE not in PRESET:
    print("MODE must be fast|mid|slow")
    sys.exit(1)

cfg = PRESET[MODE]
pad = b"x" * cfg["pad"]

def normal_client():
    s = socket.create_connection((HOST, PORT))
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print(f"[client] connected to {HOST}:{PORT} mode={MODE} cid={CID}", flush=True)

    for i in range(1, COUNT + 1):
        payload = f"{i:04d} {CID} t={time.time():.6f} ".encode() + pad + b"\n"
        s.sendall(payload)
        print(f"[client] SENT: tag={i:04d} cid={CID} bytes={len(payload)}", flush=True)
        time.sleep(random.uniform(cfg["min_sleep"], cfg["max_sleep"]))

    s.close()
    print("[client] closed", flush=True)

def attacker_client():
    try:
        s = socket.create_connection((HOST, PORT))
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print(f"[Attacker] connected to {HOST}:{PORT}", flush=True)

        for i in range(9001, 9021):
            payload = f"{i:04d} t={time.time():.6f}\n".encode()
            s.sendall(payload)
            print(f"[Attacker] SENT: {payload.decode().rstrip()}", flush=True)
            time.sleep(0.8)

        s.close()
        print("[Attacker] closed", flush=True)
    except Exception as e:
        print(f"[Attacker] Exception: {e}", flush=True)

def main():
    t_attacker = threading.Thread(target=attacker_client)
    t_normal = threading.Thread(target=normal_client)

    print("攻撃者が先に接続します")
    t_attacker.start()

    time.sleep(2)
    print("通常クライアントが接続します")
    t_normal.start()

    t_attacker.join()
    t_normal.join()
    print("すべてのクライアントが終了しました")

if __name__ == "__main__":
    main()
