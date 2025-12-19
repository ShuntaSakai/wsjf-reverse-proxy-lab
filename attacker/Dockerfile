FROM kalilinux/kali-rolling

#必要なものインストール
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

#zeekで検知できないときにはルーティングを変更
ip route add 192.168.10.30 via 192.168.10.2