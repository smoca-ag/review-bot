FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Install systemd, build essentials, common utilities, and language runtimes
RUN apt-get update && apt-get install -y \
    systemd systemd-sysv \
    curl wget git git-lfs jq unzip \
    build-essential \
    sqlite3 libsqlite3-dev zlib1g-dev libssl-dev libreadline-dev libyaml-dev \
    python3 python3-pip python3-venv \
    ruby-full \
    default-jdk maven \
    golang-go \
    php-cli \
    poppler-utils \
    ripgrep \
    postgresql postgresql-16-postgis-3 \
    && gem install rails bundler 

# Install current stable Node.js LTS from NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y nodejs \
    && corepack enable 

# Configure git
RUN git config --global --add safe.directory /workspace

# RTK (Qwen3.8-Flash-Next likes it). Pinned to a release with digests baked
# into this file; the old curl-from-master | sh pipe let any push to the
# upstream repo run arbitrary code as root at build time. Bump RTK_VERSION
# and update both digests from https://github.com/rtk-ai/rtk/releases
ARG RTK_VERSION=v0.49.0
RUN set -eu; \
    case "$(uname -m)" in \
        x86_64) \
            RTK_ASSET=rtk-x86_64-unknown-linux-musl.tar.gz; \
            RTK_SHA256=7278231dfd7e6a730a4ab7f847b195bcf02289c2d57622b0dab75a6411100c8f ;; \
        aarch64) \
            RTK_ASSET=rtk-aarch64-unknown-linux-gnu.tar.gz; \
            RTK_SHA256=c8ea4b6560841e73157c134fd4a3293914c6ede42e786ee985cf491fde691ba7 ;; \
        *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    wget -q "https://github.com/rtk-ai/rtk/releases/download/${RTK_VERSION}/${RTK_ASSET}" -O /tmp/rtk.tar.gz; \
    echo "${RTK_SHA256}  /tmp/rtk.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/rtk.tar.gz -C /usr/local/bin; \
    chmod +x /usr/local/bin/rtk; \
    rm /tmp/rtk.tar.gz; \
    rtk --version

# Additional Ruby versions via rbenv (projects pin Gemfile rubies newer than
# system 3.2; repos with a .ruby-version select these automatically).
ENV RBENV_ROOT=/opt/rbenv
ENV PATH="$RBENV_ROOT/bin:$RBENV_ROOT/shims:$PATH"
RUN git clone https://github.com/rbenv/rbenv.git $RBENV_ROOT \
    && git clone https://github.com/rbenv/ruby-build.git $RBENV_ROOT/plugins/ruby-build \
    && $RBENV_ROOT/plugins/ruby-build/bin/ruby-build 3.4.10 $RBENV_ROOT/versions/3.4.10 \
    && $RBENV_ROOT/plugins/ruby-build/bin/ruby-build 4.0.2 $RBENV_ROOT/versions/4.0.2 \
    && rbenv rehash

# Android SDK
ENV ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk
ENV PATH="$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools"

RUN mkdir -p $ANDROID_HOME/cmdline-tools && \
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip -O /tmp/cmdline-tools.zip && \
    unzip /tmp/cmdline-tools.zip -d $ANDROID_HOME/cmdline-tools && \
    mv $ANDROID_HOME/cmdline-tools/cmdline-tools $ANDROID_HOME/cmdline-tools/latest && \
    rm /tmp/cmdline-tools.zip && \
    yes | $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --licenses && \
    $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager \
        "platform-tools" \
        "platforms;android-34" \
        "build-tools;34.0.0" \
        "ndk;26.1.10909125"

# Install gradle
RUN wget -q https://services.gradle.org/distributions/gradle-8.10.2-bin.zip -O /tmp/gradle.zip && \
    unzip /tmp/gradle.zip -d /opt && \
    rm /tmp/gradle.zip
ENV PATH="$PATH:/opt/gradle-8.10.2/bin"

# Start Postgres (agents create test databases themselves, e.g.
# `su postgres -c createdb bcp_backend_test`)
RUN systemctl enable postgresql

# Systemd needs this to run in a container correctly
STOPSIGNAL SIGRTMIN+3

# Reset journald's capability bounding set so it can start in the container
# (the tilde form grants journald everything the container itself holds).
RUN mkdir -p /etc/systemd/system/systemd-journald.service.d \
    && printf '[Service]\nCapabilityBoundingSet=~\nAmbientCapabilities=\n' \
    > /etc/systemd/system/systemd-journald.service.d/override.conf

# Forward journal output to the container console so it is visible via
# `podman logs <container>` from the host.
RUN mkdir -p /etc/systemd/journald.conf.d \
    && printf '[Journal]\nForwardToConsole=yes\nMaxLevelConsole=info\nTTYPath=/dev/console\n' \
    > /etc/systemd/journald.conf.d/forward-console.conf

CMD ["/lib/systemd/systemd"]
