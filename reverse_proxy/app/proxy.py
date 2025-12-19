import asyncio # 処理を並行処理するためのライブラリ（参考記事：https://qiita.com/automation2025/items/797c23a7655898f61e7d (第8章)）

BACKNET_HOST = "victim-inline"  # back_net 側のホスト名（Docker の内部 DNS でコンテナ間から名前解決できる）
BACKNET_PORT = 80               # Apache 側のリッスンポート
LISTEN_HOST  = "0.0.0.0"        # front_net 側で待ち受け（全てのインターフェース）
LISTEN_PORT  = 80               # attacker がアクセスするポート

BUFFER_SIZE = 4096              # 一度に読み込む最大バイト数              

"""
attackerとvictim間の双方向パイプの片側処理（非同期関数）

param reader: asyncio.StreamReader データを読む側
param writer: asyncio.StreamWriter データを書き込む側
"""
async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter): # (ストリームに関する参考文献：https://docs.python.org/ja/3/library/asyncio-stream.html)
    try:
        # 無限ループ（通信が続く限り）
        while True:
            data = await reader.read(BUFFER_SIZE) # reader から最大 BUFFER_SIZE バイト読み取る（データが来るまでは非同期的に（ブロッキングではない）待機）
            if not data:
                # 相手側が close した
                break
            writer.write(data) # writer にデータを書き込む
            await writer.drain() # 書き込みが完了するまで非同期的に（ブロッキングではない）待機
    except Exception as e:
        print(f"[pipe] error: {e}") # ループの途中でエラーが発生したらここで握り潰す
    finally:
        # 書き込み側を閉じる（片方向の終了）
        writer.close() 

"""
attacker からの新規接続を処理（非同期関数）
victim-inline:80 に接続して、双方向にパイプする。
"""
async def proxy_connection(front_reader: asyncio.StreamReader,
                        front_writer: asyncio.StreamWriter):
    front_info = front_writer.get_extra_info("peername") # 接続元情報を取得
    print(f"[proxy] new connection from {front_info}")

    try:
        back_reader, back_writer = await asyncio.open_connection(
            BACKNET_HOST, BACKNET_PORT # ここで back_net 側のコンテナに TCP 接続を張る
        )
    except Exception as e:
        print(f"[proxy] failed to connect backnet: {e}")
        front_writer.close()
        return

    # front -> back, back -> front を並列に動かす
    task1 = asyncio.create_task(pipe(front_reader, back_writer)) # front_net（attacker）から来たデータを backnet（victim）に流す
    task2 = asyncio.create_task(pipe(back_reader, front_writer)) # backnet（victim）から来たデータを front_net（attacker）に流す

    # どちらかが終わるまで待つ
    await asyncio.wait({task1, task2}, return_when=asyncio.FIRST_COMPLETED)

    # 片方が終わったら、残りのタスクもキャンセル
    for t in (task1, task2):
        if not t.done():
            t.cancel()

    print(f"[proxy] connection from {front_info} closed")


async def main():
    #TCPサーバーを起動
    #新しい接続が来るたびに proxy_connection が呼ばれる。
    server = await asyncio.start_server(
        proxy_connection,
        host=LISTEN_HOST,
        port=LISTEN_PORT,
    )

    addr = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    print(f"[proxy] listening on {addr}") # プロキシがどのアドレスで listen しているか

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
