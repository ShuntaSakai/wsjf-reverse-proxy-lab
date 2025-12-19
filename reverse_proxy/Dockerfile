FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Tokyo

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tzdata \
        iproute2 \
        net-tools \
        tcpdump \
    && ln -sf /usr/share/zoneinfo/Asia/Tokyo /etc/localtime \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

#コンテナ内の作業フォルダ決定(cdも勝手に行われる)
WORKDIR /app

#プログラムを作業場所にコピー
COPY . /app

CMD ["python3", "proxy.py"]

# ルーティング設定
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
