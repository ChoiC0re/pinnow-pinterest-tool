#!/usr/bin/env python3
"""pinnow — Pinterest batch image downloader"""

import json
import re
import os
import time
from typing import Optional
import click
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

RESOLUTION_FALLBACKS = ["originals", "736x", "474x", "236x"]
_SCRIPT_DIR = "/Users/choi_c0re/pinnow"
COOKIES_FILE = os.path.join(_SCRIPT_DIR, "cookies.json")
BROWSER_DATA_DIR = os.path.join(_SCRIPT_DIR, "browser_data")


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def resolve_short_url(url: str) -> str:
    """pin.it 단축 URL을 실제 URL로 변환"""
    r = SESSION.head(url, allow_redirects=True, timeout=10)
    return r.url


def fetch_page(url: str) -> BeautifulSoup:
    r = SESSION.get(url, timeout=15)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def extract_pws_data(soup: BeautifulSoup) -> dict:
    """페이지 HTML에 내장된 __PWS_DATA__ JSON 추출"""
    tag = soup.find("script", {"id": "__PWS_DATA__"})
    if tag:
        return json.loads(tag.string)
    for script in soup.find_all("script"):
        text = script.string or ""
        m = re.search(r"P\.start\.start\((\{.+\})\)", text, re.DOTALL)
        if m:
            return json.loads(m.group(1))
    return {}


def best_image_url(images: dict) -> Optional[str]:
    """orig > 736x > 474x 순으로 가장 큰 이미지 URL 반환"""
    for key in ("orig", "736x", "474x", "236x"):
        if key in images:
            return images[key]["url"]
    return None


def to_resolution(url: str, res: str) -> str:
    return re.sub(r"pinimg\.com/[^/]+/", f"pinimg.com/{res}/", url)


# ── 핀 단건 ───────────────────────────────────────────────────────────────────

def get_pin_image_url(pin_url: str) -> tuple:
    """핀 URL → (이미지 URL, 핀 ID)"""
    if "pin.it" in pin_url:
        pin_url = resolve_short_url(pin_url)

    soup = fetch_page(pin_url)

    data = extract_pws_data(soup)
    if data:
        try:
            pin_data = (
                data.get("resourceResponses", [{}])[0]
                .get("response", {})
                .get("data", {})
            )
            images = pin_data.get("images", {})
            url = best_image_url(images)
            pin_id = pin_data.get("id")
            if url:
                return url, pin_id
        except (IndexError, KeyError, TypeError):
            pass

    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        m = re.search(r"/pin/(\d+)", pin_url)
        pin_id = m.group(1) if m else re.sub(r"[^a-zA-Z0-9]", "_", pin_url[-12:])
        return to_resolution(og["content"].split("?")[0], "originals"), pin_id

    return None, None


# ── 다운로드 (해상도 폴백 포함) ───────────────────────────────────────────────

def download_with_fallback(base_url: str, dest: str) -> bool:
    """originals → 736x → 474x → 236x 순으로 시도"""
    for res in RESOLUTION_FALLBACKS:
        url = to_resolution(base_url, res)
        try:
            r = SESSION.get(url, stream=True, timeout=20)
            if r.status_code == 200:
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                return True
        except Exception:
            continue
    return False


# ── 보드 핀 목록 수집 ─────────────────────────────────────────────────────────

