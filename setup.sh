#!/bin/bash
set -e

# setup.sh - Setup script for Auto Sites Service
# usage: ./setup.sh

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting Auto Sites Service Setup...${NC}"

# 1. Check OS and Install System Dependencies
echo -e "${YELLOW}[1/8] Checking System Dependencies...${NC}"

if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$NAME
elif type lsb_release >/dev/null 2>&1; then
    OS=$(lsb_release -si)
else
    OS=$(uname -s)
fi

echo "Detected OS: $OS"

if [[ "$OS" == *"Fedora"* ]] || [[ "$OS" == *"Red Hat"* ]] || [[ "$OS" == *"CentOS"* ]]; then
    echo "Installing dependencies for RHEL/dFedora..."
    sudo dnf update -y
    sudo dnf install -y nss atk at-spi2-atk cups-libs libdrm mesa-libgbm \
        libXcomposite libXdamage libXext libXfixes libXrandr libxcb \
        libxkbcommon pango alsa-lib libXcursor libXi libXScrnSaver bc curl git nodejs npm
elif [[ "$OS" == *"Debian"* ]] || [[ "$OS" == *"Ubuntu"* ]]; then
    echo "Installing dependencies for Debian/Ubuntu..."
    sudo apt-get update
    sudo apt-get install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libgbm1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
        libxrandr2 libxcb1 libxkbcommon0 libpango-1.0-0 \
        libasound2 libxcursor1 libxi6 libxss1 bc curl git nodejs npm
else
    echo -e "${RED}Unsupported or unknown OS: $OS. Please install Playwright dependencies manually.${NC}"
    read -p "Press Enter to continue anyway..."
fi

# 2. Check for Gemini CLI
echo -e "${YELLOW}[2/8] Checking Gemini CLI...${NC}"
if ! command -v gemini &> /dev/null; then
    echo -e "${RED}Gemini CLI is not installed or not in PATH.${NC}"
    echo "Please install it from: https://github.com/google-gemini/gemini-cli"
    echo "Once installed, run this script again."
    # We can try to install it if user wants, but Go might not be installed.
    # Assuming user needs to do this.
    read -p "Press Enter if you have installed it in a different shell, or Ctrl+C to exit and install it."
    if ! command -v gemini &> /dev/null; then
         echo -e "${YELLOW}Warning: Gemini CLI still not found in PATH. Image generation might fail.${NC}"
    fi
else
    echo "Gemini CLI found: $(gemini --version)"
fi

# 3. Install uv
echo -e "${YELLOW}[3/8] Checking uv...${NC}"
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Source env to make uv available in this script
    source "$HOME/.local/bin/env" || export PATH="$HOME/.local/bin:$PATH"
else
    echo "uv is already installed."
fi

# 3.5. Configure NPM (User-based)
echo -e "${YELLOW}[3.5] Checking NPM Configuration...${NC}"
if command -v npm &> /dev/null; then
    NPM_PREFIX=$(npm config get prefix)
    echo "Current NPM Prefix: $NPM_PREFIX"
    
    # If prefix is /usr or /usr/local, it's system-owned. We want user-owned.
    if [[ "$NPM_PREFIX" == "/usr" ]] || [[ "$NPM_PREFIX" == "/usr/local" ]]; then
        echo "NPM is processing global packages in a system directory."
        echo "Configuring user-local npm prefix to avoid permission issues..."
        
        MSG="Configuring ~/.npm-global"
        echo "$MSG"
        
        mkdir -p "$HOME/.npm-global"
        npm config set prefix "$HOME/.npm-global"
        
        # Add to PATH immediately for this script
        export PATH="$HOME/.npm-global/bin:$PATH"
        
        # Add to ~/.bashrc if not present
        if ! grep -q "npm-global/bin" "$HOME/.bashrc"; then
            echo "" >> "$HOME/.bashrc"
            echo '# NPM user-global path' >> "$HOME/.bashrc"
            echo 'export PATH="$HOME/.npm-global/bin:$PATH"' >> "$HOME/.bashrc"
            echo "Added ~/.npm-global/bin to PATH in ~/.bashrc"
        fi
        
        echo -e "${GREEN}NPM configured to use $HOME/.npm-global${NC}"
    else
        echo "NPM prefix is already custom: $NPM_PREFIX (Good)"
    fi
else
    echo -e "${RED}NPM is not installed. It should have been installed in Step 1.${NC}"
fi

# 4. Python Virtual Environment and Requirements
echo -e "${YELLOW}[4/8] Setting up Python Environment...${NC}"
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Installing requirements..."
source venv/bin/activate
pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    echo -e "${RED}requirements.txt not found!${NC}"
    exit 1
fi

# 5. Install Playwright Browsers
echo -e "${YELLOW}[5/8] Installing Playwright Browsers...${NC}"
playwright install chromium

# 6. Install Gemini Extension
echo -e "${YELLOW}[6/8] Installing Gemini Extension...${NC}"
# We link the current directory as the extension
if command -v gemini &> /dev/null; then
    echo "Linking current directory as gemini extension..."
    gemini extensions link . || echo -e "${YELLOW}Failed to link extension (maybe already linked or gemini error).${NC}"
else
    echo -e "${YELLOW}Skipping extension installation (gemini CLI missing).${NC}"
fi

# 7. Setup Systemd Service
echo -e "${YELLOW}[7/8] Setting up Systemd Service...${NC}"

CURRENT_USER=$(whoami)
CURRENT_DIR=$(pwd)
SERVICE_FILE="auto-sites.service"

echo "Generating $SERVICE_FILE..."

cat > $SERVICE_FILE <<EOF
[Unit]
Description=Auto Sites (webscapre create) API (FastAPI/Uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$CURRENT_DIR
ExecStart=$CURRENT_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false

[Install]
WantedBy=multi-user.target
EOF

echo "Installing service..."
sudo mv $SERVICE_FILE /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now auto-sites.service

echo -e "${GREEN}Service installed and started!${NC}"
sudo systemctl status auto-sites.service --no-pager | head -n 10

# 8. Environment Variables and Tests
echo -e "${YELLOW}[8/8] Configuration and Testing...${NC}"

if [ -z "$GEMINI_API_KEY" ]; then
    echo -e "${RED}GEMINI_API_KEY is not set.${NC}"
    read -p "Enter your Gemini API Key: " INPUT_KEY
    if [ ! -z "$INPUT_KEY" ]; then
        export GEMINI_API_KEY="$INPUT_KEY"
        # Offer to save to bashrc
        read -p "Add to ~/.bashrc? (y/n) " ADD_RC
        if [[ "$ADD_RC" == "y" ]]; then
            echo "export GEMINI_API_KEY=\"$INPUT_KEY\"" >> ~/.bashrc
            echo "Added to ~/.bashrc"
        fi
    fi
else
    echo "GEMINI_API_KEY is detected."
fi

# Testing
echo "Perform a test run? (This runs test-playwright.py)"
read -p "Run test? (y/n) " RUN_TEST

if [[ "$RUN_TEST" == "y" ]]; then
    python test-playwright.py
fi

echo -e "${GREEN}Setup Complete!${NC}"
echo "You can check service status with: systemctl status auto-sites.service"
echo "API is running on port 8000."
