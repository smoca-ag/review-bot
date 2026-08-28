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
    && gem install rails bundler \
    && rm -rf /var/lib/apt/lists/*

# Install current stable Node.js LTS from NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y nodejs \
    && corepack enable \
    && rm -rf /var/lib/apt/lists/*

# Configure git
RUN git config --global --add safe.directory /workspace

# RTK (Qwen3.8-Flash-Next likes it)

RUN RTK_INSTALL_DIR=/usr/local/bin curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh

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

CMD ["/lib/systemd/systemd"]
