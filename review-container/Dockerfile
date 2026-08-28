FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Install systemd, build essentials, common utilities, and language runtimes
RUN apt-get update && apt-get install -y \
    systemd systemd-sysv \
    curl wget git build-essential unzip \
    sqlite3 libsqlite3-dev zlib1g-dev libssl-dev libreadline-dev libyaml-dev \
    python3 python3-pip python3-venv \
    ruby-full \
    default-jdk maven \
    && gem install rails \
    && rm -rf /var/lib/apt/lists/*

# Install current stable Node.js LTS from NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Configure git
RUN git config --global --add safe.directory /workspace

# RTK (Qwen3.8-Flash-Next likes it)

RUN RTK_INSTALL_DIR=/usr/local/bin curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh

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

# Systemd needs this to run in a container correctly
STOPSIGNAL SIGRTMIN+3

CMD ["/lib/systemd/systemd"]
