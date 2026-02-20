#!/bin/bash
set -e

# setup.sh - Setup script for Auto Sites Service
# usage: ./setup.sh

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color
PORT=${PORT:-8000}

# Uninstall Logic
if [[ "$1" == "--uninstall" ]]; then
    echo -e "${YELLOW}Uninstalling Auto Sites Service...${NC}"
    if systemctl is-active --quiet auto-sites.service; then
        sudo systemctl stop auto-sites.service
    fi
    if systemctl is-enabled --quiet auto-sites.service 2>/dev/null; then
        sudo systemctl disable auto-sites.service
    fi
    if [ -f "/etc/systemd/system/auto-sites.service" ]; then
        sudo rm /etc/systemd/system/auto-sites.service
        sudo systemctl daemon-reload
    fi
    echo "Removing local environment files..."
    rm -rf venv .env
    echo -e "${GREEN}Uninstallation Complete!${NC}"
    exit 0
fi

echo -e "${GREEN}Starting Auto Sites Service Setup...${NC}"

# 1. Check OS and Install System Dependencies
echo -e "${YELLOW}[1/9] Checking System Dependencies...${NC}"

if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$NAME
elif type lsb_release >/dev/null 2>&1; then
    OS=$(lsb_release -si)
else
    OS=$(uname -s)
fi

# Check for existing node/npm
if command -v node &> /dev/null && command -v npm &> /dev/null; then
    echo "Node.js and npm are already installed. Skipping system installation."
    NODE_PACKAGES=""
else
    echo "Node.js/npm not found. Adding to install list..."
    NODE_PACKAGES="nodejs npm"
fi

echo "Detected OS: $OS"

if [[ "$OS" == *"Fedora"* ]] || [[ "$OS" == *"Red Hat"* ]] || [[ "$OS" == *"CentOS"* ]]; then
    echo "Installing dependencies for RHEL/Fedora..."
    sudo dnf update -y
    sudo dnf install -y nss atk at-spi2-atk cups-libs libdrm mesa-libgbm \
        libXcomposite libXdamage libXext libXfixes libXrandr libxcb \
        libxkbcommon pango alsa-lib libXcursor libXi libXScrnSaver bc curl git $NODE_PACKAGES
elif [[ "$OS" == *"Debian"* ]] || [[ "$OS" == *"Ubuntu"* ]]; then
    echo "Installing dependencies for Debian/Ubuntu..."
    sudo apt-get update
    # Check for Ubuntu 24.04+ (Noble Numbat) which uses t64 packages for 64-bit time_t transition
    UBUNTU_MAJOR_VERSION=0
    if [[ "$OS" == *"Ubuntu"* ]] && [ ! -z "$VERSION_ID" ]; then
        UBUNTU_MAJOR_VERSION=$(echo "$VERSION_ID" | cut -d. -f1)
    fi

    if [[ "$OS" == *"Ubuntu"* ]] && [[ "$UBUNTU_MAJOR_VERSION" -ge 24 ]]; then
        echo "Detected Ubuntu 24.04+ (Noble). Installing t64 packages..."
        sudo apt-get install -y libnss3 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 libdrm2 \
            libgbm1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
            libxrandr2 libxcb1 libxkbcommon0 libpango-1.0-0 \
            libasound2t64 libxcursor1 libxi6 libxss1 bc curl git $NODE_PACKAGES
    else
        echo "Installing default dependencies..."
        sudo apt-get install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
            libgbm1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
            libxrandr2 libxcb1 libxkbcommon0 libpango-1.0-0 \
            libasound2 libxcursor1 libxi6 libxss1 bc curl git $NODE_PACKAGES
    fi
else
    echo -e "${RED}Unsupported or unknown OS: $OS. Please install Playwright dependencies manually.${NC}"
    read -p "Press Enter to continue anyway..."
fi

# 2. Configure NPM (User-based)
echo -e "${YELLOW}[2/9] Checking NPM Configuration...${NC}"
if command -v npm &> /dev/null; then
    NPM_PREFIX=$(npm config get prefix)
    echo "Current NPM Prefix: $NPM_PREFIX"
    
    # If prefix is /usr or /usr/local, it's system-owned. We want user-owned or custom.
    # Note: we check if it is explicitly system owned.
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
        # Assuming permissions are fine if it's custom.
        # We ensure it's in PATH if we can guess it, but usually custom prefix means user knows what they are doing.
        if [[ "$NPM_PREFIX" != "/usr"* ]]; then
             export PATH="$NPM_PREFIX/bin:$PATH"
        fi
    fi
