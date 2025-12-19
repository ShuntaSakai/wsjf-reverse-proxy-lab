FROM kalilinux/kali-rolling

RUN apt update && \
    apt install -y \
      iproute2 \
      iputils-ping \
      net-tools \
      tcpdump \
      slowhttptest \
      hping3 \
      patator \
      hydra \
      curl \
      nmap \
      vim \
      nano \
      iperf3 \
      && apt clean && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリ
WORKDIR /workspace

# ルーティング設定
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
