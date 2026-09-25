"""Tests for advanced stealth enhancements (WebGPU, makeNative cloaking, local fonts,
speech voices, OffscreenCanvas/toBlob, OfflineAudioContext, measureText jitter, WebRTC sanitizing,
timezone injection) and organic profile history seeder.
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from nazak.api.server import app, profile_manager
from nazak.core.browser_launcher import BrowserLauncher
from nazak.core.extension_generator import generate_profile_extension
from nazak.core.history_seeder import seed_chrome_history
from nazak.core.profile_manager import ProfileManager
from nazak.models.profile import BrowserProfile, FingerprintConfig


@pytest.fixture
def test_client(tmp_path):
    mgr = ProfileManager(profiles_file=tmp_path / "profiles.json", profiles_dir=tmp_path / "profiles")
    with patch("nazak.api.server.profile_manager", mgr):
        yield TestClient(app), mgr


class TestHistorySeeder:
    def test_seed_chrome_history_creates_database(self, tmp_path):
        user_data_dir = tmp_path / "user_data"
        seeded_count = seed_chrome_history(user_data_dir, entries_count=20)

        assert seeded_count == 20
        db_path = user_data_dir / "Default" / "History"
        assert db_path.exists()

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Check urls table
        cursor.execute("SELECT COUNT(*) FROM urls")
        url_count = cursor.fetchone()[0]
        assert url_count == 20

        # Check visits table
        cursor.execute("SELECT COUNT(*) FROM visits")
        visit_count = cursor.fetchone()[0]
        assert visit_count >= 20

        # Check meta table
        cursor.execute("SELECT value FROM meta WHERE key = 'version'")
        version = cursor.fetchone()[0]
        assert int(version) >= 40

        # Verify visit timestamps are in microseconds WebKit format (> 11644473600 * 1000000)
        cursor.execute("SELECT visit_time FROM visits LIMIT 1")
        visit_time = cursor.fetchone()[0]
        assert visit_time > 11644473600 * 1000000

        conn.close()

    def test_seed_chrome_history_unique_timestamps_and_valid_transitions(self, tmp_path):
        """Audit fix P1-7 (A4): multiple visits to the same URL must NOT share
        an identical visit_time, and transitions must match real Chromium enum values."""
        from nazak.core.history_seeder import (
            PAGE_TRANSITION_CHAIN_LINK,
            PAGE_TRANSITION_CHAIN_TYPED,
            PAGE_TRANSITION_LINK,
            PAGE_TRANSITION_RELOAD,
            PAGE_TRANSITION_TYPED,
        )

        VALID_TRANSITIONS = {
            PAGE_TRANSITION_LINK,
            PAGE_TRANSITION_TYPED,
            PAGE_TRANSITION_RELOAD,
            PAGE_TRANSITION_CHAIN_TYPED,
            PAGE_TRANSITION_CHAIN_LINK,
        }

        user_data_dir = tmp_path / "user_data_quality"
        seed_chrome_history(user_data_dir, entries_count=25)
        db_path = user_data_dir / "Default" / "History"

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # 1. Transitions must all belong to the valid Chromium set
        cursor.execute("SELECT DISTINCT transition FROM visits")
        transitions_found = {row[0] for row in cursor.fetchall()}
        assert transitions_found.issubset(VALID_TRANSITIONS), f"Unexpected transitions: {transitions_found}"

        # 2. For URLs with visit_count > 1, their visits must have distinct timestamps
        cursor.execute("""
            SELECT url, COUNT(DISTINCT visit_time), COUNT(id)
            FROM visits
            GROUP BY url
            HAVING COUNT(id) > 1
        """)
        multi_visit_rows = cursor.fetchall()
        assert len(multi_visit_rows) > 0, "Seeder should generate some multi-visit URLs"
        for url_id, distinct_times, total_visits in multi_visit_rows:
            assert distinct_times == total_visits, (
                f"URL {url_id} has {total_visits} visits but only {distinct_times} distinct timestamps"
            )

        conn.close()

    def test_seed_profile_history_manager(self, tmp_path):
        mgr = ProfileManager(profiles_file=tmp_path / "profiles.json", profiles_dir=tmp_path / "profiles")
        profile = BrowserProfile(id="p_hist_test", name="History Test")
        mgr.create_profile(profile)

        seeded_count = mgr.seed_profile_history(profile.id, entries_count=15)
        assert seeded_count == 15

        history_file = mgr.profiles_dir / profile.id / "Default" / "History"
        assert history_file.exists()

    def test_api_seed_history_endpoint(self, test_client):
        client, mgr = test_client
        profile = BrowserProfile(id="p_api_seed", name="API Seeder Profile")
        mgr.create_profile(profile)

        resp = client.post(f"/api/profiles/{profile.id}/seed-history?entries_count=12")
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_id"] == profile.id
        assert data["seeded_entries"] == 12
        assert data["success"] is True

        # Non-existent profile
        resp_404 = client.post("/api/profiles/non_existent_id/seed-history")
        assert resp_404.status_code == 404


class TestAdvancedStealthEnhancements:
    def test_stealth_native_function_cloaking(self, tmp_path):
        prof = BrowserProfile(id="p_native", name="Native Cloak")
        ext_dir = Path(generate_profile_extension(prof, tmp_path))
        stealth_js = (ext_dir / "stealth.js").read_text(encoding="utf-8")

        assert "makeNative" in stealth_js
        assert "Function.prototype.toString" in stealth_js
        assert "[native code]" in stealth_js

    def test_stealth_webgpu_emulation(self, tmp_path):
        fp = FingerprintConfig(webgl_vendor="NVIDIA Corporation", webgl_renderer="NVIDIA GeForce RTX 4090")
        prof = BrowserProfile(id="p_webgpu", name="WebGPU Profile", fingerprint=fp)
        ext_dir = Path(generate_profile_extension(prof, tmp_path))
        stealth_js = (ext_dir / "stealth.js").read_text(encoding="utf-8")

        assert "navigator.gpu" in stealth_js
        assert "requestAdapter" in stealth_js
        assert "requestAdapterInfo" in stealth_js
        assert "nvidia" in stealth_js
        assert "RTX 4090" in stealth_js

    def test_stealth_local_fonts_spoofing(self, tmp_path):
        fp_win = FingerprintConfig(platform="Win32")
        p_win = BrowserProfile(id="p_win", name="Win Fonts", fingerprint=fp_win)
        stealth_win = (Path(generate_profile_extension(p_win, tmp_path / "win")) / "stealth.js").read_text(
            encoding="utf-8"
        )

        assert "queryLocalFonts" in stealth_win
        assert "Segoe UI" in stealth_win
        assert "Calibri" in stealth_win

        fp_mac = FingerprintConfig(platform="MacIntel")
        p_mac = BrowserProfile(id="p_mac", name="Mac Fonts", fingerprint=fp_mac)
        stealth_mac = (Path(generate_profile_extension(p_mac, tmp_path / "mac")) / "stealth.js").read_text(
            encoding="utf-8"
        )

        assert "San Francisco" in stealth_mac
        assert "Helvetica Neue" in stealth_mac

    def test_stealth_speech_synthesis_voices(self, tmp_path):
        fp = FingerprintConfig(platform="Win32")
        prof = BrowserProfile(id="p_speech", name="Speech Voices", fingerprint=fp)
        stealth_js = (Path(generate_profile_extension(prof, tmp_path)) / "stealth.js").read_text(encoding="utf-8")

        assert "speechSynthesis.getVoices" in stealth_js
        assert "Microsoft David" in stealth_js
        assert "Microsoft Zira" in stealth_js

    def test_stealth_offscreen_canvas_and_to_blob(self, tmp_path):
        fp = FingerprintConfig(canvas_noise=True, canvas_noise_seed=999111)
        prof = BrowserProfile(id="p_canvas_adv", name="Canvas Adv", fingerprint=fp)
        stealth_js = (Path(generate_profile_extension(prof, tmp_path)) / "stealth.js").read_text(encoding="utf-8")

        assert "OffscreenCanvasRenderingContext2D.prototype.getImageData" in stealth_js
        assert "HTMLCanvasElement.prototype.toBlob" in stealth_js

    def test_stealth_offline_audio_context(self, tmp_path):
        fp = FingerprintConfig(audio_noise=True, audio_noise_seed=0.00003)
        prof = BrowserProfile(id="p_audio_adv", name="Audio Adv", fingerprint=fp)
        stealth_js = (Path(generate_profile_extension(prof, tmp_path)) / "stealth.js").read_text(encoding="utf-8")

        assert "OfflineAudioContext.prototype.startRendering" in stealth_js
        assert "applyAudioNoise" in stealth_js

    def test_stealth_measure_text_jitter(self, tmp_path):
        fp = FingerprintConfig(client_rects_noise=True)
        prof = BrowserProfile(id="p_measure", name="Measure Text", fingerprint=fp)
        stealth_js = (Path(generate_profile_extension(prof, tmp_path)) / "stealth.js").read_text(encoding="utf-8")

        assert "CanvasRenderingContext2D.prototype.measureText" in stealth_js
        assert "fontJitter" in stealth_js

    def test_stealth_webrtc_private_ip_sanitization(self, tmp_path):
        prof = BrowserProfile(id="p_webrtc", name="WebRTC Sanitize")
        stealth_js = (Path(generate_profile_extension(prof, tmp_path)) / "stealth.js").read_text(encoding="utf-8")

        assert "sanitizeSdp" in stealth_js
        assert "RTCPeerConnection.prototype.createOffer" in stealth_js
        assert "RTCPeerConnection.prototype.setLocalDescription" in stealth_js


class TestBrowserLauncherTimezone:
    def test_time_zone_cli_arg_and_env(self, tmp_path):
        fp = FingerprintConfig(timezone="Asia/Tokyo")
        prof = BrowserProfile(id="p_tz", name="Tokyo Profile", fingerprint=fp)

        launcher = BrowserLauncher(profiles_dir=tmp_path / "profiles", extensions_dir=tmp_path / "exts")
        args, _ext = launcher.build_chrome_args(prof, chrome_exe="chrome.exe")

        assert "--time-zone-for-testing=Asia/Tokyo" in args

        # Test env injection
        with (
            patch("subprocess.Popen") as mock_popen,
            patch("nazak.core.browser_launcher.find_chrome_executable", return_value="chrome.exe"),
        ):
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.pid = 9999
            mock_popen.return_value = mock_proc

            success, pid, err = launcher.launch(prof)
            assert success is True, f"Launch failed with error: {err}"
            assert mock_popen.called
            env = mock_popen.call_args[1].get("env", {})
            assert env.get("TZ") == "Asia/Tokyo"
