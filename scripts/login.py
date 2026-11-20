from __future__ import annotations

import argparse
import asyncio
import base64
import gzip
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from playwright.async_api import async_playwright

from app.config import MAX_STORAGE_STATE_BYTES, PACKED_STORAGE_STATE_PREFIX


DOUYIN_URL = "https://www.douyin.com/"
GITHUB_SECRET_LIMIT = 48 * 1024


def export_github_state() -> None:
    state = Path("storage-state.json").read_bytes()
    if len(state) > MAX_STORAGE_STATE_BYTES:
        raise ValueError("登录状态超过程序支持的大小")
    packed = PACKED_STORAGE_STATE_PREFIX + base64.b64encode(gzip.compress(state, mtime=0)).decode("ascii")
    if len(packed) > GITHUB_SECRET_LIMIT:
        raise ValueError("压缩后的登录状态仍超过 GitHub Secret 的 48 KB 上限")
    output = Path("storage-state-github.txt")
    temporary = output.with_suffix(".txt.tmp")
    temporary.write_text(packed, encoding="ascii")
    temporary.replace(output)
    print(f"GitHub 登录状态已保存到 {output}（{len(packed)} 字节）")


async def login() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context(locale="zh-CN")
        page = await context.new_page()
        await page.goto(DOUYIN_URL, wait_until="domcontentloaded")
        await _open_login(page)
        print("请在浏览器中扫码登录。登录完成并看到抖音首页后，回到终端按 Enter。")
        await asyncio.to_thread(input)
        await page.goto(DOUYIN_URL, wait_until="domcontentloaded")
        await _verify_home_login(page)
        await context.storage_state(path="storage-state.json.tmp")
        await browser.close()
        Path("storage-state.json.tmp").replace("storage-state.json")
        print("登录状态已保存到 storage-state.json")


async def _open_login(page) -> None:
    login = page.get_by_text("登录", exact=True)
    if await login.count():
        try:
            await login.first.click(timeout=10_000)
        except Exception:
            pass

    qr_login = page.get_by_text("扫码登录", exact=True)
    if await qr_login.count():
        try:
            await qr_login.first.click(timeout=5_000)
        except Exception:
            pass


async def _verify_home_login(page) -> None:
    login = page.get_by_text("登录", exact=True)
    if await login.count() and await login.first.is_visible():
        raise RuntimeError("未检测到登录成功，请重新运行并完成扫码确认")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-github", action="store_true", help="将当前 storage-state.json 无损导出为 GitHub Secret")
    if parser.parse_args().export_github:
        try:
            export_github_state()
        except (OSError, ValueError) as exc:
            parser.exit(1, f"导出失败：{exc}\n")
    else:
        asyncio.run(login())
