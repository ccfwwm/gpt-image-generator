#!/usr/bin/env python3
"""Generate and edit images through image.aicodeme.xyz without exposing API keys."""
from __future__ import annotations

import argparse
import base64
import ctypes
import getpass
import importlib.util as importlib_util
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://image.aicodeme.xyz"
DEFAULT_GENERATE_URL = f"{DEFAULT_BASE_URL}/v1/images/generations"
DEFAULT_EDIT_URL = f"{DEFAULT_BASE_URL}/v1/images/edits"
DEFAULT_MODELS_URL = f"{DEFAULT_BASE_URL}/v1/models"
DEFAULT_MODEL = "gpt-image-2.5-sunburst"
DEFAULT_SIZE = "1536x1024"
DEFAULT_QUALITY = "high"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MAX_EDIT_REFERENCE_IMAGES = 16
MAX_REFERENCE_IMAGE_BYTES = 20 * 1024 * 1024
CURL_STATUS_MARKER = b"\n__GPT_IMAGE_HTTP_STATUS__"
APP_NAME = "gpt-image-generator"
CONFIG_DIR = Path(
    os.environ.get("GPT_IMAGE_GENERATOR_CONFIG_DIR")
    or (
        Path(os.environ["LOCALAPPDATA"]) / APP_NAME
        if os.name == "nt" and os.environ.get("LOCALAPPDATA")
        else Path.home() / "AppData" / "Local" / APP_NAME
        if os.name == "nt"
        else Path.home() / "Library" / "Application Support" / APP_NAME
        if sys.platform == "darwin"
        else Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
    )
)


class CredentialError(RuntimeError):
    """Credential storage is missing, unreadable, or not secure enough."""


def strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key:
            env[key] = strip_quotes(raw_value)
    return env


def merged_env(path: Path | None) -> dict[str, str]:
    merged = dict(os.environ)
    if path is not None:
        merged.update(load_env_file(path))
    return merged


def resolve_env_path(raw_path: str | None) -> Path | None:
    return Path(raw_path).expanduser() if raw_path else None


def _dpapi(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        raise CredentialError("Windows DPAPI is available only on Windows.")
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    source_buffer = ctypes.create_string_buffer(data)
    source = DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    output = DataBlob()
    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    if protect:
        function = crypt32.CryptProtectData
        function.argtypes = [
            ctypes.POINTER(DataBlob), wintypes.LPCWSTR, ctypes.POINTER(DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob),
        ]
        function.restype = wintypes.BOOL
        ok = function(ctypes.byref(source), APP_NAME, None, None, None, 0, ctypes.byref(output))
    else:
        function = crypt32.CryptUnprotectData
        function.argtypes = [
            ctypes.POINTER(DataBlob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob),
        ]
        function.restype = wintypes.BOOL
        ok = function(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output))
    if not ok:
        raise CredentialError("Windows could not protect or read the saved credential.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(output.pbData)


def _keyring_module():
    try:
        import keyring
    except ImportError as error:
        raise CredentialError(
            "Secure OS keychain support is unavailable. On non-Windows systems, install "
            "the Python 'keyring' package with a system keychain backend."
        ) from error
    try:
        backend = keyring.get_keyring()
        if float(getattr(backend, "priority", 0)) <= 0:
            raise CredentialError("No secure OS keychain backend is available.")
        backend_type = type(backend)
        identity = (backend_type.__module__, backend_type.__name__)
        if sys.platform == "darwin":
            secure_backends = {("keyring.backends.macOS", "Keyring")}
        elif sys.platform.startswith("linux"):
            secure_backends = {
                ("keyring.backends.SecretService", "Keyring"),
                ("keyring.backends.libsecret", "Keyring"),
                ("keyring.backends.kwallet", "DBusKeyring"),
            }
        else:
            secure_backends = set()
        if identity not in secure_backends:
            raise CredentialError(
                "The selected keyring backend is not a supported OS credential store. "
                "Use macOS Keychain, Linux Secret Service, or KWallet."
            )
    except CredentialError:
        raise
    except Exception as error:
        raise CredentialError("The OS keychain could not be opened.") from error
    return keyring


def credential_path() -> Path:
    return CONFIG_DIR / "api-key.dpapi"


def save_api_key(value: str) -> None:
    key = value.strip()
    if not key:
        raise CredentialError("The API key cannot be empty.")
    if "\n" in key or "\r" in key or "\x00" in key:
        raise CredentialError("The API key must be a single line of text.")
    if os.name == "nt":
        target = credential_path()
        temporary = target.with_suffix(".tmp")
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            encrypted = _dpapi(key.encode("utf-8"), protect=True)
            temporary.write_bytes(encrypted)
            os.replace(temporary, target)
        except CredentialError:
            raise
        except OSError as error:
            raise CredentialError("The encrypted API key could not be saved to local storage.") from error
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    else:
        try:
            _keyring_module().set_password(APP_NAME, "default", key)
        except CredentialError:
            raise
        except Exception as error:
            raise CredentialError("The API key could not be saved to the OS keychain.") from error


def load_api_key() -> str:
    if os.name == "nt":
        path = credential_path()
        if not path.is_file():
            return ""
        try:
            return _dpapi(path.read_bytes(), protect=False).decode("utf-8").strip()
        except (OSError, UnicodeError, CredentialError) as error:
            raise CredentialError("The saved API key could not be read on this Windows account.") from error
    try:
        value = _keyring_module().get_password(APP_NAME, "default")
        return value or ""
    except CredentialError:
        raise
    except Exception as error:
        raise CredentialError("The saved API key could not be read from the OS keychain.") from error


def delete_api_key() -> bool:
    """Delete the locally stored credential without displaying its value."""
    if os.name == "nt":
        path = credential_path()
        try:
            if not path.exists():
                return False
            path.unlink()
            return True
        except OSError as error:
            raise CredentialError("The saved API key could not be removed from local storage.") from error
    try:
        keyring = _keyring_module()
        if not keyring.get_password(APP_NAME, "default"):
            return False
        keyring.delete_password(APP_NAME, "default")
        return True
    except CredentialError:
        raise
    except Exception as error:
        raise CredentialError("The saved API key could not be removed from the OS keychain.") from error


def has_api_key() -> bool:
    try:
        return bool(load_api_key())
    except CredentialError:
        return False


def show_message_box(text: str, title: str = "GPT 图片生成器", error: bool = False) -> None:
    """Show a native message box so detached helpers can still report problems."""
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if error else 0x40)
            return
        except Exception:
            pass
    print(text, file=sys.stderr)


