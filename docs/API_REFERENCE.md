# 🌐 Nazak Browser Studio PRO — REST API & Swagger Reference

> **API Server URL**: `http://127.0.0.1:8899`  
> **Interactive Swagger UI**: [`http://127.0.0.1:8899/docs`](http://127.0.0.1:8899/docs) (или [`http://127.0.0.1:8899/swagger`](http://127.0.0.1:8899/swagger))  
> **ReDoc Alternative UI**: [`http://127.0.0.1:8899/redoc`](http://127.0.0.1:8899/redoc)  
> **OpenAPI Specification JSON**: [`http://127.0.0.1:8899/openapi.json`](http://127.0.0.1:8899/openapi.json)

---

## 📑 Содержание
1. [Интерактивная документация Swagger](#-интерактивная-документация-swagger)
2. [Dolphin{anty} v1.0 Local Automation API (Playwright / Puppeteer / Selenium)](#-1-dolphinanty-v10-local-automation-api)
3. [Управление профилями и массовая генерация ферм](#-2-управление-профилями-profiles)
4. [Пакетный импорт и экспорт куков (Batch Cookies)](#-3-пакетный-импорт-и-экспорт-куков-cookies)
5. [Синхронизатор действий и сетка окон Win32](#-4-синхронизатор-действий-action-synchronizer)
6. [Конструктор сценариев и органический автопрогрев](#-5-конструктор-сценариев-и-автопрогрев-scenarios)
7. [Диагностика прокси и мобильная ротация IP](#-6-прокси-и-мобильная-ротация-ip-proxies)
8. [YouTube Shorts Stealth Autoposter & FFmpeg](#-7-youtube-shorts-autoposter--ffmpeg)
9. [Системная телеметрия и WebSocket события](#-8-системная-телеметрия-и-websocket-события)

---

## ⚡ Интерактивная документация Swagger

При запуске Nazak Browser Studio в режиме сервера (`python -m nazak.main --mode web` или при работе десктопного приложения) встроенный FastAPI сервер автоматически разворачивает интерактивный UI:

- **Swagger UI**: Откройте браузер по адресу `http://127.0.0.1:8899/docs` (или `http://127.0.0.1:8899/swagger`). Здесь вы можете тестировать каждый эндпоинт в режиме реального времени, просматривать JSON-схемы запросов и ответов и нажимать кнопку **"Try it out"**.
- **ReDoc**: Доступен по адресу `http://127.0.0.1:8899/redoc` для удобного чтения технической спецификации в трехпанельном формате.

---

## 🤖 1. Dolphin{anty} v1.0 Local Automation API

Полная совместимость со стандартным протоколом автоматизации Dolphin{anty}. Ваши существующие скрипты на **Playwright**, **Puppeteer**, **Selenium** или **BAS** могут подключаться к прогретым профилям без модификации логики.

### Эндпоинты:

#### `GET /v1.0/browser_profiles`
Получение списка всех профилей, их статусов, привязанных прокси и тегов.
- **Ответ `200 OK`**:
```json
{
  "success": true,
  "data": [
    {
      "id": "prof_01",
      "name": "01 - Google Ads USA (High-Tier Desktop RTX 4090)",
      "status": "running",
      "proxy": {
        "type": "http",
        "host": "198.51.100.24",
        "port": 8080,
        "username": "ads_user",
        "password": "secret_password"
      },
      "automation": {
        "port": 9222,
        "wsEndpoint": "ws://127.0.0.1:9222/devtools/browser/d92f98..."
      },
      "tags": ["Google Ads", "USA", "RTX4090"]
    }
  ]
}
```

#### `GET /v1.0/browser_profiles/{id}/start`
Запуск профиля Chromium с выделением динамического порта CDP и генерацией WebSocket URL для подключения автоматизации.
- **Параметры Query**:
  - `custom_url` (опционально, string) — начальный URL для открытия.
  - `port` (опционально, integer) — явный порт CDP (если не указан, выделяется свободный порт).
- **Ответ `200 OK`**:
```json
{
  "success": true,
  "automation": {
    "port": 9222,
    "wsEndpoint": "ws://127.0.0.1:9222/devtools/browser/f8d0a92b-8a71-4a1e-8e49-0123456789ab"
  },
  "pid": 14200,
  "profile_id": "prof_01"
}
```

#### `GET /v1.0/browser_profiles/{id}/stop`
Остановка работающего профиля.
- **Ответ `200 OK`**:
```json
{
  "success": true,
  "profile_id": "prof_01"
}
```

#### `GET /v1.0/browser_profiles/active`
Список всех активных на данный момент профилей с их CDP WebSocket эндпоинтами.
- **Ответ `200 OK`**:
```json
{
  "success": true,
  "active_count": 1,
  "profiles": [
    {
      "profile_id": "prof_01",
      "name": "01 - Google Ads USA",
      "pid": 14200,
      "automation": {
        "port": 9222,
        "ws_endpoint": "ws://127.0.0.1:9222/devtools/browser/f8d0a..."
      }
    }
  ]
}
```

---

### 💡 Примеры подключения скриптов автоматизации

#### 🐍 Python: Playwright (`connect_over_cdp`)
```python
import requests
from playwright.sync_api import sync_playwright

PROFILE_ID = "prof_01"
BASE_API = "http://127.0.0.1:8899"

# 1. Запуск браузера через API
start_res = requests.get(f"{BASE_API}/v1.0/browser_profiles/{PROFILE_ID}/start").json()
if not start_res.get("success"):
    raise RuntimeError(f"Failed to launch profile: {start_res}")

ws_endpoint = start_res["automation"]["wsEndpoint"]
print(f"[+] Browser launched. Connecting via CDP: {ws_endpoint}")

# 2. Подключение Playwright к запущенному изолированному профилю
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(ws_endpoint)
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else context.new_page()

    # Все куки, отпечатки железа, прокси и сессия уже активны!
    page.goto("https://www.google.com")
    print(f"[+] Page title: {page.title()}")
    
    # 3. После работы закрываем сессию
    browser.close()
    requests.get(f"{BASE_API}/v1.0/browser_profiles/{PROFILE_ID}/stop")
```

#### 📦 Node.js / JavaScript: Puppeteer (`puppeteer.connect`)
```javascript
const axios = require('axios');
const puppeteer = require('puppeteer-core');

async function main() {
    const profileId = 'prof_01';
    
    // 1. Запуск профиля
    const res = await axios.get(`http://127.0.0.1:8899/v1.0/browser_profiles/${profileId}/start`);
    const wsEndpoint = res.data.automation.wsEndpoint;
    
    // 2. Подключение к CDP
    const browser = await puppeteer.connect({ browserWSEndpoint: wsEndpoint });
    const pages = await browser.pages();
    const page = pages.length > 0 ? pages[0] : await browser.newPage();
    
    await page.goto('https://api.ipify.org?format=json');
    const content = await page.evaluate(() => document.body.innerText);
    console.log(`[+] Real Exit IP via Proxy: ${content}`);
    
    await browser.disconnect();
    await axios.get(`http://127.0.0.1:8899/v1.0/browser_profiles/${profileId}/stop`);
}

main().catch(console.error);
```

#### 💻 cURL
```bash
# Запуск
curl -X GET "http://127.0.0.1:8899/v1.0/browser_profiles/prof_01/start"

# Остановка
curl -X GET "http://127.0.0.1:8899/v1.0/browser_profiles/prof_01/stop"
```

---

## 👤 2. Управление профилями (Profiles)

| Метод | Путь | Описание |
| :--- | :--- | :--- |
| `GET` | `/api/profiles` | Получить список всех профилей с их реальным статусом и PID |
| `POST` | `/api/profiles` | Создать новый изолированный профиль |
| `GET` | `/api/profiles/{id}` | Получить подробную конфигурацию профиля |
| `PUT` | `/api/profiles/{id}` | Обновить параметры железа/прокси/аккаунта |
| `DELETE` | `/api/profiles/{id}` | Удалить профиль и очистить файлы сессии на диске |
| `POST` | `/api/profiles/{id}/clone` | Клонировать профиль со случайным перевыпуском отпечатков железа |
| `POST` | `/api/profiles/{id}/launch` | Запуск браузера (обычный или с CDP) |
| `POST` | `/api/profiles/{id}/stop` | Остановка процесса браузера |
| `POST` | `/api/profiles/batch-launch` | Пакетный запуск массива `["prof_01", "prof_02"]` |
| `POST` | `/api/profiles/batch-stop` | Пакетная остановка массива `["prof_01", "prof_02"]` |
| `POST` | `/api/profiles/mass-generate` | Массовое создание фермы (1–100+ профилей) с Round-Robin прокси |
| `POST` | `/api/profiles/bulk-import` | Пакетное создание профилей из строк прокси |
| `GET` | `/api/profiles/{id}/bundle/export` | Экспорт профиля в портативный `.nazak` zip-архив |
| `POST` | `/api/profiles/{id}/clear-cache` | Очистка кэша браузера, шейдеров и временных файлов профиля |

---

## 🍪 3. Пакетный импорт и экспорт куков (Cookies)

#### `POST /api/cookies/bulk-import`
Универсальный пакетный импорт куков для множества профилей одновременно.
- **Поддерживаемые форматы `cookies_data`**:
  1. Блоки с разделителями профилей (`=== Profile 01 ===`, `--- Name ---`, `[Profile 01]`).
  2. JSON-карта `{ "Profile_A": [...], "Profile_B": [...] }`.
  3. Одиночный массив JSON или формат Netscape.
- **Request Body**:
```json
{
  "cookies_data": "=== Account Alpha ===\n[{\"name\":\"SID\",\"value\":\"secret\",\"domain\":\".google.com\",\"path\":\"/\"}]\n\n=== Account Beta ===\n.google.com\tTRUE\t/\tTRUE\t0\tHSID\tsecret2\n",
  "auto_create_missing": true,
  "group": "Farm Batch 1"
}
```
- **Response**:
```json
{
  "success": true,
  "results": {
    "matched": 2,
    "created": 0,
    "failed": 0
  }
}
```

#### `POST /api/cookies/bulk-export`
Экспорт всех сессионных куков в структурированный JSON или скачиваемый `.zip` архив.
- **Request Body**:
```json
{
  "profile_ids": ["prof_01", "prof_02"],
  "format": "zip"
}
```

---

## ⚡ 4. Синхронизатор действий (Action Synchronizer)

Репликация действий из главного окна (**Master**) на любые дочерние окна (**Workers**) с защитой от антифрода (суб-пиксельный джиттер и временные задержки) и автораскладкой окон по сетке.

| Метод | Путь | Описание |
| :--- | :--- | :--- |
| `POST` | `/api/synchronizer/start` | Запуск сессии синхронизации Master → Workers |
| `POST` | `/api/synchronizer/stop` | Остановка текущей синхронизации |
| `GET` | `/api/synchronizer/status` | Получение статуса сессии синхронизации |
| `POST` | `/api/synchronizer/tile-windows` | 1-Клик выравнивание всех окон браузера по сетке 2x2, 3x3, 4x4 |
| `POST` | `/api/synchronizer/navigate` | Мгновенная синхронная навигация всех воркеров на URL |

---

## 🔥 5. Конструктор сценариев и автопрогрев (Scenarios)

#### `GET /api/scenarios`
Получение списка встроенных сценариев:
- `ecommerce_trust_booster` — Прогрев поисковой выдачи Google, интернет-магазины, клики по товарам.
- `youtube_shorts_warmup` — Просмотр ленты Shorts, досмотры видео, разгон рекомендаций.
- `crypto_web3_farming` — Серфинг CoinMarketCap, DeFi протоколов, крипто-новостей.
- `finance_high_cpc_banking` — Сбор трастовых куков высшей ценовой категории (банки, кредиты).

#### `POST /api/scenarios/run`
Запуск сценария по пулу профилей с контролем параллелизма (`max_concurrency`).
- **Request Body**:
```json
{
  "scenario_id": "ecommerce_trust_booster",
  "profile_ids": ["prof_01", "prof_02", "prof_03"],
  "max_concurrency": 3
}
```

---

## 📱 6. Прокси и мобильная ротация IP (Proxies)

#### `POST /api/profiles/{id}/rotate-proxy`
Вызов URL ротации динамического мобильного прокси (смена внешнего IP адреса по ссылке провайдера).
- **Response `200 OK`**:
```json
{
  "success": true,
  "status_code": 200,
  "response": "{\"status\":\"IP_CHANGED\",\"new_ip\":\"188.130.155.40\"}"
}
```

#### `POST /api/profiles/{id}/check`
5-этапная диагностика: TCP Latency, Geolocation / ISP, Google Reachability Suite, проверка хранилища, WebRTC Isolation.

---

## 🎬 7. YouTube Shorts Autoposter & FFmpeg

| Метод | Путь | Описание |
| :--- | :--- | :--- |
| `GET` | `/api/autopost/status` | Статус очереди автопостинга и доступность FFmpeg |
| `POST` | `/api/autopost/uniquify` | Глубокая уникализация исходного видео под каждый профиль |
| `POST` | `/api/autopost/launch` | Запуск автономной очереди загрузки с кривыми Безье |
| `POST` | `/api/autopost/cancel` | Мгновенная отмена очереди загрузок |
| `POST` | `/api/autopost/preview-spintax` | Предпросмотр рандомизации названий и описаний |

---

## 📡 8. Системная телеметрия и WebSocket события

### `GET /api/system/info`
Возвращает информацию о хосте, пути к Google Chrome, количестве запущенных браузеров и путях к данным.

### `WebSocket /ws/events`
Стриминг событий в реальном времени:
```json
// Пример: статус браузера изменился
{
  "event": "profile_status_change",
  "data": {
    "profile_id": "prof_01",
    "status": "running",
    "pid": 14200
  }
}
```
Другие типы событий:
- `profile_created`, `profile_updated`, `profile_deleted`
- `profile_health_update`
- `cookies_bulk_imported`
- `synchronizer_started`, `synchronizer_stopped`
- `autopost_progress`, `autopost_complete`
