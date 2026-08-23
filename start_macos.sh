#!/usr/bin/env bash
# ==============================================================================
# Nazak Browser Studio PRO — macOS & Linux Turnkey One-Click Launcher
# Supports Apple Silicon (M1/M2/M3/M4) and Intel Macs
# ==============================================================================

set -e

# Change to script directory
cd "$(dirname "$0")"

# Colors for terminal styling
CYAN='\033[0;36m'
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color
BOLD='\033[1m'

echo -e "${CYAN}${BOLD}"
echo "  _   _                 _      "
echo " | \ | | __ _ ______ _ | | __  "
echo " |  \| |/ _\` |_  / _\` || |/ /  "
echo " | |\  | (_| |/ / (_| ||   <   "
echo " |_| \_|\__,_/___\__,_||_|\_\  "
echo " BROWSER STUDIO PRO // macOS   "
echo -e "${NC}"

# 1. Locate Python 3
PYTHON_BIN=""
for py in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$py" >/dev/null 2>&1; then
        PYTHON_BIN="$py"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}[ERROR] Python 3.10+ не найден в системе.${NC}"
    echo -e "Установите через Homebrew: ${YELLOW}brew install python${NC}"
    exit 1
fi

echo -e "${BLUE}[INFO] Обнаружен Python:${NC} $($PYTHON_BIN --version) ($PYTHON_BIN)"

# 2. Virtual Environment Setup
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}[SETUP] Создание виртуального окружения $VENV_DIR...${NC}"
    $PYTHON_BIN -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# 3. Verify / Install Dependencies
if ! python -c "import fastapi, uvicorn, PyQt6, qfluentwidgets" >/dev/null 2>&1; then
    echo -e "${YELLOW}[SETUP] Установка необходимых зависимостей...${NC}"
    pip install --upgrade pip
    pip install -r requirements.txt
    playwright install chromium || true
fi

# 4. Interactive Menu
echo ""
echo -e "${BOLD}Выберите режим запуска:${NC}"
echo -e "  ${CYAN}[1]${NC} 🖥️  Запустить Desktop Fluent GUI (Нативное окно)"
echo -e "  ${CYAN}[2]${NC} 🌐  Запустить Web Studio Dashboard (http://127.0.0.1:8899)"
echo -e "  ${CYAN}[3]${NC} 🧪  Запустить 271 автоматический тест"
echo -e "  ${CYAN}[4]${NC} 🚀  CLI: Авторизация Google + Залив тестового видео"
echo -e "  ${CYAN}[5]${NC} 📦  Установить/Обновить браузер Chromium (Playwright)"
echo -e "  ${CYAN}[0]${NC} 🚪  Выход"
echo ""

read -p "Ваш выбор [1-5]: " choice

case $choice in
    1)
        echo -e "${GREEN}[LAUNCH] Запуск нативного Desktop GUI...${NC}"
        python -m nazak.main --mode gui
        ;;
    2)
        echo -e "${GREEN}[LAUNCH] Запуск Web Studio на http://127.0.0.1:8899 ...${NC}"
        python -m nazak.main --mode web
        ;;
    3)
        echo -e "${GREEN}[TESTS] Запуск 271 теста...${NC}"
        python -m pytest -p no:asyncio tests -v
        ;;
    4)
        echo -e "${GREEN}[CLI] Запуск автономного процесса авторизации и загрузки...${NC}"
        python nazak/cli_auto_login_and_upload.py
        ;;
    5)
        echo -e "${GREEN}[SETUP] Установка Playwright Chromium...${NC}"
        playwright install chromium
        echo -e "${GREEN}Готово!${NC}"
        ;;
    0)
        echo "Выход."
        exit 0
        ;;
    *)
        echo -e "${GREEN}[LAUNCH] По умолчанию: запуск Desktop GUI...${NC}"
        python -m nazak.main --mode gui
        ;;
esac
