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
      && apt clean && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリ
WORKDIR /workspace

# CMD: コンテナ起動時にルーティング設定を実行し、その後コンテナを維持する
CMD ["/bin/bash", "-c", "route add default gw 192.168.10.2 || (echo 'Routing failed, check Zeek IP' && false) ; tail -f /dev/null"]
