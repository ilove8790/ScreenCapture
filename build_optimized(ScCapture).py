import PyInstaller.__main__
import os

# ============================================================
# ScrCapture.py 실제 사용 라이브러리 분석
# ============================================================
# [필수 포함]
#   - tkinter          : GUI 프레임워크 (내장)
#   - PIL (Pillow)     : ImageGrab, Image, ImageTk - 이미지 캡처/표시
#   - ctypes           : Windows API (클립보드, DPI, 모니터 정보)
#   - ctypes.wintypes  : HWND, RECT 등 Win32 타입
#   - threading        : MP4/GIF 녹화 백그라운드 스레드
#   - os               : 디렉터리 생성 (Recordings 폴더)
#   - datetime         : 녹화 파일명 타임스탬프
#   - io               : 클립보드 DIB 바이트 버퍼
#   - time             : FPS 제어 sleep
#   - sys              : 플랫폼 체크 (win32 DPI 설정)
#   - cv2 (opencv)     : MP4 VideoWriter (try/except 선택적 사용)
#   - numpy            : cv2와 함께 BGR 변환
# ============================================================
# [전혀 사용 안 함 → 제외 대상]
#   - PySide6 / PyQt5 / PyQt6 : Qt GUI (미사용, 매우 큰 용량)
#   - matplotlib               : 그래프 라이브러리 (미사용)
#   - scipy                    : 과학 계산 (미사용)
#   - pandas                   : 데이터 분석 (미사용)
#   - sqlalchemy / sqlite3 등  : DB 관련 (미사용)
#   - sklearn / tensorflow 등  : ML 라이브러리 (미사용)
#   - cryptography / paramiko  : 암호화/네트워크 (미사용)
#   - wx                       : wxPython GUI (미사용)
#   - IPython / jupyter        : 노트북 환경 (미사용)
#   - win32com                 : COM 자동화 (미사용)
# ============================================================


def build_optimized():
    script_name = "ScrCapture(0624).py"
    exe_name = "ScreenCapture"

    # 빌드 기준 디렉터리 (이 스크립트가 있는 폴더)
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # capture.ico 절대 경로
    ico_file = os.path.join(base_dir, "capture.ico")
    if not os.path.exists(ico_file):
        print(f"[경고] 아이콘 파일을 찾을 수 없습니다: {ico_file}")
        print("       capture.ico 파일을 같은 폴더에 넣고 다시 실행하세요.")
        return

    # PyInstaller에 전달할 경로 (--add-data는 절대경로;. 형식)
    add_data_ico = f"{ico_file};."

    params = [
        script_name,
        "--onefile",
        "--windowed",
        f"--name={exe_name}",
        "--clean",
        f"--icon={ico_file}",          # EXE 파일 자체 아이콘
        f"--add-data={add_data_ico}",   # 런타임에 capture.ico 파일 번들

        # ── Qt 계열 전체 제외 (ScrCapture는 tkinter 기반) ──────────────
        "--exclude-module", "PySide6",
        "--exclude-module", "PyQt5",
        "--exclude-module", "PyQt6",
        "--exclude-module", "qtpy",
        "--exclude-module", "shiboken6",

        # ── 데이터 과학 / 수치 계산 (cv2, numpy 이외 불필요) ────────────
        "--exclude-module", "matplotlib",
        "--exclude-module", "scipy",
        "--exclude-module", "pandas",
        "--exclude-module", "sklearn",
        "--exclude-module", "skimage",
        "--exclude-module", "statsmodels",
        "--exclude-module", "sympy",

        # ── ML / AI ──────────────────────────────────────────────────────
        "--exclude-module", "tensorflow",
        "--exclude-module", "torch",
        "--exclude-module", "keras",

        # ── 네트워크 / 암호화 ─────────────────────────────────────────────
        "--exclude-module", "cryptography",
        "--exclude-module", "paramiko",
        "--exclude-module", "requests",
        "--exclude-module", "urllib3",
        "--exclude-module", "aiohttp",

        # ── 데이터베이스 ──────────────────────────────────────────────────
        "--exclude-module", "sqlalchemy",
        "--exclude-module", "psycopg2",
        "--exclude-module", "pymysql",

        # ── GUI (tkinter 외) ──────────────────────────────────────────────
        "--exclude-module", "wx",
        "--exclude-module", "gi",            # GTK

        # ── 개발 도구 / 노트북 환경 ───────────────────────────────────────
        "--exclude-module", "IPython",
        "--exclude-module", "jupyter",
        "--exclude-module", "notebook",
        "--exclude-module", "pytest",
        "--exclude-module", "setuptools",
        "--exclude-module", "distutils",
        "--exclude-module", "docutils",
        "--exclude-module", "Sphinx",

        # ── Windows COM / 기타 불필요 모듈 ───────────────────────────────
        "--exclude-module", "win32com",
        "--exclude-module", "pywintypes",    # pywin32 (ctypes로 대체)
        "--exclude-module", "email",
        "--exclude-module", "html",
        "--exclude-module", "http",
        "--exclude-module", "xml",
        "--exclude-module", "xmlrpc",
        "--exclude-module", "ftplib",
        "--exclude-module", "imaplib",
        "--exclude-module", "smtplib",
        "--exclude-module", "poplib",
        "--exclude-module", "telnetlib",
        "--exclude-module", "multiprocessing",
        "--exclude-module", "concurrent",
        "--exclude-module", "asyncio",
        "--exclude-module", "unittest",
    ]

    print("====================================================")
    print(f" Starting Optimized PyInstaller Build for {exe_name}")
    print("====================================================")
    print()
    print(f"[빌드 대상] {script_name}")
    print(f"[아이콘   ] {ico_file}")
    print()
    print("[분석] ScrCapture(0624).py 실제 사용 라이브러리:")
    print("  ✅ tkinter, PIL(Pillow), ctypes, threading")
    print("  ✅ os, datetime, io, time, sys")
    print("  ✅ cv2(opencv-python), numpy  [MP4 녹화용]")
    print()
    print("[제외] PySide6/PyQt5, matplotlib, scipy, pandas 등")
    print("       불필요한 대형 패키지 전부 제외 → 용량 최소화")
    print()

    PyInstaller.__main__.run(params)

    dist_dir = "dist"
    exe_path = os.path.join(dist_dir, exe_name + ".exe")

    print("\n====================================================")
    print(" Optimized Build Completed Successfully!")
    print(f" STANDALONE EXE: {exe_path}")
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f" EXE SIZE      : {size_mb:.1f} MB")
    print("====================================================")


if __name__ == "__main__":
    build_optimized()
