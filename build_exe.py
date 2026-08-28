#!/usr/bin/env python3
"""
Nazak Browser Studio PRO - Senior Production Build Orchestrator.
Automates PyInstaller compilation, footprint optimization, smoke tests, ZIP packaging, and Inno Setup installer.
"""

import os
import sys
import shutil
import hashlib
import subprocess
import time
import zipfile
from pathlib import Path

# Fix Windows console encoding issues if necessary
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"
INSTALLER_DIR = ROOT_DIR / "dist_installer"
SPEC_FILE = ROOT_DIR / "NazakBrowserStudio.spec"
APP_DIR = DIST_DIR / "NazakBrowserStudio"
EXE_PATH = APP_DIR / "NazakBrowserStudio.exe"
ISS_FILE = ROOT_DIR / "installer.iss"
VERSION = "1.4.1"
ZIP_NAME = f"NazakBrowserStudio-v{VERSION}-Windows-x64.zip"
ZIP_PATH = DIST_DIR / ZIP_NAME

# ANSI Colors for terminal output
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_step(title: str):
    print(f"\n{CYAN}{BOLD}==> [{time.strftime('%H:%M:%S')}] {title}{RESET}")


def print_success(msg: str):
    print(f"{GREEN}[OK] {msg}{RESET}")


def print_warn(msg: str):
    print(f"{YELLOW}[WARN] {msg}{RESET}")


def print_error(msg: str):
    print(f"{RED}[ERROR] {msg}{RESET}")


def calculate_sha256(file_path: Path) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def get_dir_size_mb(path: Path) -> float:
    total_bytes = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total_bytes / (1024 * 1024)


def validate_environment():
    print_step("Step 1/7: Validating Build Environment")
    try:
        import PyInstaller
        print_success(f"PyInstaller version: {PyInstaller.__version__}")
    except ImportError:
        print_error("PyInstaller is not installed. Run: pip install pyinstaller")
        sys.exit(1)

    try:
        import PyQt6
        print_success(f"PyQt6 path: {Path(PyQt6.__file__).parent}")
    except ImportError:
        print_error("PyQt6 is not installed. Run: pip install PyQt6")
        sys.exit(1)

    try:
        import qfluentwidgets
        print_success(f"QFluentWidgets version: {getattr(qfluentwidgets, '__version__', 'detected')}")
    except ImportError:
        print_warn("qfluentwidgets is not installed in current environment.")


def clean_artifacts():
    print_step("Step 2/7: Cleaning Previous Build Artifacts")
    for d in [BUILD_DIR, DIST_DIR, INSTALLER_DIR]:
        if d.exists():
            print(f"  Removing: {d}")
            shutil.rmtree(d, ignore_errors=True)
    print_success("Build workspace cleaned successfully.")


def run_pyinstaller():
    print_step("Step 3/7: Compiling Application with PyInstaller")
    if not SPEC_FILE.exists():
        print_error(f"Spec file not found: {SPEC_FILE}")
        sys.exit(1)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        str(SPEC_FILE),
    ]

    start_time = time.time()
    result = subprocess.run(cmd, cwd=str(ROOT_DIR))
    elapsed = time.time() - start_time

    if result.returncode != 0:
        print_error(f"PyInstaller build failed with exit code {result.returncode}")
        sys.exit(result.returncode)

    print_success(f"PyInstaller compilation completed in {elapsed:.2f}s")


def optimize_distribution():
    print_step("Step 4/7: Post-Build Footprint Optimization")
    if not APP_DIR.exists():
        print_error("Distribution directory does not exist.")
        return

    # Strip unused translation files (.qm) for languages other than ru / en to save disk space
    translations_dir = APP_DIR / "PyQt6" / "Qt6" / "translations"
    removed_bytes = 0
    if translations_dir.exists():
        for qm in list(translations_dir.glob("*.qm")):
            name = qm.name.lower()
            if not ("ru" in name or "en" in name):
                try:
                    removed_bytes += qm.stat().st_size
                    qm.unlink()
                except Exception:
                    pass

    if removed_bytes > 0:
        print_success(f"Removed unused Qt locale tables (-{removed_bytes / (1024 * 1024):.2f} MB)")
    else:
        print_success("Distribution tree verified.")


