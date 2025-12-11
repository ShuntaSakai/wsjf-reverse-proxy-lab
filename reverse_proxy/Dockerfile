FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Tokyo

# タイムゾーン設定
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tzdata \
        iproute2 \
        net-tools \
        tcpdump \
    && ln -sf /usr/share/zoneinfo/Asia/Tokyo /etc/localtime \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリ
WORKDIR /app

# プロキシコード（後で作成）
COPY . /app

# デフォルトコマンド
CMD ["python3", "proxy.py"]
