"""Record a real Playwright browser walkthrough (.webm, .mp4, .gif) of the SUT & HTML report."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import expect, sync_playwright

from sut.app import create_app
from sut.config import SutSettings


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _find_ffmpeg() -> str | None:
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    local_app = os.getenv("LOCALAPPDATA")
    if local_app:
        candidates = sorted(
            (Path(local_app) / "ms-playwright").glob("ffmpeg*/ffmpeg*.exe"),
            reverse=True,
        )
        if candidates:
            return str(candidates[0])
    posix_cache = Path.home() / ".cache" / "ms-playwright"
    if posix_cache.exists():
        candidates = sorted(posix_cache.glob("ffmpeg*/ffmpeg*"), reverse=True)
        for c in candidates:
            if c.is_file() and os.access(c, os.X_OK):
                return str(c)
    return None


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    images_dir = root / "docs" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    report_html = root / "reports" / "qa-report.html"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        video_dir = tmp_path / "videos"
        video_dir.mkdir(parents=True, exist_ok=True)

        settings = SutSettings(
            db_path=str(tmp_path / "walkthrough.sqlite3"),
            rate_limit_max_requests=500,
            pbkdf2_iterations=1_000,
        )
        app = create_app(settings=settings)
        port = _free_port()
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        while not server.started:
            time.sleep(0.05)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    record_video_dir=str(video_dir),
                    record_video_size={"width": 1280, "height": 720},
                )
                page = context.new_page()
                base_url = f"http://127.0.0.1:{port}"

                page.goto(base_url, wait_until="networkidle")
                page.wait_for_timeout(500)

                page.get_by_test_id("tab-register").click()
                page.wait_for_timeout(300)
                page.get_by_test_id("reg-name").fill("Anwar Staff QA")
                page.get_by_test_id("reg-email").fill("walkthrough@aegispay.dev")
                page.get_by_test_id("reg-password").fill("StaffQaPass123!")
                page.wait_for_timeout(350)
                page.get_by_test_id("register-submit").click()
                expect(page.get_by_test_id("metric-balance")).to_have_text("$0.00")
                page.wait_for_timeout(500)

                page.get_by_test_id("deposit-amount").fill("750.00")
                page.get_by_test_id("deposit-ref").fill("ci-treasury-seed")
                page.get_by_test_id("deposit-submit").click()
                expect(page.get_by_test_id("metric-balance")).to_have_text("$750.00")
                page.wait_for_timeout(550)

                page.get_by_test_id("order-recipient").fill("cloud-gpu@infra.dev")
                page.get_by_test_id("order-amount").fill("220.00")
                page.get_by_test_id("order-memo").fill("CI Runner Cluster")
                page.get_by_test_id("order-idem").fill("demo-order-01")
                page.get_by_test_id("order-submit").click()
                expect(page.get_by_test_id("metric-balance")).to_have_text("$530.00")
                page.wait_for_timeout(550)

                page.get_by_test_id("order-recipient").fill("vendor-eu@acme.io")
                page.get_by_test_id("order-amount").fill("85.50")
                page.get_by_test_id("order-currency").select_option("EUR")
                page.get_by_test_id("order-memo").fill("Security Audit Tooling")
                page.get_by_test_id("order-submit").click()
                expect(page.get_by_test_id("metric-balance")).to_have_text("$444.50")
                page.wait_for_timeout(600)

                # Cancel the most recent order and verify refund
                page.locator("[data-testid^='cancel-order-']").first.click()
                expect(page.get_by_test_id("metric-balance")).to_have_text("$530.00")
                page.wait_for_timeout(700)

                # Navigate to the generated HTML QA Telemetry Report
                if report_html.exists():
                    page.goto(report_html.as_uri(), wait_until="load")
                    page.wait_for_timeout(800)
                    page.evaluate("window.scrollTo({ top: 420, behavior: 'smooth' })")
                    page.wait_for_timeout(900)

                video = page.video
                context.close()
                browser.close()
                assert video is not None
                recorded_webm = Path(video.path())
                target_webm = images_dir / "qa-walkthrough.webm"
                shutil.copy2(recorded_webm, target_webm)
        finally:
            server.should_exit = True
            thread.join(timeout=5.0)
            app.state.db.close()

    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        target_mp4 = images_dir / "qa-walkthrough.mp4"
        target_gif = images_dir / "qa-walkthrough.gif"
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(images_dir / "qa-walkthrough.webm"),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "26",
                str(target_mp4),
            ],
            check=False,
            capture_output=True,
        )
        if not target_mp4.exists() or target_mp4.stat().st_size == 0:
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(images_dir / "qa-walkthrough.webm"),
                    "-c:v",
                    "mpeg4",
                    "-q:v",
                    "5",
                    str(target_mp4),
                ],
                check=False,
                capture_output=True,
            )

        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(images_dir / "qa-walkthrough.webm"),
                "-vf",
                "fps=10,scale=960:-1:flags=lanczos,split[s0][s1];"
                "[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer",
                str(target_gif),
            ],
            check=False,
            capture_output=True,
        )

    for artifact in sorted(images_dir.glob("qa-walkthrough.*")):
        size_kb = artifact.stat().st_size / 1024.0
        print(f"Walkthrough artifact: {artifact.name} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
