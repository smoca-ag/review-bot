FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Install systemd, build essentials, common utilities, and language runtimes
RUN apt-get update && apt-get install -y \
    systemd systemd-sysv \
    curl wget git build-essential unzip \
    sqlite3 libsqlite3-dev zlib1g-dev libssl-dev libreadline-dev libyaml-dev \
    python3 python3-pip python3-venv \
    nodejs npm \
    ruby-full \
    default-jdk maven \
    && gem install rails \
    && rm -rf /var/lib/apt/lists/*

# Configure git
RUN git config --global --add safe.directory /workspace

# Systemd needs this to run in a container correctly
STOPSIGNAL SIGRTMIN+3

CMD ["/lib/systemd/systemd"]
