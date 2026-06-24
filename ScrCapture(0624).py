import sys
import tkinter as tk
from tkinter import Toplevel
from PIL import ImageGrab, Image, ImageTk
import ctypes
import threading
import os
from datetime import datetime

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None
from ctypes import wintypes
import io

# 윈도우 다중 모니터 배율(DPI) 차이로 인한 캡처 잘림 및 좌표 왜곡 완벽 방지
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except:
            pass

# 64비트 환경에서 메모리 주소가 잘리는 오류를 방지하기 위해 반환형 명시
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

import time


def image_to_clipboard(image):
    """Pillow 이미지를 Windows 클립보드에 복사하는 순수 ctypes 함수"""
    try:
        output = io.BytesIO()
        image.convert("RGB").save(output, "BMP")
        data = output.getvalue()[14:]  # BMP 헤더 14바이트 제거 (DIB 형식 추출)

        # 클립보드가 다른 프로세스에 의해 잠겨있을 수 있으므로 재시도 로직 추가
        opened = False
        for _ in range(10):
            if user32.OpenClipboard(None):
                opened = True
                break
            time.sleep(0.05)

        if not opened:
            print("Failed to open clipboard")
            return False

        user32.EmptyClipboard()
        hCd = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        pchData = kernel32.GlobalLock(hCd)
        ctypes.memmove(pchData, data, len(data))
        kernel32.GlobalUnlock(hCd)
        res = user32.SetClipboardData(8, hCd)  # 8 = CF_DIB
        user32.CloseClipboard()
        return bool(res)
    except Exception as e:
        print("Clipboard error:", e)
        return False


