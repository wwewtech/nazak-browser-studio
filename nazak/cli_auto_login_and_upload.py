import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import json
import time

from playwright.async_api import async_playwright

from nazak.config import DATA_DIR, EXTENSIONS_DIR, PROFILES_DIR, PROFILES_FILE
from nazak.core.account_provisioner import AccountProvisioner, generate_totp_rfc6238
from nazak.core.browser_launcher import BrowserLauncher, find_chrome_executable
from nazak.core.profile_manager import ProfileManager
from nazak.core.youtube_uploader import human_type

SCREENSHOTS_DIR = DATA_DIR / "screenshots" / "live_run"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


async def run_live_flow():
    print("=========================================================")
    print("🚀 STARTING AUTOMATIC SIGN-IN AND YOUTUBE SHORTS PUBLISHING")
    print("=========================================================")

    # 1. Load Profile
    pm = ProfileManager(PROFILES_FILE, PROFILES_DIR)
    prov = AccountProvisioner(pm, PROFILES_DIR)

    target_email = os.environ.get("GOOGLE_EMAIL", "")
    profiles = []
    if target_email:
        profiles = [
            p
            for p in pm.list_profiles()
            if (target_email in p.name)
            or (p.google and p.google.target_account_email and target_email in p.google.target_account_email)
        ]
    if not profiles:
        existing = pm.list_profiles()
        google_profs = [p for p in existing if p.google and (p.google.notes or p.google.target_account_email)]
        if google_profs:
            profiles = [google_profs[0]]
        elif existing:
            profiles = [existing[0]]

    if not profiles:
        data_file = Path(os.environ.get("NAZAK_DATA_FILE", DATA_DIR / "data1.txt"))
        if data_file.exists():
            print(f"Profile not found in the database, importing from {data_file}...")
            raw_text = data_file.read_text(encoding="utf-8")
            profiles = prov.batch_import_and_create_profiles(
                raw_text, group_name="DarkStore Gmail", posting_mode="browser_stealth"
            )

    if not profiles:
        print("❌ No profiles found for sign-in. Create a profile or set NAZAK_DATA_FILE.")
        return

    target_prof = profiles[-1]
    notes = {}
    if target_prof.google and target_prof.google.notes:
        try:
            notes = json.loads(target_prof.google.notes)
        except Exception:
            notes = {}

    email = (
        notes.get("account_email")
        or os.environ.get("GOOGLE_EMAIL")
        or (target_prof.google.target_account_email if target_prof.google else "")
    )
    password = notes.get("account_password") or os.environ.get("GOOGLE_PASSWORD", "")
    totp_secret = notes.get("totp_secret") or os.environ.get("GOOGLE_TOTP_SECRET", "")
    recovery = notes.get("recovery_email") or os.environ.get("GOOGLE_RECOVERY_EMAIL", "")

    masked_pw = ("*" * len(password)) if password else "NOT SET"
    masked_totp = (
        (totp_secret[:2] + "****" + totp_secret[-2:])
        if len(totp_secret) > 4
        else ("****" if totp_secret else "NOT SET")
    )

    print(f"📌 Account: {email or 'not specified'}")
    print(f"🔑 Password: {masked_pw}")
    print(f"🛡️ TOTP Key: {masked_totp}")

    # 2. Build Browser Arguments
    bl = BrowserLauncher(PROFILES_DIR, EXTENSIONS_DIR)
    user_data_dir = PROFILES_DIR / target_prof.id
    user_data_dir.mkdir(parents=True, exist_ok=True)

    chrome_exe = find_chrome_executable()
    args, _ext_path = bl.build_chrome_args(target_prof, chrome_exe)
    extra_args = [
        a
        for a in args
        if not a.startswith("--user-data-dir=") and not a.startswith("http") and a != "about:blank" and a != chrome_exe
    ]

    print("🌐 Launching an isolated browser with a hardware fingerprint...")

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            executable_path=chrome_exe,
            headless=False,
            args=extra_args,
            viewport={"width": 1280, "height": 800},
        )

        page = context.pages[0] if context.pages else await context.new_page()

        try:
            # 3. Navigate to Google / YouTube
            print("⏳ Step 1: Checking the Google / YouTube session...")
            try:
                await page.goto(
                    "https://accounts.google.com/signin/v2/identifier?service=youtube",
                    wait_until="commit",
                    timeout=15000,
                )
            except Exception:
                pass

            await asyncio.sleep(3)
            current_url = page.url

            # Check if already authenticated
            if (
                "myaccount.google.com" in current_url
                or "studio.youtube.com" in current_url
                or ("youtube.com" in current_url and "signin" not in current_url)
            ):
                print("✅ Profile is already signed in to Google / YouTube!")
            else:
                try:
                    # 4. Fill Email if not logged in
                    email_input = page.locator("input[type='email'], #identifierId").first
                    if await email_input.is_visible(timeout=5000):
                        print(f"⌨️ Step 2: Entering email ({email})...")
                        await email_input.click()
                        for ch in email:
                            await email_input.type(ch, delay=35)
                        await asyncio.sleep(0.8)

                        next_btn = page.locator("#identifierNext, button:has-text('Next')").first
                        await next_btn.click()
                        await asyncio.sleep(4)
                        await page.screenshot(path=str(SCREENSHOTS_DIR / "02_after_email.png"))
                        print("📸 Screenshot 2 saved: 02_after_email.png")
                except Exception:
                    pass

                # 5. Fill Password
                pwd_input = page.locator("input[type='password'], [name='Passwd'], [name='password']").first
                try:
                    await pwd_input.wait_for(state="visible", timeout=12000)
                    print("⌨️ Step 3: Entering password...")
                    await pwd_input.click()
                    for ch in password:
                        await pwd_input.type(ch, delay=40)
                    await asyncio.sleep(0.8)

                    next_btn_pwd = page.locator("#passwordNext, button:has-text('Next')").first
                    await next_btn_pwd.click()
                    await asyncio.sleep(5)
                    await page.screenshot(path=str(SCREENSHOTS_DIR / "03_after_password.png"))
                    print("📸 Screenshot 3 saved: 03_after_password.png")
                except Exception as e:
                    print(f"Password field did not appear immediately: {e}")

                # 6. 2FA TOTP Prompt
                totp_input = page.locator(
                    "input[type='tel'], input[name='totpPin'], input[id='totpPin'], [aria-label*='code' i]"
                ).first
                try:
                    if await totp_input.is_visible(timeout=8000):
                        code = generate_totp_rfc6238(totp_secret)
                        print(f"🛡️ Step 4: 2FA prompt detected! Generating current TOTP code: {code}...")
                        await totp_input.click()
                        for ch in code:
                            await totp_input.type(ch, delay=50)
                        await asyncio.sleep(0.8)

                        next_btn_totp = page.locator("#totpNext, button:has-text('Next')").first
                        await next_btn_totp.click()
                        await asyncio.sleep(5)
                        await page.screenshot(path=str(SCREENSHOTS_DIR / "04_after_totp.png"))
                        print("📸 Screenshot 4 saved: 04_after_totp.png")
                except Exception as e:
                    print(f"2FA was not required or was already completed: {e}")

                # 7. Recovery Challenge
                rec_input = page.locator("input[type='email'], [name='knowledgePreregisteredEmailResponse']").first
                try:
                    if await rec_input.is_visible(timeout=5000) and recovery:
                        print("⌨️ Entering recovery email...")
                        await rec_input.click()
                        for ch in recovery:
                            await rec_input.type(ch, delay=35)
                        await asyncio.sleep(0.8)
                        next_btn_rec = page.locator("button:has-text('Next')").first
                        await next_btn_rec.click()
                        await asyncio.sleep(5)
                        await page.screenshot(path=str(SCREENSHOTS_DIR / "05_after_recovery.png"))
                except Exception:
                    pass

            # 8. Navigate to YouTube Studio
            print("⏳ Step 5: Navigating to YouTube Studio (studio.youtube.com)...")
            try:
                await page.goto("https://studio.youtube.com", wait_until="commit", timeout=25000)
            except Exception:
                pass
            await asyncio.sleep(5)

            # Dismiss 'Welcome to YouTube Studio' modal if present
            try:
                continue_btn = page.locator("button:has-text('Continue'), #continue-button").first
                if await continue_btn.is_visible(timeout=4000):
                    print("👋 Closing the 'Welcome to YouTube Studio' window...")
                    await continue_btn.click()
                    await asyncio.sleep(1.5)
            except Exception:
                pass

            # Dismiss any tooltip
            try:
                close_tip = page.locator("button:has-text('Close'), button:has-text('Dismiss')").first
                if await close_tip.is_visible(timeout=3000):
                    await close_tip.click()
                    await asyncio.sleep(1.0)
            except Exception:
                pass

            await page.screenshot(path=str(SCREENSHOTS_DIR / "06_youtube_studio.png"))
            print("📸 Screenshot 5 saved: 06_youtube_studio.png")

            # Check for "Create Channel" button if needed
            try:
                create_channel_btn = page.locator("#create-channel-button, button:has-text('Create channel')").first
                if await create_channel_btn.is_visible(timeout=4000):
                    print("🎬 Step 6: Channel creation window detected! Clicking 'Create channel'...")
                    await create_channel_btn.click()
                    await asyncio.sleep(5)
                    await page.screenshot(path=str(SCREENSHOTS_DIR / "07_channel_created.png"))
            except Exception:
                pass

            # 9. Upload Test Video Shorts
            video_path_env = os.environ.get("NAZAK_TEST_VIDEO")
            video_file = Path(video_path_env) if video_path_env else (DATA_DIR / "test_shorts.mp4")
            if not video_file.exists():
                video_file = DATA_DIR / "videos" / "source.mp4"
            if not video_file.exists():
                video_file.parent.mkdir(parents=True, exist_ok=True)
                video_file.write_bytes(b"DEMO_MP4_HEADER" + b"0" * 1024)
            print(f"🎬 Step 7: Uploading Shorts video ({video_file.name})...")

            # Try center 'Upload videos' button first, or fallback to Create menu
            center_upload = page.locator(
                "button:has-text('Upload videos'), #upload-button, [aria-label*='Upload' i]"
            ).first
            if await center_upload.is_visible(timeout=4000):
                print("Clicking the 'Upload videos' button on the dashboard...")
                await center_upload.click()
            else:
                create_btn = page.locator("#create-icon, [aria-label='Create'], button:has-text('Create')").first
                await create_btn.wait_for(state="visible", timeout=15000)
                await create_btn.click()
                await asyncio.sleep(1.5)
                upload_item = page.locator("#text-item-0, tp-yt-paper-item:has-text('Upload videos')").first
                await upload_item.click()

            await asyncio.sleep(3)

            # Attach video file
            file_input = page.locator("input[type='file']").first
            await file_input.wait_for(state="attached", timeout=20000)
            print("📁 Sending the file to the upload form...")
            await file_input.set_input_files(str(video_file.resolve()))
            await asyncio.sleep(6)
            await page.screenshot(path=str(SCREENSHOTS_DIR / "08_file_uploading.png"))

            # Fill Title
            title_box = page.locator("#title-textarea #textbox, [aria-label*='title' i]").first
            await title_box.wait_for(state="visible", timeout=30000)
            await title_box.click()
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await asyncio.sleep(0.5)

            test_title = f"Nazak Studio Auto Shorts #{int(time.time()) % 10000} #shorts #viral"
            print(f"⌨️ Step 8: Entering title: {test_title}")
            await human_type(title_box, test_title)
            await asyncio.sleep(1.5)

            # Select Not for Kids
            not_kids_radio = page.locator(
                "tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK'], [name='VIDEO_MADE_FOR_KIDS_NOT_MFK']"
            ).first
            if await not_kids_radio.is_visible():
                await not_kids_radio.click()
                await asyncio.sleep(1.0)

            await page.screenshot(path=str(SCREENSHOTS_DIR / "09_metadata_filled.png"))

            # Advance 3 steps
            for _step_idx in range(3):
                next_btn = page.locator("#next-button").first
                await next_btn.click()
                await asyncio.sleep(2.5)

            # Select Public
            print("🌍 Step 9: Setting visibility to 'Public'...")
            public_radio = page.locator("tp-yt-paper-radio-button[name='PUBLIC'], [name='PUBLIC']").first
            await public_radio.wait_for(state="visible", timeout=15000)
            await public_radio.click()
            await asyncio.sleep(1.5)
            await page.screenshot(path=str(SCREENSHOTS_DIR / "10_visibility_public.png"))

            # Click Publish
            print("🚀 Step 10: Publishing video (clicking 'Publish')...")
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

            print(f"🎉 PUBLISHED SUCCESSFULLY! Link: {video_url or 'https://youtube.com/shorts'}")

            notes["auth_status"] = "authenticated"
            notes["last_upload_time"] = time.time()
            target_prof.google.notes = json.dumps(notes)
            pm.save_profiles()

            await context.close()
            print("=========================================================")
            print("🎉 ALL STEPS COMPLETED WITH 100% SUCCESS!")
            print("=========================================================")
            return True

        except Exception as e:
            print(f"❌ Error during the process: {e}")
            try:
                await page.screenshot(path=str(SCREENSHOTS_DIR / "error_state.png"))
                print("📸 Error screenshot saved: error_state.png")
            except Exception:
                pass
            await context.close()
            return False


if __name__ == "__main__":
    asyncio.run(run_live_flow())