else
    echo -e "${RED}NPM is not installed. It should have been installed in Step 1.${NC}"
fi

# 3. Check for Gemini CLI
echo -e "${YELLOW}[3/9] Checking Gemini CLI...${NC}"
if ! command -v gemini &> /dev/null; then
    echo "Gemini CLI not found."
    
    if command -v npm &> /dev/null; then
        echo "Installing Gemini CLI via npm (@google/gemini-cli)..."
        npm install -g @google/gemini-cli
        
        # Re-check
        if ! command -v gemini &> /dev/null; then
             echo -e "${RED}Gemini CLI install failed or not in PATH.${NC}"
             echo "Please verify npm global bin path is in your PATH."
        else
             echo "Gemini CLI installed successfully: $(gemini --version)"
        fi
    else
        echo -e "${RED}NPM not found, cannot install Gemini CLI automatically.${NC}"
        echo "Please install it from: https://github.com/google-gemini/gemini-cli"
    fi
else
    echo "Gemini CLI found: $(gemini --version)"
fi

# 4. Install uv
echo -e "${YELLOW}[4/9] Checking uv...${NC}"
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Source env to make uv available in this script
    source "$HOME/.local/bin/env" || export PATH="$HOME/.local/bin:$PATH"
else
    echo "uv is already installed."
fi

# 5. Python Virtual Environment and Requirements
echo -e "${YELLOW}[5/9] Setting up Python Environment...${NC}"
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Installing requirements..."
if [ -f "requirements.txt" ]; then
    if command -v uv &> /dev/null; then
        echo "Using uv to install dependencies (fast)..."
        uv pip install --python ./venv -r requirements.txt
    else
        echo "Using standard pip..."
        ./venv/bin/python3 -m pip install --upgrade pip
        ./venv/bin/pip install -r requirements.txt
    fi
else
    echo -e "${RED}requirements.txt not found!${NC}"
    exit 1
fi

# 6. Install Playwright Browsers
echo -e "${YELLOW}[6/9] Installing Playwright Browsers...${NC}"
playwright install chromium

# 7. Install Gemini Extension
echo -e "${YELLOW}[7/9] Installing Gemini Extension...${NC}"
# We link the current directory as the extension
if command -v gemini &> /dev/null; then
    echo "Linking current directory as gemini extension..."
    gemini extensions link . || echo -e "${YELLOW}Failed to link extension (maybe already linked or gemini error).${NC}"
else
    echo -e "${YELLOW}Skipping extension installation (gemini CLI missing).${NC}"
fi

# 8. Configure API Keys
echo -e "${YELLOW}[8/9] Configuring API Keys...${NC}"

if [ -z "$GEMINI_API_KEY" ]; then
    # Try to verify if it's already in .bashrc but not exported to this shell
    if grep -q "GEMINI_API_KEY" "$HOME/.bashrc"; then
         echo "Found GEMINI_API_KEY in .bashrc..."
         # We won't source it automatically to avoid side effects, but we'll ask the user.
    fi

    echo -e "${RED}GEMINI_API_KEY is not set in the current session.${NC}"
    echo "The service needs this key to function."
    read -p "Enter your Gemini API Key: " INPUT_KEY
    if [ ! -z "$INPUT_KEY" ]; then
        export GEMINI_API_KEY="$INPUT_KEY"
        
        # Ask to save to .bashrc if not there
        if ! grep -q "GEMINI_API_KEY" "$HOME/.bashrc"; then
            read -p "Add to ~/.bashrc for future sessions? (y/n) " ADD_RC
            if [[ "$ADD_RC" == "y" ]]; then
                echo "" >> "$HOME/.bashrc"
                echo "export GEMINI_API_KEY=\"$INPUT_KEY\"" >> "$HOME/.bashrc"
                echo "Added to ~/.bashrc"
            fi
        fi
    fi
else
    echo "✅ GEMINI_API_KEY is set."
fi