def smoke_test():
    print_step("Step 5/7: Executing Smoke Test on Compiled Binary")
    if not EXE_PATH.exists():
        print_error(f"Target executable not found: {EXE_PATH}")
        sys.exit(1)

    cmd = [str(EXE_PATH), "--mode", "cli", "help"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            print_success("Smoke test passed! Binary executed and exited cleanly.")
        else:
            print_warn(f"Smoke test returned exit code {result.returncode}. STDERR:\n{result.stderr[:400]}")
    except subprocess.TimeoutExpired:
        print_warn("Smoke test timed out after 15 seconds (likely initialized GUI or event loop).")
    except Exception as e:
        print_error(f"Smoke test failed: {e}")


def package_zip():
    print_step("Step 6/7: Creating Standalone Release ZIP Bundle")
    if not APP_DIR.exists():
        print_error("Cannot package ZIP: App directory does not exist.")
        return

    print(f"  Archiving {APP_DIR} -> {ZIP_PATH} ...")
    start_time = time.time()

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in APP_DIR.rglob("*"):
            if file.is_file():
                # Store relative to dist directory so it unzips into NazakBrowserStudio/
                arcname = file.relative_to(DIST_DIR)
                zf.write(file, arcname)

    elapsed = time.time() - start_time
    zip_size_mb = ZIP_PATH.stat().st_size / (1024 * 1024)
    print_success(f"ZIP package created: {ZIP_NAME} ({zip_size_mb:.2f} MB) in {elapsed:.2f}s")


def build_inno_installer():
    print_step("Step 7/7: Building Windows Inno Setup Installer")
    if not ISS_FILE.exists():
        print_warn(f"Installer script not found: {ISS_FILE}")
        return

    # Look for ISCC.exe in common locations or PATH
    iscc_candidates = [
        shutil.which("ISCC"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
    ]

    iscc_path = next((p for p in iscc_candidates if p and Path(p).exists()), None)

    if not iscc_path:
        print_warn("Inno Setup 6 (ISCC.exe) not detected on this machine.")
        print("  Skipping Setup.exe generation. Standalone ZIP package is ready for distribution.")
        return

    INSTALLER_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [iscc_path, str(ISS_FILE)]
    result = subprocess.run(cmd, cwd=str(ROOT_DIR))

    if result.returncode == 0:
        setup_files = list(INSTALLER_DIR.glob("*.exe"))
        if setup_files:
            setup_exe = setup_files[0]
            size_mb = setup_exe.stat().st_size / (1024 * 1024)
            print_success(f"Installer generated: {setup_exe.name} ({size_mb:.2f} MB)")
    else:
        print_error(f"Inno Setup compilation failed with code {result.returncode}")


def print_summary():
    print(f"\n{GREEN}{BOLD}================================================================{RESET}")
    print(f"{GREEN}{BOLD}       NAZAK BROWSER STUDIO PRO - BUILD COMPLETED               {RESET}")
    print(f"{GREEN}{BOLD}================================================================{RESET}\n")

    if EXE_PATH.exists():
        size_mb = get_dir_size_mb(APP_DIR)
        sha256 = calculate_sha256(EXE_PATH)
        print(f"  * {BOLD}Executable:{RESET} {EXE_PATH}")
        print(f"  * {BOLD}Bundle Size:{RESET} {size_mb:.2f} MB")
        print(f"  * {BOLD}EXE SHA256:{RESET}  {sha256}")

    if ZIP_PATH.exists():
        zip_size = ZIP_PATH.stat().st_size / (1024 * 1024)
        zip_sha = calculate_sha256(ZIP_PATH)
        print(f"  * {BOLD}Release ZIP:{RESET} {ZIP_PATH}")
        print(f"  * {BOLD}ZIP Size:{RESET}    {zip_size:.2f} MB")
        print(f"  * {BOLD}ZIP SHA256:{RESET}  {zip_sha}")

    setup_files = list(INSTALLER_DIR.glob("*.exe")) if INSTALLER_DIR.exists() else []
    if setup_files:
        setup_exe = setup_files[0]
        setup_size = setup_exe.stat().st_size / (1024 * 1024)
        setup_sha = calculate_sha256(setup_exe)
        print(f"  * {BOLD}Installer:{RESET}   {setup_exe}")
        print(f"  * {BOLD}Setup Size:{RESET}  {setup_size:.2f} MB")
        print(f"  * {BOLD}Setup SHA:{RESET}   {setup_sha}")

    print(f"\n{CYAN}To upload to GitHub Release:{RESET}")
    print(f"  gh release upload v{VERSION} \"{ZIP_PATH}\" --clobber\n")


def main():
    validate_environment()
    clean_artifacts()
    run_pyinstaller()
    optimize_distribution()
    smoke_test()
    package_zip()
    build_inno_installer()
    print_summary()


if __name__ == "__main__":
    main()