class SnippingTool:
    def __init__(self, master, callback, initial_region=None):
        self.master = master
        self.callback = callback
        self.top = Toplevel(master)

        # 다중 모니터 가상 데스크톱 영역 가져오기 (Windows API)
        self.x_virtual = ctypes.windll.user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        self.y_virtual = ctypes.windll.user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
        self.w_virtual = ctypes.windll.user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        self.h_virtual = ctypes.windll.user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN

        # 전체 화면 캡처 (include_layered_windows=True 필수: 클라우드/하드웨어 가속 창 캡처용)
        self.full_img = ImageGrab.grab(all_screens=True, include_layered_windows=True)
        # 캡처를 위한 어두운 배경화면 생성
        dim_img = self.full_img.point(lambda p: p * 0.4)

        self.top.geometry(
            f"{self.w_virtual}x{self.h_virtual}+{self.x_virtual}+{self.y_virtual}"
        )
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.config(cursor="cross")

        self.dim_tk_img = ImageTk.PhotoImage(dim_img)
        self.canvas = tk.Canvas(self.top, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=tk.YES)

        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.dim_tk_img)
        self.bright_img_id = self.canvas.create_image(
            0, 0, anchor=tk.NW
        )  # 선택 영역 밝게 표시
        self.bright_tk = None

        self.rect_id = None
        self.rect_x1 = 0
        self.rect_y1 = 0
        self.rect_x2 = 0
        self.rect_y2 = 0
        self.drag_mode = "new"

        # 이전 영역이 있으면 그대로 복원하여 수정 가능하도록 설정
        if initial_region:
            self.rect_x1, self.rect_y1, self.rect_x2, self.rect_y2 = initial_region
            self.rect_id = self.canvas.create_rectangle(
                self.rect_x1,
                self.rect_y1,
                self.rect_x2,
                self.rect_y2,
                outline="red",
                width=3,
            )
            self.update_bright_area()
            self.drag_mode = "move"

        # 안내 문구 표시
        self.canvas.create_text(
            self.w_virtual // 2,
            50,
            text="마우스로 영역을 드래그하세요.\n가장자리나 모서리를 잡아 크기/위치를 조절할 수 있습니다.\n완료하려면 Enter 또는 Ctrl+3 키를 한 번 더 누르세요.",
            fill="white",
            font=("Malgun Gothic", 12, "bold"),
            justify="center",
        )

        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.top.bind("<Escape>", lambda e: self.close_cancel())
        self.top.bind("<Return>", lambda e: self.confirm_capture())
        self.top.focus_force()

    def close_cancel(self):
        self.top.destroy()
        self.callback(None, None)

    def get_drag_mode(self, x, y):
        if not self.rect_id:
            return "new", "cross"
        x1, x2 = sorted([self.rect_x1, self.rect_x2])
        y1, y2 = sorted([self.rect_y1, self.rect_y2])
        margin = 10
        on_left = abs(x - x1) <= margin
        on_right = abs(x - x2) <= margin
        on_top = abs(y - y1) <= margin
        on_bottom = abs(y - y2) <= margin
        in_x = x1 < x < x2
        in_y = y1 < y < y2

        if on_left and on_top:
            return "nw", "size_nw_se"
        if on_right and on_bottom:
            return "se", "size_nw_se"
        if on_right and on_top:
            return "ne", "size_ne_sw"
        if on_left and on_bottom:
            return "sw", "size_ne_sw"
        if on_left and in_y:
            return "w", "size_we"
        if on_right and in_y:
            return "e", "size_we"
        if on_top and in_x:
            return "n", "size_ns"
        if on_bottom and in_x:
            return "s", "size_ns"
        if in_x and in_y:
            return "move", "fleur"
        return "new", "cross"

    def update_bright_area(self):
        if not self.rect_id:
            return
        x1, x2 = sorted([self.rect_x1, self.rect_x2])
        y1, y2 = sorted([self.rect_y1, self.rect_y2])
        if x2 - x1 > 0 and y2 - y1 > 0:
            try:
                bright_crop = self.full_img.crop((x1, y1, x2, y2))
                self.bright_tk = ImageTk.PhotoImage(bright_crop)
                self.canvas.itemconfig(self.bright_img_id, image=self.bright_tk)
                self.canvas.coords(self.bright_img_id, x1, y1)
                self.canvas.tag_raise(self.rect_id)  # 테두리가 묻히지 않게 맨 위로
            except Exception:
                pass

    def on_motion(self, event):
        _, cursor = self.get_drag_mode(event.x, event.y)
        self.canvas.config(cursor=cursor)

    def on_press(self, event):
        self.drag_mode, _ = self.get_drag_mode(event.x, event.y)
        self.start_x, self.start_y = event.x, event.y
        self.orig_x1, self.orig_y1 = self.rect_x1, self.rect_y1
        self.orig_x2, self.orig_y2 = self.rect_x2, self.rect_y2

        if self.drag_mode == "new":
            self.rect_x1 = self.rect_x2 = event.x
            self.rect_y1 = self.rect_y2 = event.y
            if self.rect_id:
                self.canvas.delete(self.rect_id)
                self.canvas.itemconfig(self.bright_img_id, image="")
            self.rect_id = self.canvas.create_rectangle(
                self.rect_x1,
                self.rect_y1,
                self.rect_x2,
                self.rect_y2,
                outline="red",
                width=3,
            )

    def on_drag(self, event):
        dx, dy = event.x - self.start_x, event.y - self.start_y
        if self.drag_mode == "new":
            self.rect_x2, self.rect_y2 = event.x, event.y
        elif self.drag_mode == "move":
            self.rect_x1, self.rect_x2 = self.orig_x1 + dx, self.orig_x2 + dx
            self.rect_y1, self.rect_y2 = self.orig_y1 + dy, self.orig_y2 + dy
        else:
            if "w" in self.drag_mode:
                self.rect_x1 = self.orig_x1 + dx
            if "e" in self.drag_mode:
                self.rect_x2 = self.orig_x2 + dx
            if "n" in self.drag_mode:
                self.rect_y1 = self.orig_y1 + dy
            if "s" in self.drag_mode:
                self.rect_y2 = self.orig_y2 + dy
        if self.rect_id:
            self.canvas.coords(
                self.rect_id, self.rect_x1, self.rect_y1, self.rect_x2, self.rect_y2
            )
            self.update_bright_area()

    def on_release(self, event):
        self.rect_x1, self.rect_x2 = sorted([self.rect_x1, self.rect_x2])
        self.rect_y1, self.rect_y2 = sorted([self.rect_y1, self.rect_y2])
        if self.rect_id:
            self.canvas.coords(
                self.rect_id, self.rect_x1, self.rect_y1, self.rect_x2, self.rect_y2
            )
            self.update_bright_area()

    def confirm_capture(self):
        if not self.rect_id:
            self.close_cancel()
            return
        x1, y1, x2, y2 = self.rect_x1, self.rect_y1, self.rect_x2, self.rect_y2
        self.top.destroy()
        if x2 - x1 > 0 and y2 - y1 > 0:
            cropped = self.full_img.crop((x1, y1, x2, y2))
            self.callback(cropped, (x1, y1, x2, y2))
        else:
            self.callback(None, None)