# Optional: OpenRouter
if [ -z "$OPENROUTER_API_KEY" ]; then
    # Silent check, only prompt if Gemini is missing? 
    # Or just let the user know they can set it.
    if [ -z "$GEMINI_API_KEY" ]; then
        echo -e "${YELLOW}Gemini Key is missing. You can provide an OPENROUTER_API_KEY instead.${NC}"
        read -p "Enter OpenRouter API Key: " OR_KEY
        if [ ! -z "$OR_KEY" ]; then
            export OPENROUTER_API_KEY="$OR_KEY"
             if ! grep -q "OPENROUTER_API_KEY" "$HOME/.bashrc"; then
                echo "export OPENROUTER_API_KEY=\"$OR_KEY\"" >> "$HOME/.bashrc"
            fi
        fi
    fi
fi

# 9. Setup Systemd Service
echo -e "${YELLOW}[9/9] Setting up Systemd Service...${NC}"

CURRENT_USER=$(whoami)
CURRENT_DIR=$(pwd)
SERVICE_FILE="auto-sites.service"
ENV_FILE="$CURRENT_DIR/.env"

# Check if port is in use
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null ; then
    echo -e "${RED}Error: Port $PORT is already in use!${NC}"
    PID=$(lsof -Pi :$PORT -sTCP:LISTEN -t)
    echo "Process ID: $PID"
    echo "Please stop the process running on port $PORT and try again."
    # Optional: ask to kill
    read -p "Do you want to kill this process? (y/n) " KILL_PROC
    if [[ "$KILL_PROC" == "y" ]]; then
        kill -9 $PID
        echo "Process killed."
    else
        exit 1
    fi
fi

echo "Configuring $ENV_FILE..."

# Helper function to safely set or update a key=value in .env
update_env() {
    local key="$1"
    local val="$2"
    local file="$3"
    # If key exists, replace it inline; if not, append it
    if grep -q "^${key}=" "$file"; then
        sed -i "s|^${key}=.*|${key}=${val}|" "$file"
    else
        echo "${key}=${val}" >> "$file"
    fi
}

if [ ! -f "$ENV_FILE" ]; then
    echo "Creating new .env from .env.example..."
    cp "$CURRENT_DIR/.env.example" "$ENV_FILE"
else
    echo "Existing .env found. Checking for missing keys..."
    # Append any variables from .env.example that don't exist in the current .env
    grep -E '^[A-Z_]+=' "$CURRENT_DIR/.env.example" | while read -r line; do
        key=$(echo "$line" | cut -d= -f1)
        if ! grep -q "^${key}=" "$ENV_FILE"; then
            echo "Appending missing key: $key"
            echo "" >> "$ENV_FILE"
            echo "# Auto-appended from .env.example during setup" >> "$ENV_FILE"
            echo "$line" >> "$ENV_FILE"
        fi
    done
fi

# Now apply the runtime dynamic values without destroying other keys (like API_TOKEN)
update_env "PORT" "$PORT" "$ENV_FILE"

if [ ! -z "$GEMINI_API_KEY" ]; then
    update_env "GEMINI_API_KEY" "\"$GEMINI_API_KEY\"" "$ENV_FILE"
fi

if [ ! -z "$OPENROUTER_API_KEY" ]; then
    update_env "OPENROUTER_API_KEY" "\"$OPENROUTER_API_KEY\"" "$ENV_FILE"
fi

chmod 600 "$ENV_FILE"
# Add explicit PATH to .env just in case, though usually better in service file.
# We will rely on EnvironmentFile for keys and Environment for PATH in the service file.

echo "Generating $SERVICE_FILE..."

# Construct the PATH to include:
# 1. venv/bin (first priority)
# 2. ~/.local/bin (for uv)
# 3. ~/.npm-global/bin (for gemini CLI via npm)
# 4. Current user PATH (captures NVM, etc.)
SERVICE_PATH="$CURRENT_DIR/venv/bin:$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"

cat > $SERVICE_FILE <<EOF
[Unit]
Description=Auto Sites (webscapre create) API (FastAPI/Uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$CURRENT_DIR
EnvironmentFile=$ENV_FILE
Environment="PATH=$SERVICE_PATH"
ExecStart=$CURRENT_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port $PORT
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
sudo systemctl status auto-sites.service --no-pager | head -n 12

# 10. Final Verification
echo -e "${YELLOW}[Verification] Running Tests...${NC}"

echo "Perform a test run? (This runs test-playwright.py)"
read -p "Run test? (y/n) " RUN_TEST

if [[ "$RUN_TEST" == "y" ]]; then
    python test-playwright.py
fi

echo -e "${GREEN}Setup Complete!${NC}"
echo "Service is running on Port $PORT"
echo "Check status: systemctl status auto-sites.service"