def write_dialog_state(state: str) -> None:
    """Record how the last setup dialog ended so callers can inspect the outcome."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"result": state, "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
        (CONFIG_DIR / "dialog-state.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def read_dialog_state() -> str:
    try:
        value = json.loads((CONFIG_DIR / "dialog-state.json").read_text(encoding="utf-8"))
        result = str(value.get("result") or "")
        stamp = str(value.get("time") or "")
        return f"{result} @ {stamp}".strip() if result else ""
    except (OSError, json.JSONDecodeError, AttributeError):
        return ""


def _creation_flags_no_window() -> int:
    return 0x08000000 if os.name == "nt" else 0


def _interpreter_has_tkinter(executable: Path) -> bool:
    if not executable.is_file():
        return False
    try:
        result = subprocess.run(
            [str(executable), "-c", "import tkinter"],
            capture_output=True, timeout=30, check=False,
            creationflags=_creation_flags_no_window(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _gui_interpreter_candidates() -> list[Path]:
    candidates: list[Path] = []
    cached = load_settings().get("gui_python")
    if isinstance(cached, str) and cached.strip():
        candidates.append(Path(cached.strip()))
    candidates.append(Path(sys.executable))
    if os.name == "nt":
        candidates.append(Path(sys.executable).with_name("pythonw.exe"))
        try:
            result = subprocess.run(
                ["py", "-3", "-c", "import sys;print(sys.executable)"],
                capture_output=True, timeout=30, check=False, text=True,
                creationflags=_creation_flags_no_window(),
            )
            if result.returncode == 0 and result.stdout.strip():
                candidates.append(Path(result.stdout.strip()))
        except (OSError, subprocess.TimeoutExpired):
            pass
        for name in ("pythonw.exe", "python3.exe", "python.exe"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
        patterns = [
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Python3*" / "python.exe",
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Python3*" / "python.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python3*" / "python.exe",
            Path("C:/") / "Python3*" / "python.exe",
        ]
        for pattern in patterns:
            try:
                candidates.extend(sorted(pattern.parent.parent.glob(pattern.relative_to(pattern.parent.parent))))
            except (OSError, ValueError):
                continue
    else:
        for name in ("python3", "python"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
        candidates.extend([Path("/usr/bin/python3"), Path("/opt/homebrew/bin/python3")])

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def find_tkinter_python() -> Path | None:
    """Locate a Python interpreter that can actually open a Tk window."""
    if importlib_util.find_spec("tkinter") is not None:
        return Path(sys.executable)
    for candidate in _gui_interpreter_candidates():
        if _interpreter_has_tkinter(candidate):
            settings = load_settings()
            if settings.get("gui_python") != str(candidate):
                settings["gui_python"] = str(candidate)
                try:
                    save_settings(settings)
                except OSError:
                    pass
            return candidate
    return None


def spawn_detached_dialog() -> int:
    """Open the masked key window in its own process and return immediately."""
    interpreter = find_tkinter_python()
    if interpreter is None:
        hint = (
            "未找到带图形界面（Tk）的 Python，无法直接弹窗。\n\n"
            "请安装官方 Python（勾选 tcl/tk）后重试，"
            "或在本机终端运行：\n"
            "python scripts/aiimagesee_image.py configure-key --terminal\n\n"
            "无论哪种方式，都不要把密钥粘贴到聊天窗口里。"
        )
        show_message_box(hint, error=True)
        raise SystemExit("ERROR: no Tk-capable Python interpreter was found for the key window.")

    executable = interpreter
    if os.name == "nt":
        windowless = interpreter.with_name("pythonw.exe")
        if windowless.is_file():
            executable = windowless
    command = [str(executable), str(Path(__file__).resolve()), "configure-key", "--gui-only"]
    try:
        if os.name == "nt":
            process = subprocess.Popen(
                command, close_fds=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x00000008,  # DETACHED_PROCESS
            )
        else:
            process = subprocess.Popen(
                command, close_fds=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    except OSError as error:
        raise SystemExit(f"ERROR: the key window could not be started: {error}") from error
    print("dialog: opened")
    print(f"dialog_pid: {process.pid}")
    print(f"dialog_interpreter: {executable}")
    print("action: paste the key into the window and click Save securely")
    return 0


def _stdin_is_tty() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (OSError, ValueError):
        return False


def configure_key_dialog(gui_only: bool = False) -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError as error:
        if gui_only or not _stdin_is_tty():
            show_message_box(
                "当前 Python 缺少 Tk 图形界面模块，无法弹窗。\n\n"
                "请安装官方 Python（含 tcl/tk），或用 configure-key --terminal 在终端里输入。",
                error=True,
            )
            return 1
        return configure_key_terminal(error)

    try:
        root = tk.Tk()
    except tk.TclError as error:
        if gui_only or not _stdin_is_tty():
            show_message_box(f"无法创建弹窗（可能没有可用的桌面会话）。\n\n{error}", error=True)
            return 1
        return configure_key_terminal(error)
    from tkinter import font as tkfont

    ui = {
        "bg": "#F5F5F7",
        "header_from": "#FFFFFF",
        "header_to": "#EFF6FF",
        "surface": "#FFFFFF",
        "field": "#FFFFFF",
        "text": "#111114",
        "muted": "#3C3C43",
        "faint": "#6E6E73",
        "accent": "#0071E3",
        "primary": "#0071E3",
        "primary_hover": "#0A84FF",
        "ghost": "#FFFFFF",
        "ghost_hover": "#F0F5FF",
        "danger": "#D70015",
        "success": "#0F8A45",
        "hairline": "#E1E1E6",
        "border": "#D8D8DE",
        "badge": "#0071E3",
    }
    signup_url = "https://image.aicodeme.xyz/signup/"
    profile_url = "https://image.aicodeme.xyz/profile/"

    available = set(tkfont.families(root))
    family = next(
        (name for name in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
                           "Noto Sans CJK SC", "Segoe UI", "Helvetica")
         if name in available),
        "TkDefaultFont",
    )

    def F(size: int, weight: str = "normal") -> tuple:
        return (family, size, weight)

    def hex_to_rgb(value: str) -> tuple[int, int, int]:
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]

    def rgb_to_hex(rgb) -> str:
        return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb)

    def draw_h_gradient(canvas, width: int, height: int, start: str, end: str) -> None:
        left, right = hex_to_rgb(start), hex_to_rgb(end)
        for x in range(width):
            t = x / max(1, width - 1)
            canvas.create_line(
                x, 0, x, height,
                fill=rgb_to_hex([left[i] + (right[i] - left[i]) * t for i in range(3)]),
            )

    def round_rect(canvas, x1: float, y1: float, x2: float, y2: float, r: float, **kwargs):
        r = max(2.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
        points = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]
        return canvas.create_polygon(points, smooth=True, **kwargs)

    class RoundButton(tk.Canvas):
        """Flat rounded button that still feels like a button on every Tk build."""

        def __init__(self, master, text, command, *, width, height, fill, hover, fg, font,
                     border=None, border_hover=None, radius=None):
            super().__init__(master, width=width, height=height, bg=ui["bg"],
                             highlightthickness=0, bd=0, takefocus=1, cursor="hand2")
            self._command = command
            self._fill, self._hover = fill, hover
            self._border = border or fill
            self._border_hover = border_hover or self._border
            radius = radius if radius is not None else height // 2
            self._shape = round_rect(self, 1, 1, width - 1, height - 1, radius,
                                     fill=fill, outline=self._border, width=1)
            self.create_text(width // 2, height // 2, text=text, fill=fg, font=font)
            self.bind("<Enter>", lambda _e: self._paint(self._hover, self._border_hover))
            self.bind("<Leave>", lambda _e: self._paint(self._fill, self._border))
            self.bind("<Button-1>", lambda _e: self._command())
            self.bind("<Return>", lambda _e: self._command())
            self.bind("<space>", lambda _e: self._command())

        def _paint(self, fill: str, border: str) -> None:
            self.itemconfigure(self._shape, fill=fill, outline=border)

    def open_site(url: str) -> None:
        __import__("webbrowser").open(url)

    def on_close() -> None:
        write_dialog_state("cancelled")
        root.destroy()

    def apply_windows_chrome() -> None:
        """Rounded corners on Windows 11 so the frame reads like a mac panel."""
        if os.name != "nt":
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            corner = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner)
            )
        except Exception:
            pass

    width_total = 700
    pad = 30
    root.configure(bg=ui["bg"])
    root.title("配置 API 密钥 · GPT 图片生成器")
    root.attributes("-topmost", True)
    root.withdraw()  # avoid a default-size flash before the content-sized geometry lands

    header = tk.Canvas(root, width=width_total, height=110, bg=ui["header_from"],
                       highlightthickness=0, bd=0)
    header.pack(fill="x")
    draw_h_gradient(header, width_total, 110, ui["header_from"], ui["header_to"])
    round_rect(header, width_total - 244, 18, width_total - pad, 92, 14,
               fill="#F4F9FF", outline="#C7DEFF", width=1)
    header.create_text(width_total - 137, 42, text="¥0.04 / 张", fill=ui["accent"], font=F(18, "bold"))
    header.create_text(width_total - 137, 72, text="image-低价分组 · 所有模型同价",
                       fill="#1D4E89", font=F(10))
    header.create_text(pad, 42, text="配置 GPT 图片 API 密钥", anchor="w", fill=ui["text"], font=F(17, "bold"))
    header.create_text(pad, 74, text="GPT Image 2.5 · 密钥加密保存在本机，不进对话与日志",
                       anchor="w", fill=ui["muted"], font=F(10))
    header.create_line(0, 109, width_total, 109, fill=ui["hairline"], width=1)

    body = tk.Frame(root, bg=ui["bg"])
    body.pack(fill="both", expand=True)
    tk.Frame(body, bg=ui["bg"], height=14).pack()

    tk.Label(body, text="支持模型 · 四个模型同价，默认 gpt-image-2.5-sunburst", bg=ui["bg"],
             fg=ui["muted"], font=F(10), anchor="w").pack(fill="x", padx=pad, pady=(0, 7))

    chip_font = tkfont.Font(family=family, size=9)
    chip_canvas = tk.Canvas(body, width=width_total - 2 * pad, height=34, bg=ui["bg"],
                            highlightthickness=0, bd=0)
    chip_canvas.pack(fill="x", padx=pad, pady=(0, 14))
    chip_x = 0
    for model_name in ("gpt-image-2", "gpt-image-2.5", "gpt-image-2.5-sunburst", "gpt-image-2.5-flare"):
        is_default = model_name.endswith("sunburst")
        chip_width = chip_font.measure(model_name) + 28
        round_rect(chip_canvas, chip_x, 2, chip_x + chip_width, 32, 8,
                   fill="#EAF2FF" if is_default else "#FFFFFF",
                   outline="#A9CDFF" if is_default else ui["border"], width=1)
        chip_canvas.create_text(chip_x + chip_width / 2, 17, text=model_name,
                                font=F(9, "bold" if is_default else "normal"),
                                fill=ui["accent"] if is_default else ui["muted"])
        chip_x += chip_width + 8

    card = tk.Frame(body, bg=ui["surface"], highlightbackground=ui["hairline"], highlightthickness=1)
    card.pack(fill="x", padx=pad, pady=(0, 12))
    inner = tk.Frame(card, bg=ui["surface"])
    inner.pack(fill="x", padx=18, pady=14)

    def add_step(index: int, title: str, detail: str, last: bool = False) -> None:
        row = tk.Frame(inner, bg=ui["surface"])
        row.pack(fill="x")
        badge = tk.Canvas(row, width=30, height=30, bg=ui["surface"], highlightthickness=0, bd=0)
        badge.pack(side="left", anchor="n")
        badge.create_oval(0, 0, 30, 30, fill=ui["badge"], outline=ui["badge"])
        badge.create_text(15, 15, text=str(index), fill="#FFFFFF", font=F(11, "bold"))
        box = tk.Frame(row, bg=ui["surface"])
        box.pack(side="left", fill="x", expand=True, padx=(14, 0))
        tk.Label(box, text=title, bg=ui["surface"], fg=ui["text"], font=F(11, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(box, text=detail, bg=ui["surface"], fg=ui["muted"], font=F(10), anchor="w",
                 justify="left", wraplength=520).pack(fill="x", pady=(3, 0))
        if not last:
            tk.Frame(inner, bg=ui["hairline"], height=1).pack(fill="x", pady=(12, 12))

    add_step(1, "注册账号", "邮箱 + 密码（至少 8 位）+ 邮箱验证码，点下面「打开注册页」直接跳转")
    add_step(2, "创建密钥", "个人中心 → 开发者密钥 → 创建密钥：名称随意、额度填 0，价格方案选 image-低价分组")
    add_step(3, "粘贴密钥", "点密钥右侧「复制」，粘到下面输入框，再点「保存密钥」；全程掩码显示", last=True)

    links = tk.Frame(body, bg=ui["bg"])
    links.pack(fill="x", padx=pad, pady=(0, 12))
    RoundButton(links, "打开注册页 ↗", lambda: open_site(signup_url), width=164, height=42,
                fill="#EAF3FF", hover="#D8E9FF", fg="#0062CC", font=F(11, "bold"),
                border="#A9CDFF", border_hover=ui["accent"], radius=10).pack(side="left")
    RoundButton(links, "打开个人中心 ↗", lambda: open_site(profile_url), width=178, height=42,
                fill="#EAF3FF", hover="#D8E9FF", fg="#0062CC", font=F(11, "bold"),
                border="#A9CDFF", border_hover=ui["accent"], radius=10).pack(side="left", padx=(10, 0))
    tk.Label(links, text="没有账号先注册，已有账号直接建密钥", bg=ui["bg"], fg=ui["faint"],
             font=F(9)).pack(side="right", pady=(13, 0))

    tk.Label(body, text="开发者密钥 SK", bg=ui["bg"], fg=ui["muted"], font=F(10),
             anchor="w").pack(fill="x", padx=pad)
    field_width = width_total - 2 * pad
    field = tk.Canvas(body, width=field_width, height=52, bg=ui["bg"], highlightthickness=0, bd=0)
    field.pack(fill="x", padx=pad, pady=(7, 0))
    round_rect(field, 0, 0, field_width, 52, 12, fill=ui["field"], outline=ui["border"], width=1)
    entry = tk.Entry(field, bd=0, bg=ui["field"], fg=ui["text"], insertbackground=ui["accent"],
                     show="●", font=F(12), highlightthickness=0, relief="flat",
                     disabledbackground=ui["field"], disabledforeground=ui["faint"])
    entry_width = field_width - 36 - 86
    field.create_window(18, 26, window=entry, anchor="w", width=entry_width, height=30)

    def paste_from_clipboard() -> None:
        if saved:
            return
        try:
            text = root.clipboard_get()
        except tk.TclError:
            status_label.configure(text="剪贴板里没有文本，请先在密钥右侧点「复制」。", fg=ui["danger"])
            return
        entry.configure(state="normal")
        entry.delete(0, tk.END)
        entry.insert(0, text.strip())
        entry.focus_set()
        status_label.configure(text="")

    paste_shape = round_rect(field, field_width - 86, 10, field_width - 12, 42, 16,
                             fill="#F5F5F7", outline="#D8D8DE", width=1)
    paste_text = field.create_text(field_width - 49, 26, text="粘贴", fill=ui["accent"], font=F(10))
    for item in (paste_shape, paste_text):
        field.tag_bind(item, "<Button-1>", lambda _event: paste_from_clipboard())
        field.tag_bind(item, "<Enter>", lambda _event: field.configure(cursor="hand2"))
        field.tag_bind(item, "<Leave>", lambda _event: field.configure(cursor=""))

    footer = tk.Frame(body, bg=ui["bg"])
    footer.pack(fill="x", padx=pad, pady=(14, 20))
    status_label = tk.Label(footer, text="", bg=ui["bg"], fg=ui["danger"], font=F(10),
                            anchor="w", justify="left", wraplength=360)
    status_label.pack(side="left", fill="x", expand=True)
    root.protocol("WM_DELETE_WINDOW", on_close)

    saved = False

    def save() -> None:
        nonlocal saved
        if saved:
            return
        value = entry.get()
        if not value.strip():
            status_label.configure(text="请先粘贴密钥，或点「取消」退出。", fg=ui["danger"])
            entry.focus_set()
            return
        if has_api_key() and not messagebox.askyesno(
            "已存在密钥", "本机已保存过一个密钥，是否覆盖？", parent=root
        ):
            return
        try:
            save_api_key(value)
        except CredentialError as error:
            status_label.configure(text=str(error), fg=ui["danger"])
            return
        try:
            if root.clipboard_get() == value:
                root.clipboard_clear()
        except tk.TclError:
            pass
        value = ""
        entry.delete(0, tk.END)
        entry.configure(state="disabled")
        saved = True
        write_dialog_state("saved")
        status_label.configure(text="密钥已加密保存到本机，窗口即将关闭 ✓", fg=ui["success"])
        root.after(1100, root.destroy)

    cancel_button = RoundButton(footer, "取消", on_close, width=106, height=46,
                                fill=ui["ghost"], hover=ui["ghost_hover"], fg=ui["text"],
                                font=F(11), border=ui["border"], border_hover="#C4C4CB",
                                radius=10)
    cancel_button.pack(side="right")
    save_button = RoundButton(footer, "保存密钥", lambda: save(), width=152, height=46,
                              fill=ui["primary"], hover=ui["primary_hover"], fg="#FFFFFF",
                              font=F(11, "bold"), radius=10)
    save_button.pack(side="right", padx=(0, 10))

    def bring_to_front() -> None:
        try:
            root.deiconify()
            root.lift()
            root.attributes("-topmost", True)
            root.focus_force()
            root.grab_set()
        except tk.TclError:
            pass

    def finalize_layout() -> None:
        """Size the window to its content so edited copy never gets clipped."""
        root.update_idletasks()
        width = max(width_total, root.winfo_reqwidth())
        height = root.winfo_reqheight()
        x = max(0, (root.winfo_screenwidth() - width) // 2)
        y = max(0, (root.winfo_screenheight() - height) // 3)
        root.geometry(f"{width}x{height}+{x}+{y}")
        print(f"dialog_geometry: {width}x{height}")
        root.resizable(False, False)
        root.minsize(width, height)
        root.deiconify()
        apply_windows_chrome()

    root.bind("<Return>", lambda _event: save())
    root.bind("<Escape>", lambda _event: on_close())
    finalize_layout()
    root.after(150, bring_to_front)
    root.after(320, entry.focus_set)
    root.mainloop()
    print(f"dialog_result: {read_dialog_state() or 'closed without saving'}")
    print(f"api_key: {'SET' if has_api_key() else 'MISSING'}")
    return 0


def configure_key_terminal(reason: Exception | None = None) -> int:
    if reason:
        print("A local key window is unavailable; using masked terminal input.", file=sys.stderr)
    try:
        with warnings.catch_warnings():
            # getpass otherwise falls back to echoing input when it cannot disable echo.
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass("Paste your API key here (input is hidden): ")
    except (EOFError, OSError, getpass.GetPassWarning) as error:
        raise SystemExit(
            "ERROR: secure hidden input is unavailable in this session. Run configure-key "
            "from a local desktop or interactive terminal; do not paste the key into chat."
        ) from error
    if not value.strip():
        raise SystemExit("ERROR: no key was entered.")
    if has_api_key():
        try:
            replace = input("A key is already saved. Replace it? [y/N] ").strip().lower()
        except (EOFError, OSError) as error:
            raise SystemExit("ERROR: could not confirm replacing the saved key.") from error
        if replace not in ("y", "yes"):
            print("Existing key kept.")
            return 0
    try:
        save_api_key(value)
    except CredentialError as error:
        raise SystemExit(f"ERROR: {error}") from error
    value = ""
    print("API key saved to the OS credential store; its value was not displayed.")
    return 0


def redact_sensitive_text(value: str, secret: str = "") -> str:
    text = value
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+|api[_-]?key\s*[:=]\s*)\S+",
        r"\1[REDACTED]", text,
    )


def env_value(env: dict[str, str], *names: str, fallback: str = "") -> str:
    for name in names:
        value = env.get(name, "").strip()
        if value:
            return value
    return fallback


def require_api_key() -> str:
    try:
        value = load_api_key()
    except CredentialError as error:
        raise SystemExit(f"ERROR: {error}") from error
    if not value:
        raise SystemExit("ERROR: no API key is configured; run 'configure-key' to open the masked local dialog.")
    return value


def parse_api_url(value: str, label: str) -> str:
    if not value:
        raise SystemExit(f"ERROR: {label} is not configured.")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SystemExit(f"ERROR: {label} must be a valid http:// or https:// URL.")
    return value


def api_url(env: dict[str, str], kind: str) -> str:
    if kind == "generate":
        return env_value(env, "IMAGE_DIRECT_UPSTREAM_URL", "DEFAULT_IMAGE_API_URL", "VITE_DEFAULT_IMAGE_API_URL", fallback=DEFAULT_GENERATE_URL)
    if kind == "edit":
        return env_value(env, "IMAGE_EDIT_DIRECT_UPSTREAM_URL", "DEFAULT_IMAGE_EDIT_API_URL", "VITE_DEFAULT_IMAGE_EDIT_API_URL", fallback=DEFAULT_EDIT_URL)
    explicit = env_value(env, "IMAGE_MODELS_URL")
    if explicit:
        return explicit
    endpoint = urllib.parse.urlsplit(api_url(env, "generate"))
    return urllib.parse.urlunsplit((endpoint.scheme, endpoint.netloc, "/v1/models", "", ""))


def upstream_headers(env: dict[str, str], api_key: str, json_content: bool) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": env_value(env, "IMAGE_UPSTREAM_USER_AGENT", fallback=DEFAULT_USER_AGENT),
    }
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


def _curl_config(headers: dict[str, str]) -> bytes:
    # cURL reads the Authorization header from stdin; it never appears in argv.
    lines = []
    for name, value in headers.items():
        if name.lower() == "authorization":
            value = value.replace("\\", "\\\\").replace('"', '\\"')
            if "\r" in value or "\n" in value:
                raise SystemExit("ERROR: invalid newline in request header.")
            lines.append(f'header = "{name}: {value}"')
    return ("\n".join(lines) + "\n").encode("utf-8")


def curl_executable() -> str | None:
    return shutil.which("curl.exe") or shutil.which("curl")


def _decode_response(raw: bytes, operation: str, secret: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as error:
        detail = redact_sensitive_text(raw.decode("utf-8", errors="replace").strip()[:500], secret)
        raise SystemExit(f"ERROR: {operation} returned invalid JSON: {detail}") from error
    if not isinstance(payload, dict):
        raise SystemExit(f"ERROR: {operation} returned a non-object JSON response.")
    return payload


def run_curl_json(command: list[str], config_stdin: bytes, operation: str, secret: str) -> dict[str, Any]:
    command.extend(["--config", "-", "--write-out", CURL_STATUS_MARKER.decode("ascii") + "%{http_code}"])
    try:
        result = subprocess.run(command, input=config_stdin, capture_output=True, timeout=600, check=False)
    except subprocess.TimeoutExpired as error:
        raise SystemExit(f"ERROR: {operation} timed out after 600 seconds.") from error
    except OSError as error:
        raise SystemExit(f"ERROR: {operation} could not start curl: {error}") from error
    raw_output = result.stdout or b""
    status: int | None = None
    body = raw_output
    if CURL_STATUS_MARKER in raw_output:
        body, raw_status = raw_output.rsplit(CURL_STATUS_MARKER, 1)
        try:
            status = int(raw_status.strip())
        except ValueError:
            status = None
    if status is not None and status >= 400:
        detail = redact_sensitive_text(body.decode("utf-8", errors="replace").strip()[:1000], secret)
        raise SystemExit(f"ERROR: {operation} failed HTTP {status}: {detail}")
    if result.returncode != 0:
        detail = redact_sensitive_text((result.stderr or b"").decode("utf-8", errors="replace").strip()[:1000], secret)
        raise SystemExit(f"ERROR: {operation} request failed via curl: {detail or 'unknown curl error'}")
    return _decode_response(body, operation, secret)


def request_json(url: str, headers: dict[str, str], operation: str, secret: str,
                 body: bytes | None = None, form: dict[str, Any] | None = None,
                 images: list[Path] | None = None) -> dict[str, Any]:
    curl = curl_executable()
    if curl:
        command = [curl, "--silent", "--show-error", "--request", "POST" if body is not None or form is not None else "GET", url]
        command.extend([item for name, value in headers.items() if name.lower() != "authorization" for item in ("--header", f"{name}: {value}")])
        config = _curl_config(headers)
        if body is not None:
            temp_name = ""
            try:
                with tempfile.NamedTemporaryFile(prefix="gpt-image-request-", suffix=".json", delete=False) as handle:
                    handle.write(body)
                    temp_name = handle.name
                command.extend(["--data-binary", "@" + temp_name])
                return run_curl_json(command, config, operation, secret)
            finally:
                if temp_name:
                    try:
                        Path(temp_name).unlink()
                    except OSError:
                        pass
        if form is not None:
            for name, value in form.items():
                command.extend(["--form-string", f"{name}={value}"])
        for image in images or []:
            mime = mimetypes.guess_type(str(image))[0] or "image/png"
            command.extend(["--form", f"image=@{image.resolve()};type={mime}"])
        return run_curl_json(command, config, operation, secret)

    request_headers = dict(headers)
    data = body
    if form is not None:
        try:
            import requests
        except ImportError as error:
            raise SystemExit("ERROR: edit mode requires Python package 'requests' when curl is unavailable.") from error
        files = []
        try:
            for image in images or []:
                mime = mimetypes.guess_type(str(image))[0] or "image/png"
                files.append(("image", (image.name, image.open("rb"), mime)))
            response = requests.post(url, headers=request_headers, data=form, files=files or None, timeout=600)
        finally:
            for _, file_tuple in files:
                file_tuple[1].close()
        if not response.ok:
            detail = redact_sensitive_text(response.text[:1000], secret)
            raise SystemExit(f"ERROR: {operation} failed HTTP {response.status_code}: {detail}")
        return _decode_response(response.content, operation, secret)
    request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET", headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return _decode_response(response.read(), operation, secret)
    except urllib.error.HTTPError as error:
        detail = redact_sensitive_text(error.read().decode("utf-8", errors="replace").strip()[:1000], secret)
        raise SystemExit(f"ERROR: {operation} failed HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        detail = redact_sensitive_text(str(error), secret)
        raise SystemExit(f"ERROR: {operation} request failed: {detail}") from error


def build_payload(args: argparse.Namespace, model: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": args.prompt,
        "model": model,
        "n": args.n,
        "response_format": args.response_format,
    }
    for name in ("size", "quality", "background", "output_format"):
        value = getattr(args, name, None)
        if value:
            payload[name] = value
    return payload


def ensure_output_targets(out: Path, count: int, output_format: str) -> list[Path]:
    ext = output_format.lower().lstrip(".") or "png"
    if out.suffix and count == 1:
        out.parent.mkdir(parents=True, exist_ok=True)
        return [out]
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return [out / f"aiimagesee-{stamp}-{index + 1}.{ext}" for index in range(count)]


def download_url(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=600) as response:
            return response.read()
    except urllib.error.URLError as error:
        raise SystemExit(f"ERROR: failed to download image URL: {error}") from error


def save_images(result: dict[str, Any], out: Path, output_format: str) -> list[Path]:
    data = result.get("data")
    if not isinstance(data, list) or not data:
        raise SystemExit("ERROR: upstream response did not contain data images.")
    targets = ensure_output_targets(out, len(data), str(result.get("output_format") or output_format))
    saved: list[Path] = []
    for item, target in zip(data, targets):
        if not isinstance(item, dict):
            continue
        if item.get("b64_json"):
            content = base64.b64decode(str(item["b64_json"]))
        elif item.get("url"):
            content = download_url(str(item["url"]))
        else:
            continue
        target.write_bytes(content)
        saved.append(target)
    if not saved:
        raise SystemExit("ERROR: no supported b64_json or url image content found.")
    return saved


def validate_images(images: list[str]) -> list[Path]:
    if not images:
        raise SystemExit("ERROR: edit mode requires at least one --image path.")
    if len(images) > MAX_EDIT_REFERENCE_IMAGES:
        raise SystemExit(f"ERROR: edit mode supports at most {MAX_EDIT_REFERENCE_IMAGES} reference images.")
    paths = [Path(value) for value in images]
    for path in paths:
        if not path.exists() or not path.is_file():
            raise SystemExit(f"ERROR: reference image not found: {path}")
        if path.stat().st_size > MAX_REFERENCE_IMAGE_BYTES:
            raise SystemExit(f"ERROR: reference image exceeds 20MB: {path}")
        mime = mimetypes.guess_type(str(path))[0] or ""
        if not mime.startswith("image/"):
            raise SystemExit(f"ERROR: reference file does not look like an image: {path}")
    return paths


def model_id(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        value = item.get("id") or item.get("name")
        return str(value).strip() if value else ""
    return ""


def fetch_models(env: dict[str, str], api_key: str) -> list[dict[str, Any]]:
    url = parse_api_url(api_url(env, "models"), "models URL")
    result = request_json(url, upstream_headers(env, api_key, json_content=False), "model list", api_key)
    data = result.get("data", result.get("models", []))
    if isinstance(data, dict):
        data = list(data.values())
    if not isinstance(data, list):
        raise SystemExit("ERROR: model list response has no data array.")
    models = []
    for item in data:
        identifier = model_id(item)
        if identifier:
            models.append(item if isinstance(item, dict) else {"id": identifier})
    return models


def model_ids(models: list[dict[str, Any]]) -> set[str]:
    return {model_id(item) for item in models if model_id(item)}


def settings_path() -> Path:
    return CONFIG_DIR / "settings.json"


def load_settings() -> dict[str, Any]:
    try:
        value = json.loads(settings_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    target = settings_path()
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def current_model(explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    return str(load_settings().get("model") or DEFAULT_MODEL)


def command_config(args: argparse.Namespace) -> int:
    env = merged_env(resolve_env_path(args.env_path))
    print(f"api_key: {'SET' if has_api_key() else 'MISSING'}")
    print(f"api_key_storage: {'Windows DPAPI' if os.name == 'nt' else 'OS keychain'}")
    print(f"generation_url: {api_url(env, 'generate')}")
    print(f"edit_url: {api_url(env, 'edit')}")
    print(f"models_url: {api_url(env, 'models')}")
    print(f"http_client: {'curl' if curl_executable() else 'python'}")
    gui_python = load_settings().get("gui_python")
    print(f"gui_python: {gui_python or 'auto-detect on demand'}")
    last_dialog = read_dialog_state()
    if last_dialog:
        print(f"last_dialog: {last_dialog}")
    print(f"default_model: {current_model(args.model)}")
    print(f"default_size: {args.size}")
    print(f"default_quality: {args.quality}")
    print(f"default_output_format: {args.output_format}")
    return 0


def command_configure_key(args: argparse.Namespace) -> int:
    """Open the masked key window and wait for the user to save or cancel."""
    if getattr(args, "terminal", False):
        return configure_key_terminal()
    if getattr(args, "detach", False):
        return spawn_detached_dialog()
    # --gui-only is the internal flag used by the detached child.
    return configure_key_dialog(gui_only=bool(getattr(args, "gui_only", False)))


def command_clear_key(_args: argparse.Namespace) -> int:
    try:
        existing = load_api_key()
        if not existing:
            print("No locally stored API key was found.")
            return 0
        existing = ""
        answer = input("Delete the locally stored API key? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Existing key kept.")
            return 0
        deleted = delete_api_key()
    except (CredentialError, EOFError, OSError) as error:
        raise SystemExit("ERROR: could not safely remove the locally stored API key.") from error
    print("Local API key removed." if deleted else "No locally stored API key was found.")
    return 0


def command_models(args: argparse.Namespace) -> int:
    env = merged_env(resolve_env_path(args.env_path))
    models = fetch_models(env, require_api_key())
    if args.json:
        print(json.dumps(models, ensure_ascii=False, indent=2))
    else:
        if not models:
            print("No models are currently available to this key.")
        for item in models:
            details = []
            for field in ("owned_by", "object", "description"):
                value = item.get(field) if isinstance(item, dict) else None
                if value:
                    details.append(f"{field}={value}")
            print(model_id(item) + ("  (" + ", ".join(details) + ")" if details else ""))
    return 0


def command_model_show(_args: argparse.Namespace) -> int:
    settings = load_settings()
    print(f"model: {settings.get('model') or DEFAULT_MODEL}")
    return 0


def command_model_set(args: argparse.Namespace) -> int:
    value = args.model_id.strip()
    if not value or any(char.isspace() for char in value):
        raise SystemExit("ERROR: model ID must be a non-empty token without whitespace.")
    settings = load_settings()
    settings["model"] = value
    save_settings(settings)
    print(f"default model saved: {value}")
    print("The ID will be passed through as requested; run 'models' to check this key's current group.")
    return 0


def command_generate(args: argparse.Namespace) -> int:
    if not args.prompt.strip():
        raise SystemExit("ERROR: --prompt is required.")
    env = merged_env(resolve_env_path(args.env_path))
    api_key = require_api_key()
    model = current_model(args.model)
    url = parse_api_url(api_url(env, "generate"), "generation upstream URL")
    payload = build_payload(args, model)
    print(f"generation_upstream: {url}")
    print(f"model: {model}, size: {args.size}, quality: {args.quality}, n: {args.n}")
    result = request_json(url, upstream_headers(env, api_key, json_content=True), "upstream generation", api_key,
                          body=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    for path in save_images(result, Path(args.out), args.output_format):
        print(f"saved: {path}")
    return 0


def command_edit(args: argparse.Namespace) -> int:
    if not args.prompt.strip():
        raise SystemExit("ERROR: --prompt is required.")
    images = validate_images(args.image)
    env = merged_env(resolve_env_path(args.env_path))
    api_key = require_api_key()
    model = current_model(args.model)
    url = parse_api_url(api_url(env, "edit"), "edit upstream URL")
    payload = build_payload(args, model)
    print(f"edit_upstream: {url}")
    print(f"model: {model}, size: {args.size}, quality: {args.quality}, n: {args.n}, references: {len(images)}")
    result = request_json(url, upstream_headers(env, api_key, json_content=False), "upstream edit", api_key,
                          form=payload, images=images)
    for path in save_images(result, Path(args.out), args.output_format):
        print(f"saved: {path}")
    return 0


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--env-path", default=None, help="Optional path to an explicit endpoint/client-settings override file.")
    parser.add_argument("--model", default=None, help="Model ID; defaults to your saved choice or gpt-image-2.5-sunburst.")
    parser.add_argument("--size", default=DEFAULT_SIZE)
    parser.add_argument("--quality", default=DEFAULT_QUALITY, help="Passed through unchanged, including xhigh and max.")
    parser.add_argument("--response-format", default="b64_json", choices=["b64_json", "url"])
    parser.add_argument("--background", default="opaque")
    parser.add_argument("--output-format", default="png")
    parser.add_argument("--n", type=int, default=1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and edit images with the image.aicodeme.xyz API.")
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("configure-key", help="Open the masked local key window and save the key securely.")
    setup.add_argument("--detach", action="store_true", help="Open the window in its own process and return immediately.")
    setup.add_argument("--terminal", action="store_true", help="Use hidden terminal input instead of opening a window.")
    setup.add_argument("--gui-only", action="store_true", help=argparse.SUPPRESS)
    setup.set_defaults(func=command_configure_key)

    clear_key = sub.add_parser("clear-key", help="Remove the locally saved API key after confirmation.")
    clear_key.set_defaults(func=command_clear_key)

    config = sub.add_parser("config", help="Check configuration without showing secrets.")
    add_common_arguments(config)
    config.set_defaults(func=command_config)

    models = sub.add_parser("models", help="List models accessible to the currently configured key/group.")
    models.add_argument("--env-path", default=None)
    models.add_argument("--json", action="store_true")
    models.set_defaults(func=command_models)

    model = sub.add_parser("model", help="Show or change the saved default model.")
    model_sub = model.add_subparsers(dest="model_action", required=True)
    show = model_sub.add_parser("show", help="Show the current default model.")
    show.set_defaults(func=command_model_show)
    set_model = model_sub.add_parser("set", help="Save a model ID; IDs returned by models are recommended.")
    set_model.add_argument("model_id")
    set_model.add_argument("--env-path", default=None)
    set_model.set_defaults(func=command_model_set)

    generate = sub.add_parser("generate", help="Generate images from a text prompt.")
    add_common_arguments(generate)
    generate.add_argument("--prompt", required=True)
    generate.add_argument("--out", required=True, help="Output file for n=1, or output directory for multiple images.")
    generate.set_defaults(func=command_generate)

    edit = sub.add_parser("edit", help="Edit images using one or more reference images.")
    add_common_arguments(edit)
    edit.add_argument("--prompt", required=True)
    edit.add_argument("--image", action="append", required=True, help="Reference image path. Repeat for multiple images.")
    edit.add_argument("--out", required=True, help="Output file for n=1, or output directory for multiple images.")
    edit.set_defaults(func=command_edit)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "n", 1) < 1:
        raise SystemExit("ERROR: --n must be >= 1.")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
