import socket, time, random, sys, os

HOST = sys.argv[1] if len(sys.argv) >= 2 else os.getenv("HOST", "reverse_proxy")
PORT = int(sys.argv[2]) if len(sys.argv) >= 3 else int(os.getenv("PORT", "5201"))

MODE = os.getenv("MODE", "mid")   # fast / mid / slow
CID  = os.getenv("CID", "X")  # 2文字（F1/S2 など）

COUNT = int(os.getenv("COUNT", "30"))
PRESET = {
    "fast": {"min_sleep": 0.02, "max_sleep": 0.05, "pad": 2000}, # "min_sleep": 0.001, "max_sleep": 0.005, "pad": 2000
    "mid":  {"min_sleep": 0.01,  "max_sleep": 0.2,   "pad": 0},
    "slow": {"min_sleep": 0.2,   "max_sleep": 0.5,   "pad": 0},
}
if MODE not in PRESET:
    print("MODE must be fast|mid|slow")
    sys.exit(1)

cfg = PRESET[MODE]
pad = b"x" * cfg["pad"]

def main():
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

if __name__ == "__main__":
    main()