def fetch_board_pins(board_url: str, max_pins: int) -> list:
    """
    Playwright로 BoardFeedResource API 응답을 인터셉트해 핀 전체 수집.
    browser_data/ 디렉토리가 있으면 로그인 세션을 재사용해 비공개 핀도 수집.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    normalized = re.sub(r"https?://[a-z]+\.pinterest\.com", "https://www.pinterest.com", board_url)
    logged_in = os.path.isdir(BROWSER_DATA_DIR)

    pins = []
    seen = set()

    def on_response(response):
        if "BoardFeedResource" not in response.url:
            return
        try:
            data = response.json()
            items = data.get("resource_response", {}).get("data", []) or []
            for item in items:
                pin_id = str(item.get("id", ""))
                if not pin_id or pin_id in seen:
                    continue
                images = item.get("images", {})
                img_url = best_image_url(images)
                if img_url:
                    seen.add(pin_id)
                    pins.append({"id": pin_id, "url": img_url})
        except Exception:
            pass

    with sync_playwright() as p:
        if logged_in:
            click.echo("  로그인 세션 적용됨")
            ctx = p.chromium.launch_persistent_context(
                BROWSER_DATA_DIR,
                headless=True,
                user_agent=HEADERS["User-Agent"],
                args=["--no-sandbox"],
            )
            page = ctx.new_page()
        else:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=HEADERS["User-Agent"])
            ctx.set_extra_http_headers({"Accept-Language": "ko-KR,ko;q=0.9"})
            page = ctx.new_page()

        page.on("response", on_response)

        click.echo("  브라우저로 보드 로딩 중...")
        page.goto(normalized, wait_until="domcontentloaded", timeout=30000)

        try:
            page.wait_for_selector("[data-test-id='board-feed'] a[href*='/pin/']", timeout=15000)
        except PWTimeout:
            ctx.close()
            raise click.ClickException("보드 핀을 찾을 수 없습니다. URL이 올바른지, 보드가 공개인지 확인하세요.")

        page.wait_for_timeout(1500)

        _DOM_JS = """() => {
            const feed = document.querySelector("[data-test-id='board-feed']");
            if (!feed) return [];
            const seen = new Set();
            const out = [];
            feed.querySelectorAll("a[href*='/pin/']").forEach(a => {
                const m = a.href.match(/\\/pin\\/(\\d+)/);
                if (!m || seen.has(m[1])) return;
                seen.add(m[1]);
                const img = a.querySelector("img");
                const src = img ? (img.src || "") : "";
                if (src) out.push({id: m[1], url: src});
            });
            return out;
        }"""

        def _flush_dom(page):
            for item in page.evaluate(_DOM_JS):
                pid = str(item.get("id", ""))
                raw = item.get("url", "")
                if pid and raw and pid not in seen:
                    seen.add(pid)
                    pins.append({"id": pid, "url": to_resolution(raw, "originals")})

        # 초기 DOM 스냅샷: 페이지 첫 로딩 시 소규모 보드 핀이 모두 여기에 있음
        _flush_dom(page)

        stall = 0
        prev_count = len(pins)
        bar = tqdm(desc="핀 수집", unit="핀", initial=prev_count)
        try:
            while len(pins) < max_pins:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2500)

                # 스크롤 후 DOM 스냅샷 (가상화로 새 핀이 렌더링될 수 있음)
                _flush_dom(page)

                added = len(pins) - prev_count
                if added > 0:
                    bar.update(added)
                    stall = 0
                else:
                    stall += 1
                    if stall >= 4:
                        break

                prev_count = len(pins)
        finally:
            bar.close()

        ctx.close()

    return pins[:max_pins]


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """pinnow — Pinterest 이미지 다운로더"""


@cli.command()
@click.option("--timeout", default=120, show_default=True, help="로그인 대기 시간(초)")
def login(timeout):
    """Pinterest 로그인 후 브라우저 세션 저장 (브라우저 창이 열립니다)"""
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    click.echo("브라우저가 열립니다. Pinterest에 로그인하면 자동으로 세션이 저장됩니다.")
    click.echo(f"저장 위치: {BROWSER_DATA_DIR}")
    click.echo(f"(최대 대기 {timeout}초)\n")

    os.makedirs(BROWSER_DATA_DIR, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            BROWSER_DATA_DIR,
            headless=False,
            user_agent=HEADERS["User-Agent"],
            args=["--no-sandbox"],
        )
        page = ctx.new_page()
        page.goto("https://www.pinterest.com/login/", timeout=30000)

        try:
            page.wait_for_url(
                re.compile(r"pinterest\.com(?!/login)"),
                timeout=timeout * 1000,
            )
            page.wait_for_timeout(2000)
        except PWTimeout:
            ctx.close()
            raise click.ClickException(f"{timeout}초 내에 로그인이 감지되지 않았습니다.")

        ctx.close()

    click.echo(f"세션 저장 완료 → {BROWSER_DATA_DIR}")
    click.echo(f"확인: {os.path.isdir(BROWSER_DATA_DIR)}")


@cli.command()
@click.argument("url")
@click.option("-o", "--output", default=".", help="저장 디렉토리 (기본: 현재 폴더)")
def pin(url, output):
    """핀 단건 다운로드\n\n  URL: 핀 URL 또는 pin.it 단축 URL"""
    os.makedirs(output, exist_ok=True)
    click.echo(f"핀 정보 가져오는 중: {url}")
    img_url, pin_id = get_pin_image_url(url)
    if not img_url:
        raise click.ClickException("이미지 URL을 찾을 수 없습니다.")

    clean_url = img_url.split("?")[0]
    ext = clean_url.rsplit(".", 1)[-1] or "jpg"
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(pin_id))
    dest = os.path.join(output, f"pin_{safe_id}.{ext}")

    click.echo(f"다운로드 중: {img_url}")
    if download_with_fallback(img_url, dest):
        click.echo(f"저장 완료: {dest}")
    else:
        click.echo("  ✗ 모든 해상도에서 다운로드 실패", err=True)


@cli.command()
@click.argument("board_url")
@click.option("-o", "--output", default=".", help="저장 디렉토리")
@click.option("-n", "--max-pins", default=50, show_default=True, help="최대 다운로드 핀 수")
def board(board_url, output, max_pins):
    """보드 전체 배치 다운로드\n\n  BOARD_URL: pinterest.com/username/boardname/ 형식"""
    os.makedirs(output, exist_ok=True)
    click.echo(f"보드 수집 중: {board_url}  (최대 {max_pins}개)")

    pins = fetch_board_pins(board_url, max_pins)
    if not pins:
        raise click.ClickException("핀을 찾을 수 없습니다. URL을 확인하거나 보드가 공개인지 확인하세요.")

    click.echo(f"\n{len(pins)}개 핀 다운로드 시작 → {output}/")
    ok = 0
    failed_urls = []

    for p in tqdm(pins, desc="다운로드", unit="핀"):
        ext = p["url"].split("?")[0].rsplit(".", 1)[-1] or "jpg"
        dest = os.path.join(output, f"pin_{p['id']}.{ext}")
        if os.path.exists(dest):
            ok += 1
            continue
        if download_with_fallback(p["url"], dest):
            ok += 1
        else:
            failed_urls.append(f"https://www.pinterest.com/pin/{p['id']}/")
        time.sleep(0.1)

    # 실패한 핀 목록을 파일로 저장
    if failed_urls:
        failed_path = os.path.join(output, "failed_pins.txt")
        with open(failed_path, "w") as f:
            f.write("\n".join(failed_urls) + "\n")
        click.echo(f"\n완료: 성공 {ok}개 / 실패 {len(failed_urls)}개")
        click.echo(f"실패한 핀 목록 → {failed_path}")
    else:
        click.echo(f"\n완료: 전체 {ok}개 성공")


if __name__ == "__main__":
    cli()
