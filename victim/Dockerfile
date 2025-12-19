FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt update && \
    apt install -y \
      apache2 \
      iproute2 \
      iputils-ping \
      net-tools \
      iptables \
      tcpdump \
      less \
      vim \
      nano \
      && apt clean && rm -rf /var/lib/apt/lists/*

RUN echo "ServerName victim" >> /etc/apache2/apache2.conf

#Apacheの防御機能を有効化
RUN a2enmod reqtimeout

# HTTP ポート
EXPOSE 80

# コンテナ起動と同時に Apache をフォアグラウンド起動(止めずに)
CMD ["/usr/sbin/apache2ctl", "-D", "FOREGROUND"]

WORKDIR /workspace

# ルーティング設定
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
