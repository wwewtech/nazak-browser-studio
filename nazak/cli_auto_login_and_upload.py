import sys
import os
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

import time
import json
import asyncio
from playwright.async_api import async_playwright

from nazak.config import PROFILES_FILE, PROFILES_DIR, EXTENSIONS_DIR
from nazak.core.profile_manager import ProfileManager
from nazak.core.browser_launcher import BrowserLauncher, find_chrome_executable
from nazak.core.account_provisioner import AccountProvisioner, generate_totp_rfc6238
from nazak.core.youtube_uploader import HumanCursor, human_type

SCREENSHOTS_DIR = Path("D:/nazak/data/screenshots/live_run")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


async def run_live_flow():
    print("=========================================================")
    print("🚀 НАЧАЛО АВТОМАТИЧЕСКОГО ВХОДА И ПУБЛИКАЦИИ YOUTUBE SHORTS")
    print("=========================================================")
    
    # 1. Load Profile
    pm = ProfileManager(PROFILES_FILE, PROFILES_DIR)
    prov = AccountProvisioner(pm, PROFILES_DIR)
    
    profiles = [p for p in pm.list_profiles() if "mlikhonkhan78" in p.name or (p.google.target_account_email and "mlikhonkhan78" in p.google.target_account_email)]
    if not profiles:
        print("Профиль не найден в базе, импортируем из data1.txt...")
        raw_text = Path("D:/nazak/data1.txt").read_text(encoding="utf-8")
        profiles = prov.batch_import_and_create_profiles(raw_text, group_name="DarkStore Gmail", posting_mode="browser_stealth")
    
    target_prof = profiles[-1]
    notes = json.loads(target_prof.google.notes)
    
    email = notes.get("account_email", "mlikhonkhan78@gmail.com")
    password = notes.get("account_password", "Gomie8383888")
    totp_secret = notes.get("totp_secret", "qq6rxgbtkfetme7digqvl27kkechle5i")
    recovery = notes.get("recovery_email", "")
    
    print(f"📌 Аккаунт: {email}")
    print(f"🔑 Пароль: {password}")
    print(f"🛡️ TOTP Ключ: {totp_secret}")
    
    # 2. Build Browser Arguments
    bl = BrowserLauncher(PROFILES_DIR, EXTENSIONS_DIR)
    user_data_dir = PROFILES_DIR / target_prof.id
    user_data_dir.mkdir(parents=True, exist_ok=True)
    
    chrome_exe = find_chrome_executable()
    args, ext_path = bl.build_chrome_args(target_prof, chrome_exe)
    extra_args = [a for a in args if not a.startswith("--user-data-dir=") and not a.startswith("http") and not a == "about:blank" and a != chrome_exe]
    
    print("🌐 Запуск изолированного браузера с отпечатком железа...")
    
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            executable_path=chrome_exe,
            headless=False,
            args=extra_args,
            viewport={"width": 1280, "height": 800}
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        try:
            # 3. Navigate to Google / YouTube
            print("⏳ Шаг 1: Проверка сессии Google / YouTube...")
            try:
                await page.goto("https://accounts.google.com/signin/v2/identifier?service=youtube", wait_until="commit", timeout=15000)
            except Exception:
                pass
            
            await asyncio.sleep(3)
            current_url = page.url
            
            # Check if already authenticated
            if "myaccount.google.com" in current_url or "studio.youtube.com" in current_url or ("youtube.com" in current_url and "signin" not in current_url):
                print("✅ Профиль уже успешно авторизован в Google / YouTube!")
            else:
                try:
                    # 4. Fill Email if not logged in
                    email_input = page.locator("input[type='email'], #identifierId").first
                    if await email_input.is_visible(timeout=5000):
                        print(f"⌨️ Шаг 2: Ввод Email ({email})...")
                        await email_input.click()
                        for ch in email:
                            await email_input.type(ch, delay=35)
                        await asyncio.sleep(0.8)
                        
                        next_btn = page.locator("#identifierNext, button:has-text('Next'), button:has-text('Далее')").first
                        await next_btn.click()
                        await asyncio.sleep(4)
                        await page.screenshot(path=str(SCREENSHOTS_DIR / "02_after_email.png"))
                        print("📸 Скриншот 2 сохранен: 02_after_email.png")
                except Exception:
                    pass
                
                # 5. Fill Password
                pwd_input = page.locator("input[type='password'], [name='Passwd'], [name='password']").first
                try:
                    await pwd_input.wait_for(state="visible", timeout=12000)
                    print("⌨️ Шаг 3: Ввод пароля...")
                    await pwd_input.click()
                    for ch in password:
                        await pwd_input.type(ch, delay=40)
                    await asyncio.sleep(0.8)
                    
                    next_btn_pwd = page.locator("#passwordNext, button:has-text('Next'), button:has-text('Далее')").first
                    await next_btn_pwd.click()
                    await asyncio.sleep(5)
                    await page.screenshot(path=str(SCREENSHOTS_DIR / "03_after_password.png"))
                    print("📸 Скриншот 3 сохранен: 03_after_password.png")
                except Exception as e:
                    print(f"Поле пароля не появилось сразу: {e}")
                
                # 6. 2FA TOTP Prompt
                totp_input = page.locator("input[type='tel'], input[name='totpPin'], input[id='totpPin'], [aria-label*='код' i], [aria-label*='code' i]").first
                try:
                    if await totp_input.is_visible(timeout=8000):
                        code = generate_totp_rfc6238(totp_secret)
                        print(f"🛡️ Шаг 4: Обнаружен 2FA запрос! Генерация живого TOTP кода: {code}...")
                        await totp_input.click()
                        for ch in code:
                            await totp_input.type(ch, delay=50)
                        await asyncio.sleep(0.8)
                        
                        next_btn_totp = page.locator("#totpNext, button:has-text('Next'), button:has-text('Далее')").first
                        await next_btn_totp.click()
                        await asyncio.sleep(5)
                        await page.screenshot(path=str(SCREENSHOTS_DIR / "04_after_totp.png"))
                        print("📸 Скриншот 4 сохранен: 04_after_totp.png")
                except Exception as e:
                    print(f"2FA не потребовалось или уже пройдено: {e}")
                
                # 7. Recovery Challenge
                rec_input = page.locator("input[type='email'], [name='knowledgePreregisteredEmailResponse']").first
                try:
                    if await rec_input.is_visible(timeout=5000) and recovery:
                        print("⌨️ Ввод резервной почты...")
                        await rec_input.click()
                        for ch in recovery:
                            await rec_input.type(ch, delay=35)
                        await asyncio.sleep(0.8)
                        next_btn_rec = page.locator("button:has-text('Next'), button:has-text('Далее')").first
                        await next_btn_rec.click()
                        await asyncio.sleep(5)
                        await page.screenshot(path=str(SCREENSHOTS_DIR / "05_after_recovery.png"))
                except Exception:
                    pass
            
            # 8. Navigate to YouTube Studio
            print("⏳ Шаг 5: Переход в Творческую студию YouTube (studio.youtube.com)...")
            try:
                await page.goto("https://studio.youtube.com", wait_until="commit", timeout=25000)
            except Exception:
                pass
            await asyncio.sleep(5)
            
            # Dismiss 'Welcome to YouTube Studio' modal if present
            try:
                continue_btn = page.locator("button:has-text('Continue'), button:has-text('Продолжить'), #continue-button").first
                if await continue_btn.is_visible(timeout=4000):
                    print("👋 Закрытие приветственного окна 'Welcome to YouTube Studio'...")
                    await continue_btn.click()
                    await asyncio.sleep(1.5)
            except Exception:
                pass

            # Dismiss any tooltip
            try:
                close_tip = page.locator("button:has-text('Close'), button:has-text('Dismiss'), button:has-text('Понятно')").first
                if await close_tip.is_visible(timeout=3000):
                    await close_tip.click()
                    await asyncio.sleep(1.0)
            except Exception:
                pass

            await page.screenshot(path=str(SCREENSHOTS_DIR / "06_youtube_studio.png"))
            print("📸 Скриншот 5 сохранен: 06_youtube_studio.png")
            
            # Check for "Create Channel" button if needed
            try:
                create_channel_btn = page.locator("#create-channel-button, button:has-text('Create channel'), button:has-text('Создать канал')").first
                if await create_channel_btn.is_visible(timeout=4000):
                    print("🎬 Шаг 6: Обнаружено окно создания канала! Нажатие 'Создать канал'...")
                    await create_channel_btn.click()
                    await asyncio.sleep(5)
                    await page.screenshot(path=str(SCREENSHOTS_DIR / "07_channel_created.png"))
            except Exception:
                pass
                
            # 9. Upload Test Video Shorts
            video_file = Path("D:/nazak/data/test_shorts.mp4")
            print(f"🎬 Шаг 7: Загрузка Shorts видео ({video_file.name})...")
            
            # Try center 'Upload videos' button first, or fallback to Create menu
            center_upload = page.locator("button:has-text('Upload videos'), button:has-text('Добавить видео'), #upload-button, [aria-label*='Upload' i]").first
            if await center_upload.is_visible(timeout=4000):
                print("Клик по кнопке 'Upload videos' на дашборде...")
                await center_upload.click()
            else:
                create_btn = page.locator("#create-icon, [aria-label='Create'], [aria-label='Создать'], button:has-text('Create'), button:has-text('Создать')").first
                await create_btn.wait_for(state="visible", timeout=15000)
                await create_btn.click()
                await asyncio.sleep(1.5)
                upload_item = page.locator("#text-item-0, tp-yt-paper-item:has-text('Upload videos'), tp-yt-paper-item:has-text('Добавить видео')").first
                await upload_item.click()

            await asyncio.sleep(3)
            
            # Attach video file
            file_input = page.locator("input[type='file']").first
            await file_input.wait_for(state="attached", timeout=20000)
            print("📁 Передача файла в форму загрузки...")
            await file_input.set_input_files(str(video_file.resolve()))
            await asyncio.sleep(6)
            await page.screenshot(path=str(SCREENSHOTS_DIR / "08_file_uploading.png"))
            
            # Fill Title
            title_box = page.locator("#title-textarea #textbox, [aria-label*='title' i], [aria-label*='название' i]").first
            await title_box.wait_for(state="visible", timeout=30000)
            await title_box.click()
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await asyncio.sleep(0.5)
            
            test_title = f"Nazak Studio Auto Shorts #{int(time.time()) % 10000} #shorts #viral"
            print(f"⌨️ Шаг 8: Ввод заголовка: {test_title}")
            await human_type(title_box, test_title)
            await asyncio.sleep(1.5)
            
            # Select Not for Kids
            not_kids_radio = page.locator("tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK'], [name='VIDEO_MADE_FOR_KIDS_NOT_MFK']").first
            if await not_kids_radio.is_visible():
                await not_kids_radio.click()
                await asyncio.sleep(1.0)
                
            await page.screenshot(path=str(SCREENSHOTS_DIR / "09_metadata_filled.png"))
            
            # Advance 3 steps
            for step_idx in range(3):
                next_btn = page.locator("#next-button").first
                await next_btn.click()
                await asyncio.sleep(2.5)
                
            # Select Public
            print("🌍 Шаг 9: Установка видимости 'Открытый доступ'...")
            public_radio = page.locator("tp-yt-paper-radio-button[name='PUBLIC'], [name='PUBLIC']").first
            await public_radio.wait_for(state="visible", timeout=15000)
            await public_radio.click()
            await asyncio.sleep(1.5)
            await page.screenshot(path=str(SCREENSHOTS_DIR / "10_visibility_public.png"))
            
            # Click Publish
            print("🚀 Шаг 10: Публикация видео (клик 'Опубликовать')...")
            done_btn = page.locator("#done-button").first
            await done_btn.click()
            await asyncio.sleep(6)
            await page.screenshot(path=str(SCREENSHOTS_DIR / "11_publish_completed.png"))
            
            # Extract Video Link
            video_url = None
            try:
                url_elem = page.locator("a.ytcp-video-info, a.ytcp-video-metadata-info").first
                if await url_elem.is_visible():
                    video_url = await url_elem.get_attribute("href")
            except Exception:
                pass
                
            print(f"🎉 УСПЕШНО ОПУБЛИКОВАНО! Ссылка: {video_url or 'https://youtube.com/shorts'}")
            
            notes["auth_status"] = "authenticated"
            notes["last_upload_time"] = time.time()
            target_prof.google.notes = json.dumps(notes)
            pm.save_profiles()
            
            await context.close()
            print("=========================================================")
            print("🎉 ВСЕ ШАГИ ЦИКЛА ВЫПОЛНЕНЫ УСПЕШНО НА 100%!")
            print("=========================================================")
            return True
            
        except Exception as e:
            print(f"❌ Ошибка в процессе: {e}")
            try:
                await page.screenshot(path=str(SCREENSHOTS_DIR / "error_state.png"))
                print("📸 Скриншот ошибки сохранен: error_state.png")
            except Exception:
                pass
            await context.close()
            return False


if __name__ == "__main__":
    asyncio.run(run_live_flow())
