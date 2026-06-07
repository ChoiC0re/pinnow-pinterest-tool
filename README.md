# pinnow

Pinterest 보드 및 핀 이미지를 로컬에 저장하는 macOS/Windows 데스크탑 앱

![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 다운로드

**[최신 릴리즈 →](https://github.com/ChoiC0re/pinnow-pinterest-tool/releases/latest)**

| 환경 | 파일 |
|------|------|
| macOS (Apple Silicon · Sequoia / Tahoe) | `pinnow-mac-arm64.zip` |
| Windows 10 / 11 (x64) | `pinnow-windows.zip` |

> Intel Mac은 현재 미지원입니다.

---

## 설치 및 실행

### macOS

1. zip 압축 해제
2. `pinnow.app` **우클릭 → 열기**
   (더블클릭 시 Gatekeeper 차단 — 반드시 우클릭으로 열기)
3. "확인되지 않은 개발자" 경고 → **열기** 클릭
4. 최초 실행 시 Chromium 브라우저 자동 설치 (약 150 MB, 1~2분 소요)

> macOS에서 "손상되었기 때문에 열 수 없음" 또는 "확인할 수 없음"이 나오면 Finder에서 우클릭 → 열기를 다시 시도하세요. 그래도 막히면 터미널에서 `xattr -cr /path/to/pinnow.app` 실행 후 다시 여세요.

### Windows

1. zip 압축 해제
2. `pinnow` 폴더 안의 `pinnow.exe` 실행
3. "Windows의 PC 보호" 경고 → **추가 정보 → 실행** 클릭
4. 최초 실행 시 Chromium 브라우저 자동 설치 (약 150 MB, 1~2분 소요)

> Windows에서는 압축 파일 안에서 바로 실행하지 말고 반드시 먼저 압축을 푼 뒤 실행하세요. 첫 실행 중 방화벽/SmartScreen 경고가 뜰 수 있습니다.

### 첫 실행 참고

- 앱은 Chromium과 로그인 세션을 사용자 폴더에 저장합니다.
  - macOS: `~/Library/Application Support/pinnow`, `~/Library/Caches/pinnow`
  - Windows: `%APPDATA%\ChoiC0re\pinnow`, `%LOCALAPPDATA%\ChoiC0re\pinnow`
- 이미 실행 중인 `pinnow`가 있으면 새 창을 추가로 열지 않습니다.

---

## 사용법

1. Pinterest 보드 URL 또는 핀 URL 붙여넣기
2. 저장 위치 선택
3. **다운로드 시작** 클릭

**지원 URL 형식**
```
https://www.pinterest.com/username/board-name/
https://www.pinterest.com/pin/123456789/
https://pin.it/xxxxxxx
```

---

## 알려진 제한

- Pinterest API가 반환하는 최대 핀 수는 보드 크기와 무관하게 제한될 수 있습니다
- 누락된 핀은 다운로드 완료 후 `failed_pins.txt`에 Pinterest 링크로 저장됩니다
- Apple Silicon(arm64) 전용 빌드 — Intel Mac 미지원

---

## 소스에서 빌드

```bash
git clone https://github.com/ChoiC0re/pinnow-pinterest-tool.git
cd pinnow-pinterest-tool

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium

# 실행
python pinnow_app.py

# 앱 빌드
pyinstaller pinnow.spec --noconfirm
```

---

## CLI 사용법

```bash
# 보드 전체 다운로드
python pinnow.py board https://www.pinterest.com/username/board/ -o ./downloads -n 999

# 핀 단건 다운로드
python pinnow.py pin https://www.pinterest.com/pin/123456789/ -o ./downloads
```

---

## 기술 스택

- [PyQt6](https://pypi.org/project/PyQt6/) — GUI
- [Playwright](https://playwright.dev/python/) — 보드 스캔 (무한스크롤 처리)
- [PyInstaller](https://pyinstaller.org/) — 앱 패키징
- GitHub Actions — macOS / Windows 자동 빌드