class FloatingFrame(tk.Toplevel):
    def __init__(self, master, x1, y1, x2, y2):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)

        # 투명 창 설정 (윈도우 전용, 빨간 틀 안쪽은 클릭이 뒤로 통과됨)
        self.transparent_color = "#ff00ff"
        self.config(bg=self.transparent_color)
        self.attributes("-transparentcolor", self.transparent_color)

        w, h = x2 - x1, y2 - y1
        self.geometry(f"{w}x{h}+{x1}+{y1}")

        self.canvas = tk.Canvas(self, bg=self.transparent_color, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.create_rectangle(2, 2, w - 1, h - 1, outline="red", width=3)


class CaptureApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ScrCapture Pro")  # 작업표시줄에 표시될 이름 (기본값 "tk" 덮어쓰기)
        self.last_region = None  # 마지막 영역 좌표 저장
        self.last_image = None  # 마지막 캡처 이미지 저장 (Ctrl+7 파일 저장용)
        self.floating_frame = None  # 화면에 띄워둘 빨간 틀
        self.initUI()
        self._apply_icon()  # overrideredirect(True) 적용 후 아이콘 설정

    def _apply_icon(self):
        """overrideredirect(True) 창에도 아이콘을 표시하기 위해 Windows API 직접 사용"""
        try:
            import sys
            import os
            import ctypes

            # PyInstaller에서 패키징된 파일이 풀리는 임시 디렉토리(_MEIPASS) 지원
            if hasattr(sys, "_MEIPASS"):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.dirname(os.path.abspath(__file__))

            # 우선적으로 capture.ico를 찾습니다.
            _ico = os.path.join(base_path, "capture.ico")
            if not os.path.exists(_ico):
                return

            # 1. 작업표시줄 아이콘 그룹화를 위한 AppUserModelID 강제 지정
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "mycompany.screencapture.pro.1"
                )
            except Exception:
                pass

            # 2. Tkinter 기본 윈도우 아이콘 설정
            try:
                self.iconbitmap(_ico)
            except Exception:
                pass

            self.update_idletasks()

            # 3. Windows API로 아이콘 로드하여 적용 (LR_LOADFROMFILE = 0x10)
            LR_LOADFROMFILE = 0x10
            IMAGE_ICON = 1
            WM_SETICON = 0x0080
            ICON_SMALL, ICON_BIG = 0, 1

            hicon_big = ctypes.windll.user32.LoadImageW(
                None, _ico, IMAGE_ICON, 256, 256, LR_LOADFROMFILE
            )
            hicon_small = ctypes.windll.user32.LoadImageW(
                None, _ico, IMAGE_ICON, 16, 16, LR_LOADFROMFILE
            )

            # overrideredirect 창의 실제 HWND 취득
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            if not hwnd:
                hwnd = self.winfo_id()

            if hicon_big or hicon_small:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
                ctypes.windll.user32.SendMessageW(
                    hwnd, WM_SETICON, ICON_SMALL, hicon_small
                )

            # 4. overrideredirect(True) 상태에서도 작업표시줄에 표시되도록 스타일 변경
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if style != 0:
                style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

            # 스타일 반영을 위해 창을 숨겼다가 다시 표시 (작업표시줄 갱신)
            self.withdraw()
            self.deiconify()

        except Exception as e:
            pass  # 아이콘 로드 실패 시 기본 아이콘 유지

    def initUI(self):
        self.overrideredirect(True)  # 타이틀바 완전 제거
        self.attributes("-topmost", True)
        self.configure(bg="#152D32")  # 다크 모드 배경

        # 외곽선 프레임
        main_frame = tk.Frame(
            self,
            bg="#152D32",
            bd=1,
            relief="solid",
            highlightbackground="#0D1C1F",
            highlightthickness=1,
        )
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 타이틀 바 (상단)
        title_bar = tk.Frame(main_frame, bg="#0D1C1F", height=30)
        title_bar.pack(fill=tk.X, side=tk.TOP)
        title_bar.pack_propagate(False)  # 높이 고정

        # 닫기 버튼
        close_btn = tk.Label(
            title_bar,
            text="✕",
            font=("Segoe UI", 10),
            bg="#0D1C1F",
            fg="#80848E",
            cursor="hand2",
        )
        close_btn.pack(side=tk.RIGHT, padx=6)
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg="#E53935"))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg="#80848E"))
        close_btn.bind("<Button-1>", lambda e: self.destroy())

        # UI 타이틀바 아이콘 표시 (숨기기 버튼 왼쪽에 추가)
        try:
            import sys, os

            if hasattr(sys, "_MEIPASS"):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.dirname(os.path.abspath(__file__))
            _ico = os.path.join(base_path, "capture.ico")
            if os.path.exists(_ico):
                from PIL import Image, ImageTk

                # 내부 UI용 작은 아이콘 생성
                icon_img = Image.open(_ico).resize((16, 16), Image.Resampling.LANCZOS)
                self.title_icon = ImageTk.PhotoImage(icon_img)
                icon_label = tk.Label(title_bar, image=self.title_icon, bg="#0D1C1F")
                icon_label.pack(side=tk.LEFT, padx=(6, 0))
        except Exception as e:
            pass

        # 숨기기 버튼 (우측, 닫기 버튼 왼쪽)
        self.is_hidden = False
        hide_btn = tk.Label(
            title_bar,
            text="—",
            font=("Segoe UI", 10, "bold"),
            bg="#0D1C1F",
            fg="#80848E",
            cursor="hand2",
        )
        hide_btn.pack(side=tk.RIGHT, padx=(0, 6))
        hide_btn.bind("<Enter>", lambda e: hide_btn.config(fg="#DFE1E5"))
        hide_btn.bind("<Leave>", lambda e: hide_btn.config(fg="#80848E"))
        hide_btn.bind("<Button-1>", lambda e: self.toggle_visibility())

        # 상단 프로그램 이름 (좌측 정렬)
        self.title_label = tk.Label(
            title_bar,
            text="ScrCapture Pro",
            font=("Segoe UI", 10, "bold"),
            bg="#0D1C1F",
            fg="#DFE1E5",
        )
        self.title_label.pack(side=tk.LEFT, padx=3)

        # 드래그 이벤트 연동
        title_bar.bind("<ButtonPress-1>", self.start_move)
        title_bar.bind("<B1-Motion>", self.on_move)
        self.title_label.bind("<ButtonPress-1>", self.start_move)
        self.title_label.bind("<B1-Motion>", self.on_move)
        main_frame.bind("<ButtonPress-1>", self.start_move)

        # 버튼을 중앙에 모으기 위한 프레임
        btn_frame = tk.Frame(main_frame, bg="#152D32")
        btn_frame.pack(expand=True, fill=tk.BOTH, pady=(12, 12))

        def create_btn(text, cmd):
            btn = tk.Button(
                btn_frame,
                text=text,
                command=cmd,
                bg="#244147",
                fg="#DFE1E5",
                font=("Segoe UI", 10),
                relief="flat",
                bd=0,
                activebackground="#1E363B",
                activeforeground="#DFE1E5",
                cursor="hand2",
                pady=4,
            )
            btn.pack(pady=3, padx=15, fill="x")
            btn.default_bg = "#244147"
            btn.hover_bg = "#31545A"
            btn.bind(
                "<Enter>",
                lambda e, b=btn: (
                    b.config(bg=b.hover_bg) if b["bg"] == b.default_bg else None
                ),
            )
            btn.bind(
                "<Leave>",
                lambda e, b=btn: (
                    b.config(bg=b.default_bg) if b["bg"] == b.hover_bg else None
                ),
            )
            return btn

        self.btn_full = create_btn("전체화면 (Ctrl+1)", self.capture_fullscreen)
        self.btn_active = create_btn("활성화 창 (Ctrl+2)", self.capture_active_window)
        self.btn_region = create_btn("영역 선택 (Ctrl+3)", self.start_region_capture)
        self.btn_repeat = create_btn(
            "고정 영역 (Ctrl+좌클릭)", self.capture_last_region
        )
        self.btn_save_img = create_btn("Save Image (Ctrl+4)", self.save_to_file)

        # 구분선
        sep = tk.Frame(btn_frame, bg="#0D1C1F", height=2)
        sep.pack(fill=tk.X, padx=15, pady=4)

        self.record_fps = 10.0
        self.btn_fps = create_btn("녹화 프레임: 10 FPS", self.toggle_fps)
        self.btn_fps.config(fg="#9AA0A6")  # 버튼 텍스트를 Gray로 변경

        self.btn_record_mp4 = create_btn(
            "MP4 녹화 (Ctrl+5)", lambda: self.toggle_recording("mp4")
        )
        self.btn_record_gif = create_btn(
            "GIF 녹화 (Ctrl+6)", lambda: self.toggle_recording("gif")
        )

        # 로컬 단축키 바인딩 (창이 활성화되어 있을 때)
        self.bind("<Control-Key-1>", lambda e: self.capture_fullscreen())
        self.bind("<Control-Key-2>", lambda e: self.capture_active_window())
        self.bind("<Control-Key-3>", lambda e: self.start_region_capture())
        self.bind("<Control-Key-4>", lambda e: self.save_to_file())
        self.bind("<Control-Key-5>", lambda e: self.toggle_recording("mp4"))
        self.bind("<Control-Key-6>", lambda e: self.toggle_recording("gif"))

        # 백그라운드에서도 작동하는 글로벌 단축키 폴링 시작
        self.hk0 = self.hk1 = self.hk2 = self.hk3 = self.hk4 = self.hk5 = self.hk6 = (
            self.hk_lbutton
        ) = False
        self.is_capturing = False
        self.is_recording = False
        self.record_mode = None
        self.gif_frames = []
        self.check_global_hotkeys()

        # 내부 컨텐츠(버튼 여백 및 글자 크기)에 딱 맞게 창 높이를 자동 계산하여 적용 (절대 잘리지 않음)
        self.update_idletasks()
        req_width = 200  # 원래 의도된 컴팩트한 너비
        req_height = self.winfo_reqheight()
        self.geometry(f"{req_width}x{req_height}")

    def toggle_visibility(self):
        if self.is_hidden:
            self.deiconify()
            self.is_hidden = False
        else:
            self.withdraw()
            self.is_hidden = True

    def toggle_fps(self):
        if self.record_fps == 10.0:
            self.record_fps = 30.0
            self.btn_fps.config(text="녹화 프레임: 30 FPS", fg="#9AA0A6")
        else:
            self.record_fps = 10.0
            self.btn_fps.config(text="녹화 프레임: 10 FPS", fg="#9AA0A6")

    def check_global_hotkeys(self):
        # 0x11: VK_CONTROL, 0x30~0x37: 0~7 키 코드
        ctrl = (ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000) != 0
        k0 = (ctypes.windll.user32.GetAsyncKeyState(0x30) & 0x8000) != 0
        k1 = (ctypes.windll.user32.GetAsyncKeyState(0x31) & 0x8000) != 0
        k2 = (ctypes.windll.user32.GetAsyncKeyState(0x32) & 0x8000) != 0
        k3 = (ctypes.windll.user32.GetAsyncKeyState(0x33) & 0x8000) != 0
        k4 = (ctypes.windll.user32.GetAsyncKeyState(0x34) & 0x8000) != 0
        k5 = (ctypes.windll.user32.GetAsyncKeyState(0x35) & 0x8000) != 0
        k6 = (ctypes.windll.user32.GetAsyncKeyState(0x36) & 0x8000) != 0

        if ctrl and k0:
            if not self.hk0:
                self.toggle_visibility()
                self.hk0 = True
        else:
            self.hk0 = False

        if ctrl and k1:
            if not self.hk1:
                self.capture_fullscreen()
                self.hk1 = True
        else:
            self.hk1 = False

        if ctrl and k2:
            if not self.hk2:
                self.capture_active_window()
                self.hk2 = True
        else:
            self.hk2 = False

        if ctrl and k3:
            if not self.hk3:
                self.start_region_capture()
                self.hk3 = True
        else:
            self.hk3 = False

        if ctrl and k5:
            if not self.hk5:
                self.toggle_recording("mp4")
                self.hk5 = True
        else:
            self.hk5 = False

        if ctrl and k6:
            if not self.hk6:
                self.toggle_recording("gif")
                self.hk6 = True
        else:
            self.hk6 = False

        if ctrl and k4:
            if not self.hk4:
                self.save_to_file()
                self.hk4 = True
        else:
            self.hk4 = False

        # Ctrl + 좌클릭 자동 캡처 감지 (고정 영역이 띄워져 있을 때만 작동)
        lbutton = (ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000) != 0
        if lbutton:
            if not self.hk_lbutton:
                self.hk_lbutton = True
                if self.floating_frame and ctrl:
                    self.capture_last_region()
        else:
            self.hk_lbutton = False

        self.after(50, self.check_global_hotkeys)

    def start_move(self, event):
        self.x = event.x
        self.y = event.y

    def on_move(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.winfo_x() + deltax
        y = self.winfo_y() + deltay
        self.geometry(f"+{x}+{y}")

    def show_message(self, text):
        self.title_label.config(text=text)
        self.after(2000, lambda: self.title_label.config(text="ScrCapture Pro"))

    def process_capture(self, img, region=None):
        if img:
            self.last_image = img  # Ctrl+S 파일 저장을 위해 마지막 이미지 보관
            success = image_to_clipboard(img)
            self.show_message("✅ 저장 완료!" if success else "❌ 캡처 실패!")
            if region:
                self.last_region = region
                self.show_floating_frame(region)
        else:
            self.show_message("❌ 캡처 취소됨")
        self.deiconify()  # 캡처 후 창 다시 표시

    def save_to_file(self):
        """마지막 캡처 이미지를 PNG 파일로 저장 (Ctrl+S)"""
        if not self.last_image:
            self.show_message("❌ 저장할 이미지 없음")
            return
        try:
            os.makedirs("Screenshots", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"Screenshots/capture_{timestamp}.png"
            self.last_image.save(filename, "PNG")
            self.show_message(f"💾 {os.path.basename(filename)}")
        except Exception as e:
            print("Save error:", e)
            self.show_message("❌ 파일 저장 실패")

    def show_floating_frame(self, region):
        if self.floating_frame:
            self.floating_frame.destroy()

        # region은 캡처 이미지(0,0 시작) 기준 로컬 좌표입니다.
        # 실제 윈도우 창을 해당 위치에 띄우려면 다중 모니터의 절대 좌표 시작점 오프셋을 더해주어야 합니다.
        x_virtual = ctypes.windll.user32.GetSystemMetrics(76)
        y_virtual = ctypes.windll.user32.GetSystemMetrics(77)

        x1, y1, x2, y2 = region
        abs_x1 = x1 + x_virtual
        abs_y1 = y1 + y_virtual
        abs_x2 = x2 + x_virtual
        abs_y2 = y2 + y_virtual

        self.floating_frame = FloatingFrame(self, abs_x1, abs_y1, abs_x2, abs_y2)

    def capture_fullscreen(self):
        self.withdraw()  # 캡처 창 숨김
        self.after(300, self._do_capture_fullscreen)

    def _do_capture_fullscreen(self):
        img = ImageGrab.grab(all_screens=True, include_layered_windows=True)
        self.process_capture(img, None)

    def capture_active_window(self):
        self.withdraw()
        self.after(
            500, self._do_capture_active_window
        )  # 이전 창이 포커스를 되찾을 시간 대기

    def _do_capture_active_window(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if hwnd:
                rect = wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                x1, y1, x2, y2 = rect.left, rect.top, rect.right, rect.bottom

                # 전체 모니터상에서의 절대 좌표를 로컬 이미지 좌표로 변환하기 위해 가상 데스크톱 시작점 획득
                x_virtual = ctypes.windll.user32.GetSystemMetrics(76)
                y_virtual = ctypes.windll.user32.GetSystemMetrics(77)

                full_img = ImageGrab.grab(
                    all_screens=True, include_layered_windows=True
                )

                crop_x1 = x1 - x_virtual
                crop_y1 = y1 - y_virtual
                crop_x2 = x2 - x_virtual
                crop_y2 = y2 - y_virtual

                img = full_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))
                self.process_capture(img, None)
            else:
                self.show_message("❌ 활성화된 창 없음")
                self.deiconify()
        except Exception as e:
            print("Capture error:", e)
            self.show_message("❌ 에러 발생")
            self.deiconify()

    def start_region_capture(self):
        if (
            hasattr(self, "snipping_tool")
            and self.snipping_tool
            and self.snipping_tool.top.winfo_exists()
        ):
            self.snipping_tool.confirm_capture()
        else:
            self.withdraw()
            if self.floating_frame:
                self.floating_frame.destroy()
                self.floating_frame = None
            self.after(300, self._open_snipping_tool)

    def _open_snipping_tool(self):
        # 마지막 영역이 있다면 넘겨주어 수정할 수 있게 함
        self.snipping_tool = SnippingTool(
            self, self.process_capture, initial_region=self.last_region
        )

    def capture_last_region(self):
        if not self.last_region:
            self.show_message("❌ 이전 영역 없음")
            return

        if self.is_capturing:
            return
        self.is_capturing = True

        self.withdraw()
        if self.floating_frame:
            self.floating_frame.withdraw()  # 캡처 전 빨간 틀 잠깐 숨기기
            self.floating_frame.update()  # 화면에서 즉시 지우기 반영

        self.after(
            50, self._do_capture_last_region
        )  # 300ms -> 50ms로 단축하여 즉각 반응

    def _do_capture_last_region(self):
        try:
            full_img = ImageGrab.grab(all_screens=True, include_layered_windows=True)
            img = full_img.crop(self.last_region)
            self.process_capture(
                img, self.last_region
            )  # 여기서 floating_frame이 다시 생성되어 나타남
        except Exception as e:
            print("Repeat capture error:", e)
            self.show_message("❌ 에러 발생")
            self.deiconify()
        finally:
            self.is_capturing = False

    def toggle_recording(self, mode="mp4"):
        if mode == "mp4" and (not cv2 or not np):
            self.show_message("❌ cv2/numpy 미설치")
            return

        if not self.last_region:
            self.show_message("❌ 영역 먼저 선택")
            return

        if self.is_recording:
            self.is_recording = False
            self.btn_record_mp4.default_bg = "#244147"
            self.btn_record_mp4.config(
                text="MP4 녹화 (Ctrl+5)", bg="#244147", fg="#DFE1E5"
            )
            self.btn_record_gif.default_bg = "#244147"
            self.btn_record_gif.config(
                text="GIF 녹화 (Ctrl+6)", bg="#244147", fg="#DFE1E5"
            )
            self.show_message("⏹ 녹화 종료 및 저장 중...")
        else:
            self.is_recording = True
            self.record_mode = mode
            if mode == "mp4":
                self.btn_record_mp4.default_bg = "#D32F2F"
                self.btn_record_mp4.config(
                    text="MP4 정지 (Ctrl+5)", bg="#D32F2F", fg="white"
                )
            else:
                self.btn_record_gif.default_bg = "#D32F2F"
                self.btn_record_gif.config(
                    text="GIF 정지 (Ctrl+6)", bg="#D32F2F", fg="white"
                )
            self.show_message(f"🔴 {mode.upper()} 녹화 시작됨!")
            threading.Thread(target=self._record_loop, daemon=True).start()

    def _record_loop(self):
        x1, y1, x2, y2 = self.last_region

        # 빨간색 테두리가 영상에 전혀 보이지 않도록 안쪽으로 여유있게 5픽셀씩 잘라냅니다.
        crop_x1, crop_y1 = x1 + 5, y1 + 5
        crop_x2, crop_y2 = x2 - 5, y2 - 5

        # 코덱 호환성을 위해 너비와 높이를 짝수로 맞춤
        cw = crop_x2 - crop_x1
        ch = crop_y2 - crop_y1
        if cw % 2 != 0:
            cw -= 1
            crop_x2 -= 1
        if ch % 2 != 0:
            ch -= 1
            crop_y2 -= 1

        if cw <= 0 or ch <= 0:
            self.is_recording = False
            self.show_message("❌ 영역이 너무 작음")
            self.btn_record_mp4.default_bg = "#244147"
            self.btn_record_mp4.config(
                text="MP4 녹화 (Ctrl+5)", bg="#244147", fg="#DFE1E5"
            )
            self.btn_record_gif.default_bg = "#244147"
            self.btn_record_gif.config(
                text="GIF 녹화 (Ctrl+6)", bg="#244147", fg="#DFE1E5"
            )
            return

        os.makedirs("Recordings", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fps = self.record_fps
        target_frame_time = 1.0 / fps

        if self.record_mode == "mp4":
            filename = f"Recordings/capture_{timestamp}.mp4"
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            out = cv2.VideoWriter(filename, fourcc, fps, (cw, ch))
        else:
            filename = f"Recordings/capture_{timestamp}.gif"
            self.gif_frames = []

        while self.is_recording:
            start_time = time.time()
            try:
                # 화면 전체 캡처 후 자르기 (가속 창 포함하기 위해)
                full_img = ImageGrab.grab(
                    all_screens=True, include_layered_windows=True
                )
                img = full_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))

                if self.record_mode == "mp4":
                    frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                    out.write(frame)
                else:
                    self.gif_frames.append(img.convert("RGB"))
            except Exception as e:
                print("Record error:", e)

            elapsed = time.time() - start_time
            sleep_time = target_frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        if self.record_mode == "mp4":
            out.release()
        elif self.record_mode == "gif" and len(self.gif_frames) > 0:
            self.gif_frames[0].save(
                filename,
                save_all=True,
                append_images=self.gif_frames[1:],
                duration=int(1000 / fps),
                loop=0,
            )
            self.gif_frames.clear()

        self.btn_record_mp4.default_bg = "#244147"
        self.btn_record_mp4.config(text="MP4 녹화 (Ctrl+5)", bg="#244147", fg="#DFE1E5")
        self.btn_record_gif.default_bg = "#244147"
        self.btn_record_gif.config(text="GIF 녹화 (Ctrl+6)", bg="#244147", fg="#DFE1E5")
        self.show_message("✅ 녹화 저장 완료!")


if __name__ == "__main__":
    app = CaptureApp()
    app.mainloop()
