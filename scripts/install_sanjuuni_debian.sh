#!/usr/bin/env bash
set -euo pipefail

SANJUUNI_REPO_URL="https://github.com/MCJack123/sanjuuni.git"
SANJUUNI_DIR="${SANJUUNI_DIR:-/opt/sanjuuni}"

echo "Installing build dependencies (Debian/Ubuntu)..."
sudo apt-get update
sudo apt-get install -y \
  build-essential \
  git \
  pkg-config \
  zlib1g-dev \
  libpoco-dev \
  libavcodec-dev \
  libavformat-dev \
  libavutil-dev \
  libswscale-dev \
  libswresample-dev \
  ocl-icd-opencl-dev

if [ ! -d "$SANJUUNI_DIR/.git" ]; then
  echo "Cloning sanjuuni into $SANJUUNI_DIR"
  sudo git clone "$SANJUUNI_REPO_URL" "$SANJUUNI_DIR"
else
  echo "Sanjuuni repo already exists at $SANJUUNI_DIR"
fi

echo "Building sanjuuni..."
cd "$SANJUUNI_DIR"
sudo ./configure
sudo make -j"$(nproc)"

echo "Done. Add this to your environment if needed:"
echo "  export SANJUUNI_PATH=$SANJUUNI_DIR/sanjuuni"
