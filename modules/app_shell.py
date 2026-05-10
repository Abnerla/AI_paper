# -*- coding: utf-8 -*-
"""
纸研社桌面应用主壳（窗口、导航与各页面挂载）。
"""

import os
import sys
import ctypes
import importlib
import io
import json
import math
import shutil
import subprocess
import threading
import time
import webbrowser
import zipfile
import base64
import urllib.parse
import urllib.request
import urllib.error
try:
    import pystray
except Exception:
    pystray = None
try:
    from PIL import Image as PILImage
except Exception:
    PILImage = None
try:
    from ctypes import wintypes
except (ImportError, ValueError):
    wintypes = None
from datetime import datetime
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from modules.runtime_paths import get_runtime_paths, refresh_runtime_paths

try:
    import winreg
except ImportError:
    winreg = None

RUNTIME_PATHS = get_runtime_paths()
BASE_DIR = RUNTIME_PATHS.resource_root
APP_DIR = RUNTIME_PATHS.app_root
BASE_DATA_DIR = RUNTIME_PATHS.base_data_root

REPO_RAW_BASE_URL = 'https://raw.githubusercontent.com/Abnerla/AI_paper/main'
STARTUP_REG_PATH = r'Software\Microsoft\Windows\CurrentVersion\Run'
STARTUP_VALUE_NAME = "APP_NAME"
TOP_NAV_ITEMS = (
    ('home', '首页'),
    ('paper_write', '论文写作'),
    ('ai_reduce', '降AI检测'),
    ('plagiarism', '降查重率'),
    ('polish', '学术润色'),
    ('correction', '智能纠错'),
    ('history', '历史记录'),
)
GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
MONITOR_DEFAULTTONEAREST = 0x00000002
SPI_GETWORKAREA = 0x0030
WINDOW_DESIGN_WIDTH = 1600
WINDOW_DESIGN_HEIGHT = 900
WINDOW_WORKAREA_MARGIN_X = 96
WINDOW_WORKAREA_MARGIN_Y = 80

sys.path.insert(0, BASE_DIR)

from modules.app_metadata import APP_NAME, APP_VERSION
from modules.config import ConfigManager, resolve_model_display_name
from modules.api_client import APIClient
from modules.app_bridge import AppBridge
from modules.history import HistoryManager
from modules.remote_content import RemoteContentManager, compare_versions, normalize_version
from modules.runtime_logging import RuntimeLogStream, format_exception_trace
from modules.skills_runtime import SkillManager
from modules.task_runner import TaskRunner
from modules.ui_components import (
    apply_adaptive_window_geometry,
    bind_adaptive_wrap,
    CardFrame,
    COLORS,
    create_home_shell_button,
    FONTS,
    ModernButton,
    ModernEntry,
    ScrollablePage,
    THEMES,
    ToolIconButton,
    apply_theme_to_tree,
    configure_fonts,
    get_resource_path,
    get_system_theme,
    load_image,
    resolve_theme_mode,
    set_theme_mode,
    setup_styles,
)


def enable_high_dpi():
    """在创建 Tk 窗口前启用高 DPI 感知，避免系统缩放导致整窗发糊。"""
    if sys.platform != 'win32':
        return

    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


if wintypes is not None:
    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ('cbSize', wintypes.DWORD),
            ('rcMonitor', wintypes.RECT),
            ('rcWork', wintypes.RECT),
            ('dwFlags', wintypes.DWORD),
        ]
else:
    MONITORINFO = None


class WindowControlButton(tk.Canvas):
    """Classic Windows-like title bar control."""

    def __init__(self, parent, role, command=None, is_maximized=None, **kwargs):
        self.role = role
        self.command = command
        self.is_maximized = is_maximized or (lambda: False)
        self._visual_state = 'normal'
        kwargs.setdefault('width', 44)
        kwargs.setdefault('height', 44)
        kwargs.setdefault('bg', COLORS['nav_bg'])
        kwargs.setdefault('bd', 0)
        kwargs.setdefault('highlightthickness', 0)
        kwargs.setdefault('cursor', 'hand2')
        super().__init__(parent, **kwargs)
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self.bind('<ButtonPress-1>', self._on_press)
        self.bind('<ButtonRelease-1>', self._on_release)
        self.refresh()

    def _palette(self):
        close_base = COLORS['accent_light']
        close_hover = COLORS['accent']
        close_pressed = COLORS['btn_hover']
        base = COLORS['card_bg']
        hover = COLORS['surface_alt']
        pressed = COLORS['accent_light']
        return {
            'slot_bg': COLORS['nav_bg'],
            'border': COLORS['card_border'],
            'icon': COLORS['card_border'],
            'button_bg': {
                'normal': close_base if self.role == 'close' else base,
                'hover': close_hover if self.role == 'close' else hover,
                'pressed': close_pressed if self.role == 'close' else pressed,
            }.get(self._visual_state, close_base if self.role == 'close' else base),
        }

    def refresh(self):
        self._draw()

    def _draw(self):
        palette = self._palette()
        width = max(self.winfo_width(), int(self.cget('width')))
        height = max(self.winfo_height(), int(self.cget('height')))
        side = min(width, height)
        offset_x = (width - side) / 2
        offset_y = (height - side) / 2
        self.configure(bg=palette['slot_bg'])
        self.delete('all')

        inset = max(3, round(side * 0.12))
        left = offset_x + inset
        top = offset_y + inset
        right = offset_x + side - inset
        bottom = offset_y + side - inset
        self.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=palette['button_bg'],
            outline=palette['border'],
            width=2,
        )

        role = 'restore' if self.role == 'maximize' and self.is_maximized() else self.role
        if role == 'minimize':
            y = offset_y + side * 0.68
            self.create_line(
                offset_x + side * 0.28,
                y,
                offset_x + side * 0.72,
                y,
                fill=palette['icon'],
                width=2.5,
                capstyle=tk.PROJECTING,
            )
            return

        if role == 'maximize':
            self.create_rectangle(
                offset_x + side * 0.28,
                offset_y + side * 0.24,
                offset_x + side * 0.72,
                offset_y + side * 0.70,
                outline=palette['icon'],
                width=2,
            )
            return

        if role == 'restore':
            self.create_rectangle(
                offset_x + side * 0.34,
                offset_y + side * 0.31,
                offset_x + side * 0.75,
                offset_y + side * 0.72,
                outline=palette['icon'],
                width=2,
            )
            self.create_rectangle(
                offset_x + side * 0.22,
                offset_y + side * 0.20,
                offset_x + side * 0.63,
                offset_y + side * 0.61,
                outline=palette['icon'],
                width=2,
            )
            self.create_line(
                offset_x + side * 0.34,
                offset_y + side * 0.31,
                offset_x + side * 0.63,
                offset_y + side * 0.31,
                fill=palette['button_bg'],
                width=3,
            )
            return

        if role == 'close':
            self.create_line(
                offset_x + side * 0.30,
                offset_y + side * 0.28,
                offset_x + side * 0.70,
                offset_y + side * 0.72,
                fill=palette['icon'],
                width=2.2,
            )
            self.create_line(
                offset_x + side * 0.70,
                offset_y + side * 0.28,
                offset_x + side * 0.30,
                offset_y + side * 0.72,
                fill=palette['icon'],
                width=2.2,
            )

    def _on_enter(self, _event=None):
        self._visual_state = 'hover'
        self.refresh()

    def _on_leave(self, _event=None):
        self._visual_state = 'normal'
        self.refresh()

    def _on_press(self, _event=None):
        self._visual_state = 'pressed'
        self.refresh()

    def _on_release(self, event):
        inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        self._visual_state = 'hover' if inside else 'normal'
        self.refresh()
        if inside and callable(self.command):
            self.command()


class SmartPaperTool:
    """纸研社主程序"""

    def __init__(self):
        enable_high_dpi()
        self.root = tk.Tk()
        self._startup_started_at = time.perf_counter()
        self._startup_metrics = {}
        self._startup_steps = []
        self._startup_step_index = 0
        self._startup_complete = False
        self._shell_repair_job = None
        self._startup_page_id = 'home'
        self._page_warmup_queue = []
        self._page_class_cache = {}
        self._page_module_mtimes = {}
        self._page_specs = self._build_page_specs()
        self.root.withdraw()
        self.root.bind('<Map>', self._handle_root_map, add='+')
        self._loading_win = self._show_loading_screen()
        self.design_window_width = WINDOW_DESIGN_WIDTH
        self.design_window_height = WINDOW_DESIGN_HEIGHT
        self.window_workarea_margin_x = WINDOW_WORKAREA_MARGIN_X
        self.window_workarea_margin_y = WINDOW_WORKAREA_MARGIN_Y
        self.min_window_width = self.design_window_width
        self.min_window_height = self.design_window_height
        self.startup_window_width = self.design_window_width
        self.startup_window_height = self.design_window_height
        self.config_mgr = None
        self.history_mgr = None
        self.api_client = None
        self.runtime_paths = RUNTIME_PATHS
        self.launch_silently = '--silent-start' in sys.argv
        self.logs_dir = ''
        self.temp_dir = ''
        self.log_path = ''
        self._sync_runtime_paths(self.runtime_paths)
        self._runtime_log_hooks_installed = False
        self._runtime_log_closed = False
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._original_excepthook = sys.excepthook
        self._original_threading_excepthook = getattr(threading, 'excepthook', None)
        self._original_tk_exception_handler = None
        self._last_status_log_signature = None
        self.current_page_id = None
        self.nav_buttons = {}
        self.nav_button_shells = []
        self.nav_button_borders = []
        self.pages = {}
        self.page_titles = {}
        self.tool_buttons = []
        self.tool_button_shells = []
        self.tool_button_borders = []
        self.tool_button_images = {}
        self._top_tool_icon_cache = {}
        self.theme_tool_button = None
        self.dialogs = []
        self.brand_logo = None
        self.user_logo = None
        self.user_canvas = None
        self.user_logo_label = None
        self.user_content = None
        self.user_row = None
        self.username_label = None
        self.user_arrow = None
        self._user_display_name = ''
        self.icon_image = None
        self.window_chrome = None
        self.window_chrome_inner = None
        self.window_drag_region = None
        self.window_controls = None
        self.window_chrome_divider = None
        self.window_icon_label = None
        self.window_title_label = None
        self.window_control_buttons = {}
        self._custom_window_chrome_enabled = False
        self._window_drag_origin = None
        self._window_is_maximized = False
        self._window_restore_geometry = None
        self._top_nav_layout_job = None
        self._top_nav_last_width = None
        self._top_nav_last_stack_state = None
        self._tray_icon = None
        self._tray_thread = None
        self._is_tray_minimized = False
        self._is_shutting_down = False
        self._tray_hint_shown = False
        self._webdav_auto_sync_job = None
        self._webdav_auto_sync_busy = False
        self._webdav_auto_sync_last_error = ''
        self.settings_window = None
        self._api_config_window = None
        self._dialog_api_page = None
        self._api_config_tip = None
        self._api_config_return_to_model_list = False
        self._theme_menu_window = None
        self._theme_menu_root_click_bind = None
        self._theme_menu_focusout_bind = None
        self._theme_menu_unmap_bind = None
        self._prompt_manager_window = None
        self._prompt_manager_panel = None
        self._prompt_compact_window = None
        self._prompt_compact_panel = None
        self._skills_center_window = None
        self._skills_center_panel = None
        self._discover_skills_window = None
        self._discover_skills_panel = None
        self._repo_manage_window = None
        self._remote_content = None
        self.skill_manager = None
        self._version_check_anim_job = None
        self._version_check_button = None
        self._version_check_busy = False
        self._pending_version_update_data = None
        self.bell_button = None
        self.bell_badge = None
        self._bell_badge_visible = False
        self.app_bridge = self._build_app_bridge()
        self.task_runner = TaskRunner(self.root, set_status=self._set_status)

        self.root.after(0, self._start_startup_sequence)

    def _sync_runtime_paths(self, runtime_paths=None):
        self.runtime_paths = runtime_paths or refresh_runtime_paths()
        self.logs_dir = self.runtime_paths.logs_dir
        self.temp_dir = self.runtime_paths.temp_dir
        self.log_path = os.path.join(self.logs_dir, 'paperlab.log')

    def _configure_scaling(self):
        """根据实际 DPI 让 Tk 使用正确的字体和控件缩放。"""
        if sys.platform == 'win32':
            try:
                dpi = ctypes.windll.user32.GetDpiForWindow(self.root.winfo_id())
            except Exception:
                try:
                    dpi = int(self.root.winfo_fpixels('1i'))
                except Exception:
                    dpi = 96

            scaling = max(dpi / 72.0, 1.0)
            try:
                self.root.tk.call('tk', 'scaling', scaling)
            except tk.TclError:
                pass

        self._initialize_window_size_policy()

    def _initialize_window_size_policy(self):
        work_x, work_y, work_width, work_height = self._get_work_area()
        safe_width = max(1, int(work_width) - self.window_workarea_margin_x)
        safe_height = max(1, int(work_height) - self.window_workarea_margin_y)
        self.min_window_width = min(self.design_window_width, safe_width)
        self.min_window_height = min(self.design_window_height, safe_height)
        self.startup_window_width = self.min_window_width
        self.startup_window_height = self.min_window_height
        self.root.minsize(self.min_window_width, self.min_window_height)
        self.root.geometry(f'{self.startup_window_width}x{self.startup_window_height}')
        self._write_app_log(
            '[window_size_policy] '
            f'work_area={work_x},{work_y},{work_width}x{work_height} '
            f'min={self.min_window_width}x{self.min_window_height} '
            f'startup={self.startup_window_width}x{self.startup_window_height}'
        )

    def _build_page_specs(self):
        return {
            'home': {'module': 'pages.home_page', 'class': 'HomePage', 'title': '首页'},
            'api_config': {'module': 'pages.api_config_page', 'class': 'APIConfigPage', 'title': '模型配置'},
            'paper_write': {'module': 'pages.paper_write_page', 'class': 'PaperWritePage', 'title': '论文写作'},
            'ai_reduce': {'module': 'pages.ai_reduce_page', 'class': 'AIReducePage', 'title': '降AI检测'},
            'polish': {'module': 'pages.polish_page', 'class': 'PolishPage', 'title': '学术润色'},
            'correction': {'module': 'pages.correction_page', 'class': 'CorrectionPage', 'title': '智能纠错'},
            'plagiarism': {'module': 'pages.plagiarism_page', 'class': 'PlagiarismPage', 'title': '降查重率'},
            'history': {'module': 'pages.history_page', 'class': 'HistoryPage', 'title': '历史记录'},
        }

    def _start_startup_sequence(self):
        self._startup_steps = [
            ('scaling', self._configure_scaling),
            ('fonts', lambda: configure_fonts(self.root)),
            ('services', self._initialize_runtime_services),
            ('theme', self._initialize_window_theme),
            ('shell_chrome', self._build_window_chrome),
            ('shell_nav', self._build_top_nav),
            ('shell_content', self._build_content_area),
            ('shell_status', self._build_status_bar),
            ('page_load', self._preload_startup_page_class),
            ('page_build', self._build_startup_page),
            ('page_show', self._show_startup_page),
        ]
        self._run_next_startup_step()

    def _run_next_startup_step(self):
        if self._startup_step_index >= len(self._startup_steps):
            self._finish_startup_sequence()
            return

        step_key, callback = self._startup_steps[self._startup_step_index]
        started_at = time.perf_counter()
        try:
            callback()
        except Exception as exc:
            self._write_app_log(f'[startup_error] step={step_key} error={exc}', level='ERROR')
            self._loading_running = False
            self._close_loading_screen()
            self.root.deiconify()
            self.root.after(
                0,
                lambda message=str(exc): messagebox.showerror(
                    '启动失败',
                    f'应用启动时发生错误：\n{message}',
                    parent=self.root,
                ),
            )
            return

        self._startup_metrics[step_key] = time.perf_counter() - started_at
        self._startup_step_index += 1

        # 每步执行完后刷新加载窗口，让动画帧得以渲染，再立即调度下一步
        win = getattr(self, '_loading_win_ref', None)
        if win and win.winfo_exists():
            try:
                win.update()
            except Exception:
                pass
        self.root.after(0, self._run_next_startup_step)

    def _initialize_runtime_services(self):
        self._sync_runtime_paths()
        self.config_mgr = ConfigManager(BASE_DATA_DIR)
        self.history_mgr = HistoryManager(BASE_DATA_DIR)
        self._ensure_runtime_dirs()
        self._reset_runtime_log_file()
        self._install_runtime_log_hooks()
        self.api_client = APIClient(self.config_mgr, log_callback=self._write_app_log)
        self.skill_manager = SkillManager(self.config_mgr, api_client=self.api_client, log_callback=self._write_app_log)
        self.api_client.set_skills_runtime(self.skill_manager)
        self._remote_content = RemoteContentManager(self.root, log_callback=self._write_app_log)
        self._write_app_log(
            '[session_start] '
            f'pid={os.getpid()} '
            f'python={sys.version.split()[0]} '
            f'frozen={bool(getattr(sys, "frozen", False))} '
            f'app_dir={APP_DIR} '
            f'base_data_dir={self.runtime_paths.base_data_root} '
            f'data_dir={self.runtime_paths.data_root} '
            f'logs_dir={self.runtime_paths.logs_dir} '
            f'temp_dir={self.runtime_paths.temp_dir} '
            f'resource_dir={BASE_DIR}'
        )
        self._write_app_log(f'[session_args] argv={" ".join(sys.argv)}')
        self._schedule_webdav_auto_sync()

    def _initialize_window_theme(self):
        theme_mode = self.config_mgr.get_setting('theme_mode', 'light')
        set_theme_mode(theme_mode)
        setup_styles(self.root)
        self.root.title(APP_NAME)
        self.root.configure(bg=COLORS['bg_main'])
        self._set_window_icon()
        self.root.after_idle(lambda: self._apply_dwm_titlebar_color(resolve_theme_mode(theme_mode)))

    def _set_root_alpha_safe(self, alpha):
        try:
            self.root.attributes('-alpha', float(alpha))
            return True
        except (tk.TclError, ValueError, TypeError):
            return False

    def _build_ui_shell(self):
        _tb0 = time.perf_counter()
        self._build_top_nav()
        _tb1 = time.perf_counter()

        self._build_content_area()
        self._build_status_bar()
        _tb2 = time.perf_counter()
        self._write_app_log(
            f'[build_ui_shell] top_nav={_tb1-_tb0:.3f}s '
            f'status_bar={_tb2-_tb1:.3f}s'
        )

    def _build_content_area(self):
        self.content_view = ScrollablePage(self.root, bg=COLORS['bg_main'])
        self.content_view.pack(fill=tk.BOTH, expand=True, padx=26, pady=(20, 12))
        self.content_frame = self.content_view.inner

    def _preload_startup_page_class(self):
        self._startup_page_id = self._resolve_startup_page()
        self._load_page_class(self._startup_page_id)

    def _build_startup_page(self):
        self._ensure_page(self._startup_page_id)

    def _show_startup_page(self):
        self._show_page(self._startup_page_id, invoke_on_show=False)

    def _resolve_startup_page(self):
        startup_page = 'home'
        if self.config_mgr is not None:
            startup_page = self.config_mgr.get_setting('startup_page', 'home')
        if startup_page not in self._page_specs:
            startup_page = 'home'
        return startup_page

    def _initialize_startup_page(self):
        self._startup_page_id = self._resolve_startup_page()
        self._ensure_page(self._startup_page_id)
        self._show_page(self._startup_page_id)

    def _finish_startup_sequence(self):
        started_at = time.perf_counter()
        # 先恢复普通窗口尺寸，作为启动后“还原”时的目标几何
        restore_geometry = self._restore_or_center_window()
        if restore_geometry:
            self._window_restore_geometry = dict(restore_geometry)
        self._window_is_maximized = False
        startup_page = self.pages.get(self._startup_page_id)
        if startup_page and hasattr(startup_page, 'begin_startup_prelayout'):
            startup_page.begin_startup_prelayout()
        # 把主窗口移到屏幕外，让 Tkinter 在不可见位置完成真实布局计算
        if restore_geometry:
            size_part = f'{restore_geometry["width"]}x{restore_geometry["height"]}'
        else:
            size_part = f'{self.min_window_width}x{self.min_window_height}'
        self.root.geometry(f'{size_part}+99999+99999')
        alpha_hidden = self._set_root_alpha_safe(0.0)
        self._loading_running = False
        self.root.deiconify()
        self.root.update_idletasks()
        # 同步 ScrollablePage canvas → inner frame 宽度
        if hasattr(self, 'content_view'):
            canvas = self.content_view.canvas
            w = canvas.winfo_width()
            if w > 1:
                canvas.itemconfigure(self.content_view.window_id, width=w)
        self.root.update_idletasks()
        # 用真实尺寸执行首页全部自适应布局
        if startup_page:
            if hasattr(startup_page, '_fix_hero_button_sizes'):
                startup_page._fix_hero_button_sizes()
            if hasattr(startup_page, '_relayout_hero'):
                startup_page._relayout_hero()
            if hasattr(startup_page, '_relayout_dashboard'):
                startup_page._relayout_dashboard()
        self.root.update_idletasks()
        self.root.update()
        startup_page_prepared = False
        if startup_page and hasattr(startup_page, 'prepare_startup_display'):
            startup_page_prepared = bool(startup_page.prepare_startup_display())
            self.root.update_idletasks()
            self.root.update()
        pre_stabilized = False
        original_close_loading_screen = self._close_loading_screen
        self._close_loading_screen = lambda: None
        if startup_page and hasattr(startup_page, 'stabilize_startup_render'):
            pre_stabilized = bool(startup_page.stabilize_startup_render('startup_pre_maximize'))
            self.root.update_idletasks()
            self.root.update()
        # 布局完成后先关闭加载窗，再把主窗口切到最大化窗口状态
        self._close_loading_screen()
        self._maximize_window(remember_restore=False)
        self.root.update_idletasks()
        if hasattr(self, 'content_view'):
            canvas = self.content_view.canvas
            w = canvas.winfo_width()
            if w > 1:
                canvas.itemconfigure(self.content_view.window_id, width=w)
        self.root.update()
        prepared_on_show = False
        if startup_page and hasattr(startup_page, 'on_show'):
            startup_page.on_show()
            prepared_on_show = True
            if hasattr(startup_page, '_stabilize_usage_layout'):
                try:
                    startup_page._stabilize_usage_layout(refresh_usage=False)
                except TypeError:
                    startup_page._stabilize_usage_layout()
            self.root.update_idletasks()
            self.root.update()
        post_stabilized = False
        if startup_page and hasattr(startup_page, 'stabilize_startup_render'):
            post_stabilized = bool(startup_page.stabilize_startup_render('startup_post_on_show'))
            self.root.update_idletasks()
            self.root.update()
        self._write_app_log(
            f'[startup_page_stabilize] page={self._startup_page_id} '
            f'prepared={startup_page_prepared} '
            f'pre={pre_stabilized} post={post_stabilized} on_show={prepared_on_show}'
        )
        self.root.update_idletasks()
        self._rebuild_window_chrome_after_show()
        # 顶部导航在离屏预布局后，部分子控件的屏幕坐标不会自动修正。
        # 主窗口真正显示后立即重建一次，避免公告/模式/设置按钮叠在同一位置。
        self._rebuild_top_nav_after_show()
        if hasattr(self, 'content_view'):
            canvas = self.content_view.canvas
            w = canvas.winfo_width()
            if w > 1:
                canvas.itemconfigure(self.content_view.window_id, width=w)
        self._repair_shell_after_map()
        self.root.update_idletasks()
        self.root.update()
        if alpha_hidden:
            self._set_root_alpha_safe(1.0)
            self.root.update_idletasks()
        self._close_loading_screen = original_close_loading_screen
        self._close_loading_screen()
        self.root.update_idletasks()
        self._startup_complete = True
        if startup_page and hasattr(startup_page, 'finish_startup_prelayout'):
            startup_page.finish_startup_prelayout()
        if startup_page and hasattr(startup_page, 'on_show') and not prepared_on_show:
            self.root.after(40, lambda page_id=self._startup_page_id: self._invoke_page_on_show(page_id))
        self._startup_metrics['show'] = time.perf_counter() - started_at
        self._write_app_log(
            f'[startup] fonts={self._startup_metrics.get("fonts", 0.0):.3f}s '
            f'scaling={self._startup_metrics.get("scaling", 0.0):.3f}s '
            f'services={self._startup_metrics.get("services", 0.0):.3f}s '
            f'theme={self._startup_metrics.get("theme", 0.0):.3f}s '
            f'shell_chrome={self._startup_metrics.get("shell_chrome", 0.0):.3f}s '
            f'shell_nav={self._startup_metrics.get("shell_nav", 0.0):.3f}s '
            f'shell_content={self._startup_metrics.get("shell_content", 0.0):.3f}s '
            f'shell_status={self._startup_metrics.get("shell_status", 0.0):.3f}s '
            f'page_load={self._startup_metrics.get("page_load", 0.0):.3f}s '
            f'page_build={self._startup_metrics.get("page_build", 0.0):.3f}s '
            f'page_show={self._startup_metrics.get("page_show", 0.0):.3f}s '
            f'show={self._startup_metrics.get("show", 0.0):.3f}s '
            f'total={time.perf_counter() - self._startup_started_at:.3f}s'
        )
        self._write_app_log('应用启动')

        self._write_app_log(
            f'[startup] fonts={self._startup_metrics.get("fonts", 0.0):.3f}s '
            f'scaling={self._startup_metrics.get("scaling", 0.0):.3f}s '
            f'services={self._startup_metrics.get("services", 0.0):.3f}s '
            f'theme={self._startup_metrics.get("theme", 0.0):.3f}s '
            f'shell={self._startup_metrics.get("shell", 0.0):.3f}s '
            f'startup_page={self._startup_metrics.get("startup_page", 0.0):.3f}s '
            f'show={self._startup_metrics.get("show", 0.0):.3f}s '
            f'total={time.perf_counter() - self._startup_started_at:.3f}s'
        )

        self._page_warmup_queue = [
            page_id for page_id in self._page_specs
            if page_id not in {self._startup_page_id, 'api_config'}
        ]
        if self._page_warmup_queue:
            self.root.after(120, self._warmup_remaining_pages)

        if self.launch_silently:
            self.root.after(180, self._apply_silent_launch)

        self.root.after(500, self._prefetch_announcement)
        self.root.after(650, self._prefetch_push)
        self.root.after(900, self._check_version_update_on_startup)

    def _warmup_remaining_pages(self):
        if self._is_shutting_down or not self._page_warmup_queue:
            return

        page_id = self._page_warmup_queue.pop(0)
        started_at = time.perf_counter()
        try:
            # 预热时直接构建页面实例（隐藏），避免首次切页时同步创建导致卡顿与黑屏闪烁。
            self._ensure_page(page_id)
        except Exception as exc:
            self._write_app_log(f'[page_prewarm] {page_id} failed: {exc}', level='WARN')
        else:
            self._write_app_log(f'[page_prewarm] {page_id} init={time.perf_counter() - started_at:.3f}s')

        if self._page_warmup_queue:
            self.root.after(220, self._warmup_remaining_pages)

    def _load_page_class(self, page_id):
        if page_id not in self._page_specs:
            raise KeyError(page_id)

        module = self._refresh_page_module_if_needed(page_id)
        if page_id not in self._page_class_cache:
            spec = self._page_specs[page_id]
            module = module or importlib.import_module(spec['module'])
            self._page_module_mtimes[spec['module']] = self._get_page_module_mtime(module)
            self._page_class_cache[page_id] = getattr(module, spec['class'])
        return self._page_class_cache[page_id]

    def _create_page(self, page_id):
        page_class = self._load_page_class(page_id)
        if page_id in self.pages:
            return self.pages[page_id]
        started_at = time.perf_counter()
        page = page_class(
            self.content_frame,
            self.config_mgr,
            self.api_client,
            self.history_mgr,
            self._set_status,
            navigate_page=self._show_page,
            app_bridge=self.app_bridge,
        )
        page.frame.pack_forget()
        self.pages[page_id] = page
        self._write_app_log(f'[page_init] {page_id}={time.perf_counter() - started_at:.3f}s')
        return page

    def _ensure_page(self, page_id):
        if page_id not in self._page_specs:
            return None
        return self.pages.get(page_id) or self._create_page(page_id)

    def _get_page_module_mtime(self, module):
        module_path = getattr(module, '__file__', '')
        if not module_path or not os.path.exists(module_path):
            return None
        try:
            return os.path.getmtime(module_path)
        except OSError:
            return None

    def _refresh_page_module_if_needed(self, page_id):
        if getattr(sys, 'frozen', False):
            return None
        spec = self._page_specs.get(page_id)
        if not spec:
            return None

        module_name = spec['module']
        importlib.invalidate_caches()
        module = sys.modules.get(module_name)
        if module is None:
            return None

        current_mtime = self._get_page_module_mtime(module)
        cached_mtime = self._page_module_mtimes.get(module_name)
        if cached_mtime is None:
            self._page_module_mtimes[module_name] = current_mtime
            return module
        if current_mtime is None or current_mtime <= cached_mtime:
            return module

        module = importlib.reload(module)
        self._page_module_mtimes[module_name] = self._get_page_module_mtime(module)
        self._page_class_cache.pop(page_id, None)

        old_page = self.pages.pop(page_id, None)
        if old_page is not None:
            try:
                old_page.frame.destroy()
            except Exception:
                pass
            if self.current_page_id == page_id:
                self.current_page_id = None
        self._write_app_log(f'[page_reload] {page_id} source_updated')
        return module

    def _get_page_title(self, page_id):
        return self.page_titles.get(page_id) or self._page_specs.get(page_id, {}).get('title', page_id)

    def _get_startup_loading_palette(self):
        """根据已保存主题为启动加载窗选择配色。"""
        try:
            theme_mode = ConfigManager(BASE_DATA_DIR).get_setting('theme_mode', 'light')
            resolved = resolve_theme_mode(theme_mode)
        except Exception:
            resolved = 'light'
        return THEMES.get(resolved, THEMES['light']).copy()

    def _show_loading_screen(self):
        """显示加载动画窗口，主窗口初始化期间占位。"""
        from modules.ui_components import load_gif_frames
        palette = self._get_startup_loading_palette()
        window_bg = palette['bg_main']
        card_bg = palette['card_bg']
        border_color = palette['card_border']
        accent_color = palette['accent']
        title_color = palette['text_main']
        text_color = palette['text_sub']
        muted_color = palette['text_muted']
        divider_color = palette['divider']
        primary_color = palette['primary']

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.configure(bg=window_bg)

        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        w, h = 680, 350
        win.geometry(f'{w}x{h}+{(sw-w)//2}+{(sh-h)//2}')
        win.lift()
        win.attributes('-topmost', True)

        try:
            frames, frame_delays = load_gif_frames('loading.gif', max_size=(132, 132))
        except Exception:
            frames, frame_delays = [], []

        shell = tk.Frame(win, bg=border_color, bd=0, highlightthickness=0)
        shell.pack(fill=tk.BOTH, expand=True, padx=18, pady=18)

        card = tk.Frame(shell, bg=card_bg, bd=0, highlightthickness=0)
        card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        tk.Frame(card, bg=accent_color, width=10).pack(side=tk.LEFT, fill=tk.Y)

        content = tk.Frame(card, bg=card_bg, padx=22, pady=18)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)

        visual_panel = tk.Frame(content, bg=card_bg, width=154)
        visual_panel.grid(row=0, column=0, sticky='ns')
        visual_panel.pack_propagate(False)

        info_panel = tk.Frame(content, bg=card_bg)
        info_panel.grid(row=0, column=1, sticky='nsew', padx=(22, 4))
        info_panel.grid_columnconfigure(0, weight=1)

        tk.Label(
            info_panel,
            text='STARTUP',
            font=('Segoe UI', 10, 'bold'),
            fg=primary_color,
            bg=card_bg,
            anchor='w',
        ).grid(row=0, column=0, sticky='w')

        tk.Label(
            info_panel,
            text=APP_NAME,
            font=('Microsoft YaHei UI', 24, 'bold'),
            fg=title_color,
            bg=card_bg,
            anchor='w',
        ).grid(row=1, column=0, sticky='w', pady=(10, 0))

        wave_row = tk.Frame(info_panel, bg=card_bg)
        wave_row.grid(row=2, column=0, sticky='ew', pady=(16, 0))
        wave_row.grid_columnconfigure(0, weight=1)

        tk.Label(
            wave_row,
            text='LOADING',
            font=('Segoe UI', 10, 'bold'),
            fg=primary_color,
            bg=card_bg,
            anchor='w',
        ).grid(row=0, column=0, sticky='w')

        dots_canvas = tk.Canvas(
            wave_row,
            width=146,
            height=32,
            bg=card_bg,
            highlightthickness=0,
            bd=0,
        )
        dots_canvas.grid(row=0, column=1, sticky='e', padx=(16, 0))

        dot_items = []
        for _ in range(6):
            dot_items.append(dots_canvas.create_oval(0, 0, 0, 0, fill='#111111', outline=''))

        tk.Label(
            info_panel,
            text='正在准备工作区与页面组件',
            font=('Microsoft YaHei UI', 10),
            fg=text_color,
            bg=card_bg,
            anchor='w',
            justify='left',
            wraplength=360,
        ).grid(row=3, column=0, sticky='ew', pady=(14, 0))

        tk.Frame(info_panel, bg=divider_color, height=1).grid(row=4, column=0, sticky='ew', pady=(16, 16))

        tk.Label(
            info_panel,
            text='首次进入较慢时请稍候，资源加载完成后将自动进入主界面',
            font=('Microsoft YaHei UI', 9),
            fg=muted_color,
            bg=card_bg,
            justify='left',
            anchor='w',
            wraplength=360,
        ).grid(row=5, column=0, sticky='ew')

        self._loading_win_ref = win
        self._loading_running = True
        self._loading_after_id = None
        self._loading_animation_started_at = time.perf_counter()

        if frames:
            lbl = tk.Label(visual_panel, bg=card_bg, bd=0, highlightthickness=0)
            lbl.pack(expand=True)
            self._loading_frames = frames
            self._loading_frame_delays = frame_delays
            self._loading_idx = 0
            self._loading_label = lbl
            lbl.configure(image=frames[0])
        else:
            tk.Label(
                visual_panel,
                text='加载中',
                font=('Microsoft YaHei UI', 18, 'bold'),
                fg=primary_color,
                bg=card_bg,
            ).pack(expand=True)

        self._loading_dot_canvas = dots_canvas
        self._loading_dot_items = dot_items
        self._loading_dot_colors = {
            'dot': '#111111',
        }
        self._update_loading_dots()
        self._schedule_loading_animation()

        win.update()
        return win

    def _update_loading_dots(self):
        """更新右侧点状跳动动画。"""
        canvas = getattr(self, '_loading_dot_canvas', None)
        dot_items = getattr(self, '_loading_dot_items', [])
        if not canvas or not dot_items:
            return

        colors = getattr(self, '_loading_dot_colors', {})
        dot_color = colors.get('dot', '#111111')

        elapsed = time.perf_counter() - getattr(self, '_loading_animation_started_at', time.perf_counter())
        spacing = 22
        base_x = 9
        base_y = 20
        base_radius = 4.6
        jump_height = 9.0

        for index, dot in enumerate(dot_items):
            phase = (elapsed * 8.2) - (index * 0.72)
            wave = (math.sin(phase) + 1.0) / 2.0
            lift = wave ** 1.35
            radius = base_radius + (lift * 2.2)
            center_x = base_x + index * spacing
            center_y = base_y - (lift * jump_height)
            canvas.coords(
                dot,
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
            )
            canvas.itemconfigure(dot, fill=dot_color, outline=dot_color)

    def _advance_loading_animation(self):
        """推进启动页 GIF 与点阵动画一帧。"""
        win = getattr(self, '_loading_win_ref', None)
        if not win or not win.winfo_exists():
            return False

        if hasattr(self, '_loading_frames') and self._loading_frames:
            idx = self._loading_idx % len(self._loading_frames)
            self._loading_label.configure(image=self._loading_frames[idx])
            delays = getattr(self, '_loading_frame_delays', [])
            delay = delays[idx] if idx < len(delays) else 33
            self._loading_idx += 1
            self._loading_gif_after_id = win.after(delay, self._advance_loading_animation)

        return True

    def _schedule_loading_animation(self):
        """在事件循环可用时持续刷新启动页点阵动画（约60fps），GIF独立调度。"""
        win = getattr(self, '_loading_win_ref', None)
        if not getattr(self, '_loading_running', False) or not win or not win.winfo_exists():
            return

        self._update_loading_dots()
        self._loading_after_id = win.after(16, self._schedule_loading_animation)

        if not hasattr(self, '_loading_gif_after_id'):
            self._loading_gif_after_id = None
            self._advance_loading_animation()

    def _close_loading_screen(self):
        """停止动画并销毁加载窗口。"""
        self._loading_running = False
        if hasattr(self, '_loading_after_id'):
            try:
                self.root.after_cancel(self._loading_after_id)
            except Exception:
                pass
        if hasattr(self, '_loading_gif_after_id') and self._loading_gif_after_id:
            try:
                self.root.after_cancel(self._loading_gif_after_id)
            except Exception:
                pass
        if hasattr(self, '_loading_win_ref'):
            try:
                self._loading_win_ref.destroy()
            except Exception:
                pass
        self._loading_dot_canvas = None
        self._loading_dot_items = []

    def _set_window_icon(self):
        icon_path = get_resource_path('logo.png')
        if os.path.exists(icon_path):
            try:
                self.icon_image = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, self.icon_image)
            except Exception:
                pass

    def _center_window(self, win=None, geometry=None):
        if win is None:
            win = self.root
        if geometry:
            apply_adaptive_window_geometry(win, geometry)
            return
        win.update_idletasks()
        width = win.winfo_width()
        height = win.winfo_height()
        screen_width = win.winfo_screenwidth()
        screen_height = win.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        win.geometry(f'{width}x{height}+{x}+{y}')

    def _restore_or_center_window(self):
        """恢复上次窗口位置，若无记录则居中显示。"""
        work_x, work_y, work_width, work_height = self._get_work_area()
        safe_width = max(self.min_window_width, int(work_width) - self.window_workarea_margin_x)
        safe_height = max(self.min_window_height, int(work_height) - self.window_workarea_margin_y)
        geometry = None
        if self.config_mgr is None:
            geometry = self._get_centered_root_geometry()
            self._apply_window_geometry(geometry)
            return geometry

        saved_x = self.config_mgr.get_setting('window_x', None)
        saved_y = self.config_mgr.get_setting('window_y', None)
        saved_w = self.config_mgr.get_setting('window_w', None)
        saved_h = self.config_mgr.get_setting('window_h', None)

        if saved_x is not None and saved_y is not None and saved_w is not None and saved_h is not None:
            try:
                w = min(max(int(saved_w), self.min_window_width), safe_width)
                h = min(max(int(saved_h), self.min_window_height), safe_height)
                x = max(int(work_x), min(int(saved_x), int(work_x) + max(0, int(work_width) - w)))
                y = max(int(work_y), min(int(saved_y), int(work_y) + max(0, int(work_height) - h)))
                geometry = {'x': x, 'y': y, 'width': w, 'height': h}
                self._apply_window_geometry(geometry)
                return geometry
            except Exception:
                pass

        geometry = self._get_centered_root_geometry()
        self._apply_window_geometry(geometry)
        return geometry

    def _get_centered_root_geometry(self):
        work_x, work_y, work_width, work_height = self._get_work_area()
        width = min(self.startup_window_width, max(1, int(work_width) - self.window_workarea_margin_x))
        height = min(self.startup_window_height, max(1, int(work_height) - self.window_workarea_margin_y))
        x = int(work_x) + max(0, (int(work_width) - width) // 2)
        y = int(work_y) + max(0, (int(work_height) - height) // 2)
        return {
            'x': x,
            'y': y,
            'width': width,
            'height': height,
        }

    def _maximize_window(self, remember_restore=True):
        if self._window_is_maximized:
            return
        if remember_restore or self._window_restore_geometry is None:
            self._window_restore_geometry = self._capture_window_geometry()
        x, y, width, height = self._get_work_area()
        frame_width, frame_height = self._get_window_frame_size()
        target_width = max(1, width - frame_width)
        target_height = max(1, height - frame_height)
        self.root.geometry(f'{target_width}x{target_height}+{x}+{y}')
        self.root.update_idletasks()
        self._fit_window_to_work_area(x, y, width, height)
        self._window_is_maximized = True
        self._refresh_window_chrome()

    def _get_window_frame_size(self):
        if sys.platform != 'win32':
            return 0, 0
        try:
            hwnd = self._get_root_hwnd()
            if not hwnd:
                return 0, 0
            rect = wintypes.RECT()
            if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return 0, 0
            self.root.update_idletasks()
            outer_width = rect.right - rect.left
            outer_height = rect.bottom - rect.top
            inner_width = self.root.winfo_width()
            inner_height = self.root.winfo_height()
            return (
                max(0, outer_width - inner_width),
                max(0, outer_height - inner_height),
            )
        except Exception:
            return 0, 0

    def _fit_window_to_work_area(self, x, y, width, height):
        if sys.platform != 'win32':
            return
        try:
            hwnd = self._get_root_hwnd()
            if not hwnd:
                return
            rect = wintypes.RECT()
            if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return
            actual_width = rect.right - rect.left
            actual_height = rect.bottom - rect.top
            if (
                rect.left == x and
                rect.top == y and
                actual_width == width and
                actual_height == height
            ):
                return
            corrected_width = max(1, self.root.winfo_width() - (actual_width - width))
            corrected_height = max(1, self.root.winfo_height() - (actual_height - height))
            self.root.geometry(f'{corrected_width}x{corrected_height}+{x}+{y}')
        except Exception:
            return

    def _ensure_runtime_dirs(self):
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

    def _reset_runtime_log_file(self):
        self._ensure_runtime_dirs()
        with open(self.log_path, 'w', encoding='utf-8') as handle:
            handle.write('')
        self._runtime_log_closed = False

    def _clear_runtime_log_file(self):
        self._ensure_runtime_dirs()
        with open(self.log_path, 'w', encoding='utf-8') as handle:
            handle.write('')
        self._runtime_log_closed = True

    def _install_runtime_log_hooks(self):
        if self._runtime_log_hooks_installed:
            return

        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._original_excepthook = sys.excepthook
        self._original_threading_excepthook = getattr(threading, 'excepthook', None)
        self._original_tk_exception_handler = getattr(self.root, 'report_callback_exception', None)

        sys.stdout = RuntimeLogStream(self._write_app_log, level='STDOUT', mirror=self._original_stdout)
        sys.stderr = RuntimeLogStream(self._write_app_log, level='STDERR', mirror=self._original_stderr)
        sys.excepthook = self._handle_uncaught_exception
        if hasattr(threading, 'excepthook'):
            threading.excepthook = self._handle_thread_exception
        self.root.report_callback_exception = self._handle_tk_callback_exception
        self._runtime_log_hooks_installed = True

    def _restore_runtime_log_hooks(self):
        if not self._runtime_log_hooks_installed:
            return

        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr
        sys.excepthook = self._original_excepthook
        if hasattr(threading, 'excepthook') and self._original_threading_excepthook is not None:
            threading.excepthook = self._original_threading_excepthook
        if self._original_tk_exception_handler is not None:
            self.root.report_callback_exception = self._original_tk_exception_handler
        self._runtime_log_hooks_installed = False

    def _handle_uncaught_exception(self, exc_type, exc_value, exc_traceback):
        self._write_app_log(
            f'[uncaught_exception]\n{format_exception_trace(exc_type, exc_value, exc_traceback)}',
            level='ERROR',
        )

    def _handle_thread_exception(self, args):
        self._write_app_log(
            '[thread_exception] '
            f'thread={getattr(args.thread, "name", "unknown")}\n'
            f'{format_exception_trace(args.exc_type, args.exc_value, args.exc_traceback)}',
            level='ERROR',
        )

    def _handle_tk_callback_exception(self, exc_type, exc_value, exc_traceback):
        self._write_app_log(
            f'[tk_callback_exception]\n{format_exception_trace(exc_type, exc_value, exc_traceback)}',
            level='ERROR',
        )

    def _write_app_log(self, message, level='INFO'):
        if self._runtime_log_closed:
            return
        self._ensure_runtime_dirs()
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(self.log_path, 'a', encoding='utf-8') as handle:
                text = str(message or '').replace('\r\n', '\n').replace('\r', '\n')
                lines = text.split('\n') or ['']
                for line in lines:
                    if not line.strip():
                        continue
                    handle.write(f'[{timestamp}] [{str(level or "INFO").upper()}] {line}\n')
        except Exception:
            pass

    def _open_directory(self, path):
        os.makedirs(path, exist_ok=True)
        try:
            if sys.platform == 'win32':
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
            return True
        except Exception as exc:
            messagebox.showerror('打开目录失败', f'无法打开目录：\n{path}\n\n{exc}', parent=self.root)
            return False

    def _clear_directory_contents(self, directory):
        if not os.path.exists(directory):
            return 0

        removed = 0
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                removed += 1
            except Exception:
                continue
        return removed

    def _build_startup_command(self, silent=False):
        if getattr(sys, 'frozen', False):
            command = [sys.executable]
        else:
            pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
            command = [pythonw if os.path.exists(pythonw) else sys.executable, os.path.join(APP_DIR, 'main.py')]

        if silent:
            command.append('--silent-start')
        return subprocess.list2cmdline(command)

    def _set_launch_on_startup(self, enabled, silent=False):
        if sys.platform != 'win32' or winreg is None:
            raise RuntimeError('当前系统不支持开机启动注册表配置。')

        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_PATH)
        try:
            if enabled:
                winreg.SetValueEx(key, STARTUP_VALUE_NAME, 0, winreg.REG_SZ, self._build_startup_command(silent=silent))
            else:
                try:
                    winreg.DeleteValue(key, STARTUP_VALUE_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)

    def _apply_silent_launch(self):
        try:
            self.root.iconify()
            self._write_app_log('已按静默启动模式最小化窗口')
        except Exception:
            pass

    @staticmethod
    def _widget_exists(widget):
        try:
            return bool(widget) and bool(widget.winfo_exists())
        except tk.TclError:
            return False

    def _cancel_version_check_animation(self):
        if self._version_check_anim_job is None:
            return
        try:
            self.root.after_cancel(self._version_check_anim_job)
        except Exception:
            pass
        self._version_check_anim_job = None

    def _reset_version_check_button(self, button=None, *, text='检查更新', style='primary', delay_ms=0):
        target_button = button or self._version_check_button

        def apply():
            self._cancel_version_check_animation()
            self._version_check_busy = False
            self._version_check_button = None
            if not self._widget_exists(target_button):
                return
            try:
                if hasattr(target_button, 'set_style'):
                    target_button.set_style(style)
                target_button.configure(
                    text=text,
                    state=tk.NORMAL,
                    cursor='hand2',
                    disabledforeground=COLORS['text_main'],
                )
            except tk.TclError:
                pass

        if delay_ms > 0:
            self.root.after(delay_ms, apply)
        else:
            apply()

    def _start_version_check_animation(self, button):
        if not self._widget_exists(button):
            return

        self._cancel_version_check_animation()
        self._version_check_button = button
        self._version_check_busy = True

        frames = ('检查中', '检查中.', '检查中..', '检查中...')
        state = {'index': 0}

        try:
            if hasattr(button, 'set_style'):
                button.set_style('warning')
            button.configure(
                state=tk.DISABLED,
                cursor='arrow',
                disabledforeground=COLORS['text_main'],
            )
        except tk.TclError:
            pass

        def tick():
            if not self._widget_exists(button):
                self._cancel_version_check_animation()
                self._version_check_busy = False
                self._version_check_button = None
                return
            try:
                button.configure(text=frames[state['index']])
            except tk.TclError:
                self._cancel_version_check_animation()
                self._version_check_busy = False
                self._version_check_button = None
                return
            state['index'] = (state['index'] + 1) % len(frames)
            self._version_check_anim_job = self.root.after(260, tick)

        tick()

    def _is_update_ignored(self, version):
        ignored_version = ''
        if self.config_mgr is not None:
            ignored_version = (self.config_mgr.get_setting('ignored_update_version', '') or '').strip()
        target_version = normalize_version(version)
        if not ignored_version or not target_version:
            return False
        return compare_versions(ignored_version, target_version) == 0

    def _remember_ignored_update(self, version):
        target_version = normalize_version(version)
        if not target_version or self.config_mgr is None:
            return False
        self.config_mgr.set_setting('ignored_update_version', target_version)
        saved = self.config_mgr.save()
        if saved:
            self._write_app_log(f'已忽略版本更新提醒: {target_version}')
        else:
            self._write_app_log(f'保存忽略版本更新提醒失败: {target_version}', level='WARN')
        return saved

    def _can_show_version_update_dialog(self):
        try:
            return (
                self.root.winfo_exists() and
                self.root.winfo_viewable() and
                self.root.state() != 'iconic'
            )
        except tk.TclError:
            return False

    def _show_or_defer_version_update_dialog(self, data, *, from_startup=False):
        if from_startup and not self._can_show_version_update_dialog():
            self._pending_version_update_data = data
            self._write_app_log('窗口当前不可见，已延后显示版本更新提醒')
            return
        self._show_version_update_dialog(data)

    def _show_pending_version_update_dialog(self):
        data = self._pending_version_update_data
        if not data or not self._can_show_version_update_dialog():
            return
        self._pending_version_update_data = None
        self._show_version_update_dialog(data)

    def _check_version_update_on_startup(self):
        if self._is_shutting_down:
            return
        if self._version_check_busy:
            self.root.after(600, self._check_version_update_on_startup)
            return
        self._check_version_update(silent=True)

    def _show_version_update_dialog(self, data):
        self._pending_version_update_data = None
        window, content, footer = self._create_info_dialog_shell('版本更新', '760x580', min_width=620, min_height=460)

        tk.Label(
            content,
            text=f'当前版本：{APP_NAME} {APP_VERSION}',
            font=FONTS['title'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w', fill=tk.X, pady=(0, 10))

        latest = normalize_version(data.get('latest_version', APP_VERSION))
        min_supported = normalize_version(data.get('min_supported_version', latest))
        cmp = compare_versions(APP_VERSION, latest)
        requires_forced_update = compare_versions(APP_VERSION, min_supported) < 0

        if cmp < 0:
            banner = tk.Frame(
                content,
                bg=COLORS['primary_light'],
                highlightbackground=COLORS['primary'],
                highlightthickness=1,
                bd=0,
            )
            banner.pack(fill=tk.X, pady=(0, 12))
            tk.Label(
                banner,
                text=f'发现新版本：{latest}',
                font=FONTS['subtitle'],
                fg=COLORS['primary_dark'],
                bg=COLORS['primary_light'],
                anchor='center',
                justify='center',
            ).pack(fill=tk.X, padx=14, pady=(10, 10))

            if requires_forced_update:
                tk.Label(
                    content,
                    text=f'当前版本过低，最低支持版本为 {min_supported}，需要先完成更新。',
                    font=FONTS['body'],
                    fg=COLORS['error'],
                    bg=COLORS['card_bg'],
                    anchor='w',
                    justify='left',
                ).pack(anchor='w', fill=tk.X, pady=(0, 8))

            update_msg = data.get('update_message', '')
            if update_msg:
                msg_label = tk.Label(
                    content,
                    text=update_msg,
                    font=FONTS['body'],
                    fg=COLORS['text_sub'],
                    bg=COLORS['card_bg'],
                    anchor='w',
                    justify='left',
                )
                msg_label.pack(anchor='w', fill=tk.X, pady=(0, 8))
                bind_adaptive_wrap(msg_label, content, padding=8, min_width=320)

            for entry in data.get('changelog', []):
                ver = normalize_version(entry.get('version', ''))
                date = entry.get('date', '')
                tk.Label(
                    content,
                    text=f'{ver}（{date}）',
                    font=FONTS['body_bold'],
                    fg=COLORS['text_main'],
                    bg=COLORS['card_bg'],
                    anchor='w',
                ).pack(anchor='w', fill=tk.X, pady=(6, 2))
                for change in entry.get('changes', []):
                    tk.Label(
                        content,
                        text=f'  · {change}',
                        font=FONTS['body'],
                        fg=COLORS['text_sub'],
                        bg=COLORS['card_bg'],
                        anchor='w',
                    ).pack(anchor='w', fill=tk.X)

            download_url = data.get('download_url', '')
            def ignore_current_version():
                if not self._remember_ignored_update(latest):
                    messagebox.showerror('保存失败', '无法保存忽略提醒设置。', parent=window)
                    return
                self._set_status(f'已忽略版本 {latest} 的启动提醒', COLORS['success'])
                self._close_dialog(window)

            def open_update_page():
                if download_url:
                    webbrowser.open(download_url)
                self._close_dialog(window)

            ModernButton(
                footer,
                '更新',
                style='primary',
                command=open_update_page,
            ).pack(side=tk.RIGHT)
            if not requires_forced_update:
                ModernButton(
                    footer,
                    '本次更新不再提示',
                    style='secondary',
                    command=ignore_current_version,
                ).pack(side=tk.RIGHT, padx=(0, 10))
        else:
            tk.Label(
                content,
                text='当前已是最新版本',
                font=FONTS['body'],
                fg=COLORS['primary'],
                bg=COLORS['card_bg'],
                anchor='center',
                justify='center',
            ).pack(fill=tk.X)
            ModernButton(footer, '关闭', style='secondary', command=lambda: self._close_dialog(window)).pack(side=tk.RIGHT)

    def _check_version_update(self, button=None, *, silent=False):
        if self._version_check_busy:
            return

        self._version_check_busy = True
        if silent:
            self._write_app_log('启动后后台检查版本更新')
        else:
            self._write_app_log('检查版本更新')
            self._set_status('正在检查版本更新...', COLORS['warning'])

        if not self._remote_content:
            if not silent:
                self._set_status('更新服务尚未初始化', COLORS['error'])
            self._reset_version_check_button(
                button,
                text='检查失败',
                style='danger',
                delay_ms=1200 if self._widget_exists(button) else 0,
            )
            return

        if self._widget_exists(button):
            self._start_version_check_animation(button)

        def on_loaded(data):
            latest = normalize_version(data.get('latest_version', APP_VERSION))
            min_supported = normalize_version(data.get('min_supported_version', latest))
            cmp = compare_versions(APP_VERSION, latest)
            requires_forced_update = compare_versions(APP_VERSION, min_supported) < 0

            if cmp < 0:
                if silent and (not requires_forced_update) and self._is_update_ignored(latest):
                    self._write_app_log(f'发现新版本 {latest}，但当前版本已设置为不再提醒')
                    self._reset_version_check_button(button)
                    return
                if self._widget_exists(button):
                    try:
                        if hasattr(button, 'set_style'):
                            button.set_style('accent')
                        button.configure(
                            text='发现新版本',
                            state=tk.DISABLED,
                            cursor='arrow',
                            disabledforeground=COLORS['text_main'],
                        )
                    except tk.TclError:
                        pass
                self._cancel_version_check_animation()
                self._version_check_busy = False
                self._version_check_button = None
                if not silent:
                    if requires_forced_update:
                        self._set_status(f'当前版本过低，请更新到 {min_supported} 或更高版本', COLORS['warning'])
                    else:
                        self._set_status(f'发现新版本 {latest}', COLORS['warning'])
                self._show_or_defer_version_update_dialog(data, from_startup=silent)
                self._reset_version_check_button(button, delay_ms=1200 if self._widget_exists(button) else 0)
                return

            if not silent:
                self._set_status('当前已是最新版本', COLORS['success'])
                self._reset_version_check_button(button, text='已是最新版本', style='secondary', delay_ms=1200 if self._widget_exists(button) else 0)
                return
            self._reset_version_check_button(button)

        def on_error(exc):
            self._write_app_log(f'检查版本更新失败: {exc}', level='WARN')
            if not silent:
                self._set_status('检查更新失败，请检查网络连接', COLORS['error'])
            self._reset_version_check_button(
                button,
                text='检查失败',
                style='danger',
                delay_ms=1200 if self._widget_exists(button) else 0,
            )

        self._remote_content.fetch('version', on_success=on_loaded, on_error=on_error, force=True)

    def _get_root_hwnd(self):
        if sys.platform != 'win32':
            return None
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            return hwnd or self.root.winfo_id()
        except Exception:
            return None

    def _enable_custom_window_chrome(self):
        if self._custom_window_chrome_enabled or sys.platform != 'win32':
            return

        try:
            self.root.update_idletasks()
            hwnd = self._get_root_hwnd()
            if not hwnd:
                return
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            style = (style & ~WS_CAPTION) | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style)
            ctypes.windll.user32.SetWindowPos(
                hwnd,
                None,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
            )
            self._custom_window_chrome_enabled = True
        except Exception as exc:
            self._write_app_log(f'自定义标题栏启用失败: {exc}', level='WARN')

    def _build_window_chrome(self):
        if sys.platform != 'win32':
            return

        self._enable_custom_window_chrome()

        self.window_chrome = tk.Frame(self.root, bg=COLORS['nav_bg'], bd=0, highlightthickness=0)
        self.window_chrome.pack(fill=tk.X, side=tk.TOP)

        chrome_inner = tk.Frame(self.window_chrome, bg=COLORS['nav_bg'], height=44, bd=0, highlightthickness=0)
        chrome_inner.pack(fill=tk.X, padx=12, pady=0)
        chrome_inner.pack_propagate(False)
        self.window_chrome_inner = chrome_inner

        self.window_controls = tk.Frame(chrome_inner, bg=COLORS['nav_bg'], bd=0, highlightthickness=0)
        self.window_controls.pack(side=tk.RIGHT)

        drag_region = tk.Frame(chrome_inner, bg=COLORS['nav_bg'], bd=0, highlightthickness=0, cursor='arrow')
        drag_region.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.window_drag_region = drag_region

        try:
            self.brand_logo = load_image('logo.png', max_size=(18, 18))
            icon_label = tk.Label(drag_region, image=self.brand_logo, bg=COLORS['nav_bg'], bd=0)
            icon_label.pack(side=tk.LEFT, padx=(2, 8))
            self.window_icon_label = icon_label
        except Exception:
            self.window_icon_label = None

        self.window_title_label = tk.Label(
            drag_region,
            text=APP_NAME,
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['nav_bg'],
            anchor='w',
        )
        self.window_title_label.pack(side=tk.LEFT)

        control_specs = (
            ('minimize', self._minimize_window),
            ('maximize', self._toggle_window_maximize),
            ('close', self._on_close),
        )
        self.window_control_buttons = {}
        for index, (role, command) in enumerate(control_specs):
            button = WindowControlButton(
                self.window_controls,
                role=role,
                command=command,
                is_maximized=lambda: self._window_is_maximized,
            )
            pad_right = 0 if index == len(control_specs) - 1 else 4
            button.pack(side=tk.LEFT, padx=(0, pad_right))
            self.window_control_buttons[role] = button

        divider = tk.Frame(self.window_chrome, bg=COLORS['card_border'], height=2, bd=0, highlightthickness=0)
        divider.pack(fill=tk.X, padx=12, pady=0)
        self.window_chrome_divider = divider

        drag_bindings = [chrome_inner, drag_region, self.window_title_label]
        if self.window_icon_label is not None:
            drag_bindings.append(self.window_icon_label)
        for widget in drag_bindings:
            widget.bind('<ButtonPress-1>', self._start_window_drag, add='+')
            widget.bind('<B1-Motion>', self._perform_window_drag, add='+')
            widget.bind('<ButtonRelease-1>', self._stop_window_drag, add='+')
            widget.bind('<Double-Button-1>', self._toggle_window_maximize, add='+')

        self._refresh_window_chrome()

    def _refresh_window_chrome(self):
        if not self.window_chrome:
            return

        self.window_chrome.configure(bg=COLORS['nav_bg'])
        self.window_chrome_inner.configure(bg=COLORS['nav_bg'])
        self.window_drag_region.configure(bg=COLORS['nav_bg'])
        self.window_controls.configure(bg=COLORS['nav_bg'])
        self.window_chrome_divider.configure(bg=COLORS['card_border'])
        self.window_title_label.configure(bg=COLORS['nav_bg'], fg=COLORS['text_main'])
        if self.window_icon_label is not None:
            self.window_icon_label.configure(bg=COLORS['nav_bg'])
        for button in self.window_control_buttons.values():
            button.refresh()

    def _capture_window_geometry(self):
        self.root.update_idletasks()
        return {
            'x': self.root.winfo_x(),
            'y': self.root.winfo_y(),
            'width': self.root.winfo_width(),
            'height': self.root.winfo_height(),
        }

    def _get_work_area(self):
        if sys.platform == 'win32':
            try:
                hwnd = self._get_root_hwnd()
                if hwnd:
                    monitor = ctypes.windll.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
                    if monitor:
                        info = MONITORINFO()
                        info.cbSize = ctypes.sizeof(MONITORINFO)
                        if ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                            rect = info.rcWork
                            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
            except Exception:
                pass
            try:
                rect = wintypes.RECT()
                if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
                    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
            except Exception:
                pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _apply_window_geometry(self, geometry):
        if not geometry:
            geometry = self._get_centered_root_geometry()
        work_x, work_y, work_width, work_height = self._get_work_area()
        safe_width = max(self.min_window_width, int(work_width) - self.window_workarea_margin_x)
        safe_height = max(self.min_window_height, int(work_height) - self.window_workarea_margin_y)
        width = min(max(int(geometry.get('width', self.min_window_width)), self.min_window_width), safe_width)
        height = min(max(int(geometry.get('height', self.min_window_height)), self.min_window_height), safe_height)
        x = max(int(work_x), min(int(geometry.get('x', work_x)), int(work_x) + max(0, int(work_width) - width)))
        y = max(int(work_y), min(int(geometry.get('y', work_y)), int(work_y) + max(0, int(work_height) - height)))
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def _minimize_window(self):
        self._stop_window_drag()
        if self.config_mgr and self.config_mgr.get_setting('minimize_to_tray_on_minimize', False):
            self._minimize_to_tray(reason='manual_minimize')
            return
        self.root.iconify()

    def _supports_tray(self):
        return pystray is not None and PILImage is not None

    def _build_tray_icon_image(self):
        icon_path = get_resource_path('logo.png')
        if not os.path.exists(icon_path):
            return None
        try:
            with PILImage.open(icon_path) as source:
                image = source.convert('RGBA')
                if image.size != (64, 64):
                    resampling = getattr(getattr(PILImage, 'Resampling', PILImage), 'LANCZOS', getattr(PILImage, 'LANCZOS', 1))
                    image = image.resize((64, 64), resampling)
                return image.copy()
        except Exception:
            return None

    def _ensure_tray_icon(self):
        if self._tray_icon is not None:
            return self._tray_icon
        if not self._supports_tray():
            return None
        tray_image = self._build_tray_icon_image()
        if tray_image is None:
            return None

        open_item = pystray.MenuItem('打开纸研社', lambda _icon, _item: self._restore_from_tray())
        quit_item = pystray.MenuItem('退出', lambda _icon, _item: self._quit_from_tray())
        self._tray_icon = pystray.Icon('paperlab', tray_image, APP_NAME, menu=pystray.Menu(open_item, quit_item))
        self._tray_thread = threading.Thread(target=self._tray_icon.run, name='PaperLabTray', daemon=True)
        self._tray_thread.start()
        return self._tray_icon

    def _restore_from_tray(self):
        if self._is_shutting_down:
            return
        try:
            self.root.after(0, self._restore_from_tray_ui)
        except Exception:
            pass

    def _restore_from_tray_ui(self):
        if self._is_shutting_down:
            return
        self._is_tray_minimized = False
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def _quit_from_tray(self):
        if self._is_shutting_down:
            return
        self._is_shutting_down = True
        try:
            self.root.after(0, self._perform_exit)
        except Exception:
            pass

    def _stop_tray_icon(self):
        icon = self._tray_icon
        thread = self._tray_thread
        self._tray_icon = None
        self._tray_thread = None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            try:
                thread.join(timeout=1.2)
            except Exception:
                pass

    def _cancel_pending_after_jobs(self):
        """取消所有已跟踪的 after 定时器，避免 destroy 后回调报错。"""
        for attr in (
            '_shell_repair_job', '_top_nav_layout_job',
            '_webdav_auto_sync_job', '_version_check_anim_job',
        ):
            job_id = getattr(self, attr, None)
            if job_id is not None:
                try:
                    self.root.after_cancel(job_id)
                except Exception:
                    pass
                setattr(self, attr, None)

    def _minimize_to_tray(self, reason=''):
        self._stop_window_drag()
        if not self._supports_tray():
            self._write_app_log('最小化托盘失败：缺少 pystray 或 Pillow，回退到任务栏最小化。', level='WARNING')
            self.root.iconify()
            return
        tray_icon = self._ensure_tray_icon()
        if tray_icon is None:
            self._write_app_log('最小化托盘失败：托盘图标初始化失败，回退到任务栏最小化。', level='WARNING')
            self.root.iconify()
            return
        try:
            self.root.withdraw()
            self._is_tray_minimized = True
            if not self._tray_hint_shown and reason:
                self._write_app_log(f'窗口已最小化到系统托盘，原因：{reason}')
                self._tray_hint_shown = True
        except Exception:
            self.root.iconify()

    def _toggle_window_maximize(self, _event=None):
        if self._window_is_maximized:
            self._window_is_maximized = False
            self._apply_window_geometry(self._window_restore_geometry)
        else:
            self._maximize_window()
            return
        self._refresh_window_chrome()

    def _start_window_drag(self, event):
        if self._window_is_maximized:
            return
        self._window_drag_origin = (
            event.x_root,
            event.y_root,
            self.root.winfo_x(),
            self.root.winfo_y(),
        )
        self._drag_last_pos = None

    def _perform_window_drag(self, event):
        if not self._window_drag_origin or self._window_is_maximized:
            return
        start_x, start_y, window_x, window_y = self._window_drag_origin
        new_x = window_x + event.x_root - start_x
        new_y = window_y + event.y_root - start_y
        if (new_x, new_y) == self._drag_last_pos:
            return
        self._drag_last_pos = (new_x, new_y)
        if sys.platform == 'win32':
            hwnd = self._get_root_hwnd()
            if hwnd:
                SWP_NOSIZE = 0x0001
                SWP_NOZORDER = 0x0004
                SWP_NOACTIVATE = 0x0010
                ctypes.windll.user32.SetWindowPos(
                    hwnd, None, new_x, new_y, 0, 0,
                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
                )
                return
        self.root.geometry(f'+{new_x}+{new_y}')

    def _stop_window_drag(self, _event=None):
        self._window_drag_origin = None
        self._drag_last_pos = None

    def _build_top_nav(self):
        shadow_gap = 5
        shell_inset = 2
        self.top_nav_shadow_gap = shadow_gap
        self.top_nav_shell_inset = shell_inset
        self.user_shell_inset = shell_inset + 1
        self.user_shadow_gap = shadow_gap
        self.user_content_inset = 2
        self.user_row_pad_left = 12
        self.user_row_pad_right = 12
        self.user_row_pad_y = 8
        self.user_avatar_slot_width = 56
        self.user_logo_gap = 10
        self.user_arrow_gap = 8

        self.top_nav_frame = tk.Frame(self.root, bg=COLORS['nav_bg'])
        top_pad = 12 if self.window_chrome else 18
        pack_kwargs = {
            'fill': tk.X,
            'padx': 18,
            'pady': (top_pad, 0),
        }
        if hasattr(self, 'content_view') and self.content_view and self.content_view.winfo_exists():
            pack_kwargs['before'] = self.content_view
        self.top_nav_frame.pack(**pack_kwargs)

        self.top_nav_inner = tk.Frame(self.top_nav_frame, bg=COLORS['nav_bg'])
        self.top_nav_inner.pack(fill=tk.X)

        self.nav_center = tk.Frame(self.top_nav_inner, bg=COLORS['nav_bg'])

        nav_items = list(TOP_NAV_ITEMS)
        # 注：api_config 页面仅通过弹窗入口访问，不在导航栏显示
        self.page_titles = {page_id: label for page_id, label in nav_items}

        self.nav_button_shells = []
        self.nav_button_borders = []
        for page_id, label in nav_items:
            shell = tk.Frame(self.nav_center, bg=COLORS['nav_bg'], bd=0, highlightthickness=0)
            shell.pack(side=tk.LEFT, padx=(0, 7))
            border = tk.Frame(shell, bg='#121317', bd=0, highlightthickness=0)
            border.pack_propagate(False)
            button_width, button_height = self._measure_top_nav_canvas_size(label)
            shell.configure(width=button_width + shadow_gap, height=button_height + shadow_gap)
            shell.pack_propagate(False)
            border.place(
                x=0,
                y=0,
                width=button_width + shadow_gap,
                height=button_height + shadow_gap,
            )
            button = tk.Canvas(
                border,
                bg=COLORS['nav_bg'],
                bd=0,
                highlightthickness=0,
                cursor='hand2',
                width=button_width,
                height=button_height,
            )
            button._nav_page_id = page_id
            button._nav_label = label
            button.place(
                x=0,
                y=0,
                width=button_width,
                height=button_height,
            )
            button.bind('<Button-1>', lambda _event, pid=page_id: self._handle_top_nav_click(pid))
            shell.bind('<Button-1>', lambda _event, pid=page_id: self._handle_top_nav_click(pid))
            border.bind('<Button-1>', lambda _event, pid=page_id: self._handle_top_nav_click(pid))
            self._render_top_nav_canvas(button)
            shell._nav_button = button
            border._nav_button = button
            self.nav_button_shells.append(shell)
            self.nav_button_borders.append(border)
            self.nav_buttons[page_id] = button

        self.right_tools = tk.Frame(self.top_nav_inner, bg=COLORS['nav_bg'])

        tool_specs = [
            ('notice', '公告', '系统公告', 'png/SystemNotice.png', self._show_announcement),
            ('theme', '模式', '模式切换', 'png/ModeSwitch.png', self._show_theme_menu),
            ('settings', '设置', '设置', 'png/Settings.png', self._show_settings),
        ]

        self.tool_button_shells = []
        self.tool_button_borders = []
        self.tool_button_images = {}
        self.theme_tool_button = None
        self.bell_button = None
        self.bell_badge = None
        for role, label, tip, icon_file, command in tool_specs:
            try:
                icon_image = self._load_top_tool_icon(icon_file, max_size=(26, 26))
            except Exception:
                icon_image = None
            self.tool_button_images[role] = icon_image
            shell = tk.Frame(
                self.right_tools,
                bg=COLORS['shadow'],
                bd=0,
                highlightthickness=0,
                width=84,
                height=84,
            )
            shell.pack_propagate(False)
            shell.pack(side=tk.LEFT, padx=(0, 4))

            button = ToolIconButton(
                shell,
                text='',
                tooltip=tip,
                command=command,
                font=FONTS['small'],
                width=4,
                padx=0,
                pady=0,
                highlightthickness=2,
                takefocus=0,
            )
            button.pack(fill=tk.BOTH, expand=True, padx=(0, self.top_nav_shadow_gap), pady=(0, self.top_nav_shadow_gap))
            button._tool_role = role
            button._tool_label = label
            button._tool_tip = tip
            button._tool_icon_file = icon_file
            button._tool_icon_bg = COLORS['toolbar_icon_bg']
            button._tool_icon_fg = COLORS['toolbar_icon_fg']
            button._tool_icon_image = icon_image
            button._tool_has_badge = role == 'notice' and self._bell_badge_visible
            button._tool_shell = shell
            badge = tk.Canvas(
                shell,
                width=10,
                height=10,
                bg=COLORS['error'],
                bd=0,
                highlightthickness=0,
            )
            shell._tool_button = button
            shell._tool_badge = badge
            shell._tool_role = role

            self._refresh_top_tool_button(shell)
            self.tool_button_shells.append(shell)
            self.tool_button_borders.append(None)
            self.tool_buttons.append(button)
            if role == 'notice':
                self.bell_button = shell
            if role == 'theme':
                self.theme_tool_button = shell

        self.user_box = tk.Frame(self.right_tools, bg=COLORS['shadow'])

        self.user_inner = tk.Frame(
            self.user_box,
            bg=COLORS['card_border'],
            bd=0,
            highlightthickness=0,
        )
        self.user_inner.pack(
            fill=tk.BOTH,
            expand=True,
            padx=(self.user_shell_inset, self.user_shadow_gap),
            pady=(self.user_shell_inset, self.user_shadow_gap),
        )
        self.user_content = tk.Frame(
            self.user_inner,
            bg=COLORS['card_bg'],
            bd=0,
            highlightthickness=0,
        )
        self.user_content.pack(
            fill=tk.BOTH,
            expand=True,
            padx=self.user_content_inset,
            pady=self.user_content_inset,
        )
        self.user_canvas = tk.Canvas(
            self.user_content,
            bg=COLORS['card_bg'],
            bd=0,
            highlightthickness=0,
            cursor='hand2',
        )
        self.user_canvas.pack(fill=tk.BOTH, expand=True)
        self.user_row = None

        try:
            self.user_logo = load_image('logo.png', max_size=(40, 40))
        except Exception:
            self.user_logo = None
        self.user_logo_label = None

        raw_username = os.getenv('USERNAME') or 'Local User'
        self._user_display_name = raw_username if len(raw_username) <= 7 else f'{raw_username[:7]}...'
        self.username_label = None
        self.user_arrow = None

        initial_user_box_width, initial_user_box_height, _inner_width, _inner_height, _content_width, _content_height = self._measure_user_profile_box_size()
        self.user_box.configure(
            width=initial_user_box_width,
            height=initial_user_box_height,
        )
        self.user_box.pack_propagate(False)
        self._layout_user_profile_box(
            box_width=initial_user_box_width,
            box_height=initial_user_box_height,
        )

        self.user_canvas.bind('<Button-1>', lambda _event: self._show_about_dialog())
        for widget in (self.user_box, self.user_inner, self.user_content, self.user_canvas):
            widget.bind('<Button-1>', lambda _event: self._show_about_dialog())

        self.user_box.pack(side=tk.LEFT, padx=(2, 0))

        # 初始布局：确保 nav_center 和 right_tools 立即可见
        self.top_nav_inner.grid_columnconfigure(0, weight=1)
        self.top_nav_inner.grid_columnconfigure(1, weight=0)
        self.top_nav_inner.grid_rowconfigure(0, weight=0)
        self.nav_center.grid(row=0, column=0, sticky='w')
        self.right_tools.grid(row=0, column=1, sticky='e')

        self.top_nav_inner.update_idletasks()
        self._sync_top_nav_metrics()
        self._relayout_top_nav(force=True)
        self.top_nav_inner.bind('<Configure>', self._schedule_top_nav_relayout, add='+')
        self.top_nav_inner.after_idle(lambda: self._relayout_top_nav(refresh_metrics=True, force=True))

    def _rebuild_window_chrome_after_show(self):
        if sys.platform != 'win32':
            return
        try:
            if self.window_chrome and self.window_chrome.winfo_exists():
                self.window_chrome.destroy()
        except tk.TclError:
            pass

        self.window_chrome = None
        self.window_chrome_inner = None
        self.window_drag_region = None
        self.window_controls = None
        self.window_chrome_divider = None
        self.window_icon_label = None
        self.window_title_label = None
        self.window_control_buttons = {}

        self._build_window_chrome()
        if self.window_chrome and hasattr(self, 'top_nav_frame') and self.top_nav_frame and self.top_nav_frame.winfo_exists():
            self.window_chrome.pack_configure(before=self.top_nav_frame)
        self.root.update_idletasks()

    def _rebuild_top_nav_after_show(self):
        if not getattr(self, 'top_nav_frame', None):
            return
        try:
            if self.top_nav_frame.winfo_exists():
                self.top_nav_frame.destroy()
        except tk.TclError:
            return

        self.nav_buttons = {}
        self.nav_button_shells = []
        self.nav_button_borders = []
        self.tool_buttons = []
        self.tool_button_shells = []
        self.tool_button_borders = []
        self.tool_button_images = {}
        self.top_nav_frame = None
        self.top_nav_inner = None
        self.nav_center = None
        self.right_tools = None
        self.user_box = None
        self.user_inner = None
        self.user_content = None
        self.user_canvas = None
        self.user_row = None
        self.user_logo_label = None
        self.theme_tool_button = None
        self.bell_button = None
        self.bell_badge = None
        self.username_label = None
        self.user_arrow = None

        self._build_top_nav()
        if hasattr(self, 'content_view') and self.content_view.winfo_exists():
            self.top_nav_frame.pack_configure(before=self.content_view)
        self.root.update_idletasks()
        self._relayout_top_nav(refresh_metrics=True, force=True)
        for _page_id, button in self.nav_buttons.items():
            # 顶部一级导航使用自绘样式，当前页保持黄色激活态，其余按钮使用浅色底。
            self._render_top_nav_canvas(button)

        self._refresh_top_nav_buttons()

    def _handle_root_map(self, _event=None):
        if not self._startup_complete or self._shell_repair_job is not None:
            return
        self._shell_repair_job = self.root.after(80, self._repair_shell_after_map)
        if self._pending_version_update_data:
            self.root.after(220, self._show_pending_version_update_dialog)

    def _repair_shell_after_map(self):
        self._shell_repair_job = None
        if sys.platform != 'win32' or not self.root.winfo_exists() or not self.root.winfo_viewable():
            return

        rebuild_chrome = False
        if not self.window_chrome or not self.window_chrome.winfo_exists():
            rebuild_chrome = True
        else:
            try:
                rebuild_chrome = self.window_chrome.winfo_rootx() == 0 and self.window_chrome.winfo_rooty() == 0
            except tk.TclError:
                rebuild_chrome = True

        if rebuild_chrome:
            self._rebuild_window_chrome_after_show()

        rebuild_nav = False
        if not getattr(self, 'top_nav_frame', None) or not self.top_nav_frame.winfo_exists():
            rebuild_nav = True
        else:
            try:
                rebuild_nav = self.top_nav_frame.winfo_rootx() == 0 and self.top_nav_frame.winfo_rooty() == 0
            except tk.TclError:
                rebuild_nav = True

        if rebuild_chrome or rebuild_nav:
            self._rebuild_top_nav_after_show()

    def _apply_top_nav_spacing(self):
        _work_x, _work_y, work_width, _work_height = self._get_work_area()
        width = max(self.root.winfo_width(), self.min_window_width)
        max_width = max(int(work_width), self.min_window_width + 1)
        progress = min(1.0, max(0.0, (width - self.min_window_width) / (max_width - self.min_window_width)))

        outer_pad = int(round(18 + 18 * progress))
        nav_gap = int(round(6 + 7 * progress))
        tool_gap = int(round(3 + 5 * progress))
        user_gap = int(round(4 + 6 * progress))

        self.top_nav_frame.pack_configure(padx=outer_pad)

        for index, shell in enumerate(self.nav_button_shells):
            right_gap = nav_gap if index < len(self.nav_button_shells) - 1 else 0
            shell.pack_configure(padx=(0, right_gap))

        for index, shell in enumerate(self.tool_button_shells):
            right_gap = tool_gap if index < len(self.tool_button_shells) - 1 else 0
            shell.pack_configure(padx=(0, right_gap))

        self.user_box.pack_configure(padx=(user_gap, 0))

    def _refresh_top_nav_buttons(self):
        for button in self.nav_buttons.values():
            self._render_top_nav_canvas(button)

    def _schedule_top_nav_relayout(self, _event=None, delay_ms=24):
        if not getattr(self, 'top_nav_inner', None):
            return
        if self._top_nav_layout_job is not None:
            return
        try:
            self._top_nav_layout_job = self.root.after(delay_ms, self._run_scheduled_top_nav_relayout)
        except tk.TclError:
            self._top_nav_layout_job = None

    def _run_scheduled_top_nav_relayout(self):
        self._top_nav_layout_job = None
        self._relayout_top_nav()

    def _measure_top_nav_canvas_size(self, label):
        try:
            nav_font = tkfont.Font(font=FONTS['nav'])
        except Exception:
            nav_font = tkfont.nametofont('TkDefaultFont')
        text_width = nav_font.measure(label or '')
        text_height = nav_font.metrics('linespace')
        canvas_width = max(text_width + 36, 92)
        canvas_height = max(text_height + 16, 42)
        if canvas_width % 2 != 0:
            canvas_width += 1
        if canvas_height % 2 != 0:
            canvas_height += 1
        return canvas_width, canvas_height

    def _measure_user_profile_box_size(self):
        def _ensure_even(value):
            value = int(max(value, 0))
            return value if value % 2 == 0 else value + 1

        shell_inset = getattr(self, 'user_shell_inset', getattr(self, 'top_nav_shell_inset', 0))
        shadow_gap = getattr(self, 'user_shadow_gap', getattr(self, 'top_nav_shadow_gap', 0))
        content_inset = getattr(self, 'user_content_inset', 2)
        row_pad_left = getattr(self, 'user_row_pad_left', 12)
        row_pad_right = getattr(self, 'user_row_pad_right', 12)
        row_pad_y = getattr(self, 'user_row_pad_y', 8)
        avatar_slot_width = getattr(self, 'user_avatar_slot_width', 56)
        logo_gap = getattr(self, 'user_logo_gap', 10)
        arrow_gap = getattr(self, 'user_arrow_gap', 8)
        username_text = getattr(self, '_user_display_name', '')
        arrow_text = '\u25BE'
        try:
            username_font = tkfont.Font(font=FONTS['small'])
        except Exception:
            username_font = tkfont.nametofont('TkDefaultFont')
        try:
            arrow_font = tkfont.Font(font=FONTS['tiny'])
        except Exception:
            arrow_font = tkfont.nametofont('TkDefaultFont')

        username_width = username_font.measure(username_text) + 12
        username_height = username_font.metrics('linespace') + 6
        arrow_width = arrow_font.measure(arrow_text) + 8
        arrow_height = arrow_font.metrics('linespace') + 6
        logo_height = 44 if getattr(self, 'user_logo', None) is not None else 0

        row_width = username_width
        row_height = username_height
        if getattr(self, 'user_logo', None) is not None:
            row_width += avatar_slot_width + logo_gap
            row_height = max(row_height, logo_height)
        if arrow_width > 0:
            row_width += arrow_gap + arrow_width
            row_height = max(row_height, arrow_height)

        content_width = _ensure_even(row_width + row_pad_left + row_pad_right)
        content_height = _ensure_even(row_height + row_pad_y * 2)
        inner_width = _ensure_even(content_width + content_inset * 2)
        inner_height = _ensure_even(content_height + content_inset * 2)
        box_width = inner_width + shell_inset + shadow_gap
        box_height = inner_height + shell_inset + shadow_gap
        return box_width, box_height, inner_width, inner_height, content_width, content_height

    def _render_user_profile_canvas(self, canvas):
        if canvas is None:
            return

        try:
            req_width = int(float(canvas.cget('width')))
            req_height = int(float(canvas.cget('height')))
        except Exception:
            req_width = 120
            req_height = 48

        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width <= 1:
            width = req_width
        if height <= 1:
            height = req_height
        width = max(int(width), 80)
        height = max(int(height), 40)

        username_text = getattr(self, '_user_display_name', '')
        arrow_text = '\u25BE'
        render_signature = (
            width,
            height,
            username_text,
            bool(getattr(self, 'user_logo', None)),
            COLORS['card_bg'],
            COLORS['text_main'],
            COLORS['text_sub'],
        )
        if getattr(canvas, '_render_signature', None) == render_signature:
            return
        canvas._render_signature = render_signature

        row_pad_left = getattr(self, 'user_row_pad_left', 12)
        avatar_slot_width = getattr(self, 'user_avatar_slot_width', 56)
        logo_gap = getattr(self, 'user_logo_gap', 10)
        arrow_gap = getattr(self, 'user_arrow_gap', 8)
        center_y = int(round(height / 2))

        try:
            username_font = tkfont.Font(font=FONTS['small'])
        except Exception:
            username_font = tkfont.nametofont('TkDefaultFont')

        username_width = username_font.measure(username_text) + 12
        cursor_x = row_pad_left

        canvas.delete('all')
        canvas.configure(bg=COLORS['card_bg'], highlightthickness=0, bd=0)

        if getattr(self, 'user_logo', None) is not None:
            canvas.create_image(
                cursor_x + avatar_slot_width / 2,
                center_y,
                image=self.user_logo,
            )
        else:
            avatar_radius = 18
            avatar_center_x = cursor_x + avatar_slot_width / 2
            avatar_fill = COLORS['primary_light']
            avatar_outline = COLORS['card_border']
            avatar_text = (username_text or 'U').strip()[:1].upper()
            canvas.create_oval(
                avatar_center_x - avatar_radius,
                center_y - avatar_radius,
                avatar_center_x + avatar_radius,
                center_y + avatar_radius,
                fill=avatar_fill,
                outline=avatar_outline,
                width=2,
            )
            canvas.create_text(
                avatar_center_x,
                center_y,
                text=avatar_text,
                fill=COLORS['text_main'],
                font=FONTS['body_bold'],
            )
        cursor_x += avatar_slot_width + logo_gap

        canvas.create_text(
            cursor_x + 4,
            center_y,
            text=username_text,
            fill=COLORS['text_main'],
            font=FONTS['small'],
            anchor='w',
        )
        cursor_x += username_width + arrow_gap

        canvas.create_text(
            cursor_x + 1,
            center_y,
            text=arrow_text,
            fill=COLORS['text_sub'],
            font=FONTS['tiny'],
            anchor='w',
        )

    def _layout_user_profile_box(self, *, box_width=None, box_height=None):
        if not getattr(self, 'user_box', None) or not getattr(self, 'user_inner', None) or not getattr(self, 'user_content', None):
            return

        shell_inset = getattr(self, 'user_shell_inset', getattr(self, 'top_nav_shell_inset', 0))
        shadow_gap = getattr(self, 'user_shadow_gap', getattr(self, 'top_nav_shadow_gap', 0))
        content_inset = getattr(self, 'user_content_inset', 2)

        min_box_width, min_box_height, _min_inner_width, _min_inner_height, _min_content_width, _min_content_height = self._measure_user_profile_box_size()

        width = int(box_width if box_width is not None else max(self.user_box.winfo_width(), self.user_box.winfo_reqwidth(), min_box_width))
        height = int(box_height if box_height is not None else max(self.user_box.winfo_height(), self.user_box.winfo_reqheight(), min_box_height))
        width = max(width, min_box_width)
        height = max(height, min_box_height)

        inner_width = max(width - shell_inset - shadow_gap, 0)
        inner_height = max(height - shell_inset - shadow_gap, 0)
        content_width = max(inner_width - content_inset * 2, 0)
        content_height = max(inner_height - content_inset * 2, 0)
        self.user_inner.configure(width=inner_width, height=inner_height)
        self.user_content.configure(width=content_width, height=content_height)
        if getattr(self, 'user_canvas', None):
            self.user_canvas.configure(width=content_width, height=content_height)
            self._render_user_profile_canvas(self.user_canvas)

    def _render_top_nav_canvas(self, canvas):
        if canvas is None:
            return
        nav_outline = '#121317'
        nav_normal_fill = '#F5F4EF'
        nav_active_fill = '#FFD84A'
        try:
            req_width = int(float(canvas.cget('width')))
            req_height = int(float(canvas.cget('height')))
        except Exception:
            req_width = 96
            req_height = 42
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width <= 1:
            width = req_width
        if height <= 1:
            height = req_height
        width = max(width, 48)
        height = max(height, 36)
        center_x = int(round(width / 2))
        center_y = int(round(height / 2))
        outline_width = 3
        inset = max(2, outline_width // 2 + 1)
        page_id = getattr(canvas, '_nav_page_id', '')
        is_active = page_id == self.current_page_id
        label = getattr(canvas, '_nav_label', '')
        render_signature = (
            width,
            height,
            is_active,
            label,
            nav_outline,
            nav_normal_fill,
            nav_active_fill,
            FONTS['nav'],
            COLORS['nav_bg'],
        )
        if getattr(canvas, '_render_signature', None) == render_signature:
            return
        canvas._render_signature = render_signature
        canvas.delete('all')
        canvas.configure(bg=COLORS['nav_bg'], highlightthickness=0, bd=0)
        canvas.create_rectangle(
            inset,
            inset,
            max(width - inset, inset + 1),
            max(height - inset, inset + 1),
            fill=nav_active_fill if is_active else nav_normal_fill,
            outline=nav_outline,
            width=outline_width,
        )
        canvas.create_text(
            center_x,
            center_y,
            text=label,
            fill=nav_outline,
            font=FONTS['nav'],
            anchor='center',
            justify='center',
        )

    def _load_top_tool_icon(self, filename, *, max_size=(24, 24)):
        cache_key = (filename, tuple(max_size or ()), COLORS['toolbar_icon_fg'])
        cached = self._top_tool_icon_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            from PIL import Image as _PILImage
            from PIL import ImageTk as _ImageTk

            path = get_resource_path(filename)
            with _PILImage.open(path) as source:
                image = source.convert('RGBA')
                if max_size:
                    resampling = getattr(getattr(_PILImage, 'Resampling', _PILImage), 'LANCZOS', getattr(_PILImage, 'LANCZOS', 1))
                    image.thumbnail(max_size, resampling)
                alpha = image.getchannel('A')
                tinted = _PILImage.new('RGBA', image.size, COLORS['toolbar_icon_fg'])
                tinted.putalpha(alpha)
            icon_image = _ImageTk.PhotoImage(tinted)
        except Exception:
            icon_image = load_image(filename, max_size=max_size)
        self._top_tool_icon_cache[cache_key] = icon_image
        return icon_image

    def _render_top_tool_canvas(self, canvas):
        if canvas is None:
            return
        icon_file = getattr(canvas, '_tool_icon_file', '')
        icon_bg = getattr(canvas, '_tool_icon_bg', None)
        icon_fg = getattr(canvas, '_tool_icon_fg', None)
        if icon_file and (icon_bg != COLORS['toolbar_icon_bg'] or icon_fg != COLORS['toolbar_icon_fg']):
            try:
                icon_image = self._load_top_tool_icon(icon_file, max_size=(26, 26))
            except Exception:
                icon_image = None
            canvas._tool_icon_image = icon_image
            canvas._tool_icon_bg = COLORS['toolbar_icon_bg']
            canvas._tool_icon_fg = COLORS['toolbar_icon_fg']
            role = getattr(canvas, '_tool_role', '')
            if role:
                self.tool_button_images[role] = icon_image
        try:
            width = max(int(float(canvas.cget('width'))), canvas.winfo_width(), 52)
            height = max(int(float(canvas.cget('height'))), canvas.winfo_height(), 52)
        except Exception:
            width = max(canvas.winfo_width(), 84)
            height = max(canvas.winfo_height(), 84)

        shadow_gap = getattr(self, 'top_nav_shadow_gap', 5)
        right = max(12, width - shadow_gap)
        bottom = max(12, height - shadow_gap)
        center_x = right / 2
        center_y = bottom / 2
        icon_image = getattr(canvas, '_tool_icon_image', None)
        label = getattr(canvas, '_tool_label', '')
        has_badge = bool(getattr(canvas, '_tool_has_badge', False))

        canvas.delete('all')
        canvas.configure(bg=COLORS['shadow'], highlightthickness=0, bd=0)
        canvas.create_rectangle(
            0,
            0,
            right,
            bottom,
            fill=COLORS['toolbar_icon_bg'],
            outline=COLORS['card_border'],
            width=2,
        )
        if icon_image is not None:
            canvas.create_image(center_x, center_y, image=icon_image)
        else:
            canvas.create_text(center_x, center_y, text=label, fill=COLORS['toolbar_icon_fg'], font=FONTS['small'])
        if has_badge:
            canvas.create_oval(
                right - 16,
                8,
                right - 6,
                18,
                fill=COLORS['error'],
                outline=COLORS['error'],
            )

    @staticmethod
    def _resolve_tool_button_canvas(widget):
        if isinstance(widget, tk.Canvas):
            return widget
        return getattr(widget, '_tool_canvas', None)

    @staticmethod
    def _resolve_tool_button(widget):
        if isinstance(widget, tk.Button):
            return widget
        return getattr(widget, '_tool_button', None)

    def _refresh_top_tool_button(self, widget):
        button = self._resolve_tool_button(widget)
        if button is None:
            return

        shell = getattr(button, '_tool_shell', None) or getattr(widget, '_tool_shell', None) or widget
        if shell is None:
            return

        icon_file = getattr(button, '_tool_icon_file', '')
        icon_bg = getattr(button, '_tool_icon_bg', None)
        icon_fg = getattr(button, '_tool_icon_fg', None)
        if icon_file and (icon_bg != COLORS['toolbar_icon_bg'] or icon_fg != COLORS['toolbar_icon_fg']):
            try:
                icon_image = self._load_top_tool_icon(icon_file, max_size=(26, 26))
            except Exception:
                icon_image = None
            button._tool_icon_image = icon_image
            button._tool_icon_bg = COLORS['toolbar_icon_bg']
            button._tool_icon_fg = COLORS['toolbar_icon_fg']
            role = getattr(button, '_tool_role', '')
            if role:
                self.tool_button_images[role] = icon_image

        if hasattr(button, 'set_style'):
            button.set_style('tool')
        button.configure(
            bg=COLORS['toolbar_icon_bg'],
            fg=COLORS['toolbar_icon_fg'],
            activebackground=COLORS['accent_light'],
            activeforeground=COLORS['text_main'],
            highlightbackground=COLORS['card_border'],
            compound=tk.CENTER,
        )

        icon_image = getattr(button, '_tool_icon_image', None)
        if icon_image is not None:
            button.configure(image=icon_image, text='')
            button.image = icon_image
        else:
            button.configure(image='', text=getattr(button, '_tool_label', ''))

        shell.configure(bg=COLORS['shadow'])
        badge = getattr(shell, '_tool_badge', None)
        if badge is None:
            return
        badge.configure(bg=COLORS['error'])
        if getattr(button, '_tool_has_badge', False):
            badge.place(relx=1.0, x=-(self.top_nav_shadow_gap + 8), y=8, width=10, height=10, anchor='ne')
        else:
            badge.place_forget()

    def _sync_top_nav_metrics_legacy_unused(self):
        return
        # 一级导航只使用“历史记录/智能纠错”的尺寸基准，避免其他按钮再被自身文本宽度带偏。

    def _sync_top_nav_metrics(self):
        self.top_nav_inner.update_idletasks()

        def _ensure_even(value):
            value = int(max(value, 0))
            return value if value % 2 == 0 else value + 1

        nav_shadow_gap = getattr(self, 'top_nav_shadow_gap', 3)
        nav_min_border_width = 92
        nav_button_inset_x = 0
        nav_button_inset_y = 0
        nav_border_height = 0
        nav_button_metrics = []
        for shell, border in zip(self.nav_button_shells, self.nav_button_borders):
            button = getattr(shell, '_nav_button', None) or getattr(border, '_nav_button', None)
            if button is None:
                continue
            inner_width, inner_height = self._measure_top_nav_canvas_size(getattr(button, '_nav_label', ''))
            border_width = _ensure_even(max(inner_width, nav_min_border_width) + nav_shadow_gap)
            border_height = _ensure_even(inner_height + nav_shadow_gap)
            nav_button_metrics.append((shell, border, button, inner_width, inner_height, border_width, border_height))
            nav_border_height = max(nav_border_height, border_height)

        self.user_box.update_idletasks()
        user_box_width, user_box_height, _user_inner_width, _user_inner_height, _user_content_width, _user_content_height = self._measure_user_profile_box_size()
        nav_height = max(
            nav_border_height,
            user_box_height,
            52,
        )
        nav_height = _ensure_even(nav_height)

        final_nav_border_height = nav_height
        for shell, border, button, inner_width, inner_height, border_width, _border_height in nav_button_metrics:
            shell.configure(width=border_width, height=nav_height)
            shell.pack_propagate(False)
            border.pack_propagate(False)
            border.place_configure(
                x=0,
                y=0,
                width=border_width,
                height=final_nav_border_height,
            )
            button.place_configure(
                x=nav_button_inset_x,
                y=nav_button_inset_y,
                width=max(border_width - nav_shadow_gap, inner_width),
                height=max(final_nav_border_height - nav_shadow_gap, inner_height),
            )
            self._render_top_nav_canvas(button)

        for shell in self.tool_button_shells:
            shell.configure(width=nav_height, height=nav_height)
            shell.pack_propagate(False)
            self._refresh_top_tool_button(shell)

        self.user_box.configure(
            width=user_box_width,
            height=nav_height,
        )
        self.user_box.pack_propagate(False)
        self._layout_user_profile_box(box_width=user_box_width, box_height=nav_height)

    def _relayout_top_nav(self, _event=None, *, refresh_metrics=False, force=False):
        if not getattr(self, 'top_nav_inner', None) or not self.top_nav_inner.winfo_exists():
            return
        if refresh_metrics:
            self._sync_top_nav_metrics()
        try:
            available_width = max(self.top_nav_inner.winfo_width(), self.top_nav_inner.winfo_reqwidth(), 1)
        except tk.TclError:
            return
        if not force and not refresh_metrics and available_width == self._top_nav_last_width:
            return
        self._top_nav_last_width = available_width
        self._apply_top_nav_spacing()
        if refresh_metrics or force:
            try:
                self.top_nav_inner.update_idletasks()
            except tk.TclError:
                return
        nav_width = self.nav_center.winfo_reqwidth()
        right_width = self.right_tools.winfo_reqwidth()
        stacked = available_width < nav_width + right_width + 24

        if not force and stacked == self._top_nav_last_stack_state:
            return
        self._top_nav_last_stack_state = stacked

        self.nav_center.grid_forget()
        self.right_tools.grid_forget()

        if stacked:
            self.top_nav_inner.grid_columnconfigure(0, weight=1, minsize=0)
            self.top_nav_inner.grid_columnconfigure(1, weight=0, minsize=0)
            self.top_nav_inner.grid_rowconfigure(0, weight=0, minsize=0)
            self.top_nav_inner.grid_rowconfigure(1, weight=0, minsize=0)
            self.nav_center.grid(row=0, column=0, sticky='w')
            self.right_tools.grid(row=1, column=0, sticky='e', pady=(8, 0))
        else:
            self.top_nav_inner.grid_columnconfigure(0, weight=1, minsize=0)
            self.top_nav_inner.grid_columnconfigure(1, weight=0, minsize=right_width)
            self.top_nav_inner.grid_rowconfigure(0, weight=0, minsize=0)
            self.top_nav_inner.grid_rowconfigure(1, weight=0, minsize=0)
            self.nav_center.grid(row=0, column=0, sticky='w')
            self.right_tools.grid(row=0, column=1, sticky='e')

    def _build_status_bar(self):
        return

    def _build_app_bridge(self):
        return AppBridge(
            show_announcement=self._show_announcement,
            show_tutorial=self._show_tutorial,
            show_settings=self._show_settings,
            show_about=self._show_about_dialog,
            show_api_config=self._show_api_config_dialog,
            show_prompt_manager=self._show_prompt_manager,
            show_skills_center=self._show_skills_center,
            show_discover_skills=self._show_discover_skills,
            show_repo_manage=self._show_repo_manage,
            show_model_routing=self._show_model_routing,
            switch_api_provider_direct=self._switch_api_provider_in_dialog,
            add_new_provider=self._add_new_provider_in_dialog,
            pull_paper_write_context=self._pull_paper_write_context,
            pull_paper_write_selection_snapshot=self._pull_paper_write_selection_snapshot,
            apply_result_to_paper_write=self._apply_result_to_paper_write,
            send_paper_write_content=self._send_paper_write_content,
            navigate_to_page=self._navigate_to_page,
            write_app_log=self._write_app_log,
            restore_page_workspace=self._restore_page_workspace,
        )

    def _pull_paper_write_context(self):
        page = self._ensure_page('paper_write')
        if not page or not hasattr(page, 'export_polish_context'):
            return {}
        try:
            return page.export_polish_context() or {}
        except Exception as exc:
            self._write_app_log(f'拉取论文写作上下文失败: {exc}', level='WARN')
            return {}

    def _pull_paper_write_selection_snapshot(self):
        page = self._ensure_page('paper_write')
        if not page or not hasattr(page, 'export_selection_snapshot'):
            return None
        try:
            return page.export_selection_snapshot()
        except Exception as exc:
            self._write_app_log(f'拉取论文写作选区失败: {exc}', level='WARN')
            return None

    def _apply_result_to_paper_write(
        self,
        result,
        target_mode='smart',
        write_mode='replace',
        section_hint='',
        task_type='',
    ):
        page = self._ensure_page('paper_write')
        if not page or not hasattr(page, 'apply_external_result'):
            return {'ok': False, 'message': '论文写作页不可用'}
        try:
            outcome = page.apply_external_result(
                result,
                target_mode=target_mode,
                write_mode=write_mode,
                section_hint=section_hint,
                task_type=task_type,
            )
            if outcome.get('ok'):
                self._write_app_log(
                    f'学术润色结果已写回论文写作页: target={outcome.get("target")} mode={write_mode}'
                )
            return outcome
        except Exception as exc:
            self._write_app_log(f'写回论文写作页失败: {exc}', level='ERROR')
            return {'ok': False, 'message': str(exc)}

    def _send_paper_write_content(self, page_id, payload):
        page = self._ensure_page(page_id)
        if not page or not hasattr(page, 'receive_paper_write_content'):
            return {'ok': False, 'message': f'目标页面不支持接收内容：{page_id}'}
        try:
            outcome = page.receive_paper_write_content(payload or {})
            if outcome.get('ok'):
                self._write_app_log(
                    f'paper_write content sent: target={page_id} section={outcome.get("section", "")}'
                )
            return outcome
        except Exception as exc:
            self._write_app_log(f'paper_write content send failed: {page_id} {exc}', level='ERROR')
            return {'ok': False, 'message': str(exc)}

    def _navigate_to_page(self, page_id):
        page = self._ensure_page(page_id)
        if not page:
            return {'ok': False, 'message': f'未找到页面: {page_id}'}
        self._show_page(page_id)
        return {'ok': True, 'page_id': page_id}

    def _handle_top_nav_click(self, page_id):
        self._show_page(page_id)
        return 'break'

    def _restore_page_workspace(self, page_id, state, save_to_disk=True):
        page = self._ensure_page(page_id)
        if not page:
            return {'ok': False, 'message': f'未找到页面: {page_id}'}
        if not hasattr(page, 'apply_workspace_state_snapshot'):
            return {'ok': False, 'message': f'页面不支持工作区恢复: {page_id}'}
        try:
            ok = bool(page.apply_workspace_state_snapshot(state, save_to_disk=save_to_disk))
        except Exception as exc:
            self._write_app_log(f'workspace_state restore failed: {page_id} {exc}', level='ERROR')
            return {'ok': False, 'message': str(exc)}
        if not ok:
            return {'ok': False, 'message': f'页面工作区恢复失败: {page_id}'}
        self._write_app_log(f'workspace_state restored: {page_id}')
        return {'ok': True, 'message': f'已恢复 {page_id} 工作区', 'page_id': page_id}

    def _set_status(self, text, color=None):
        if hasattr(self, 'status_label'):
            self.status_label.configure(text=f'● {text}', fg=color or COLORS['text_sub'])

        signature = (str(text or ''), str(color or ''))
        if signature != self._last_status_log_signature:
            level = 'INFO'
            if color == COLORS.get('warning'):
                level = 'WARN'
            elif color == COLORS.get('error'):
                level = 'ERROR'
            self._write_app_log(f'状态更新: {text}', level=level)
            self._last_status_log_signature = signature

    def _flush_page_workspace_states(self):
        for page in self.pages.values():
            if hasattr(page, 'save_workspace_state_now'):
                try:
                    page.save_workspace_state_now(save_to_disk=False)
                except Exception as exc:
                    self._write_app_log(f'workspace_state save failed: {exc}', level='WARN')

    def _show_page(self, page_id, *, invoke_on_show=True):
        # 若页面已创建则立即切换，否则先切换占位再异步完成创建
        if page_id == self.current_page_id and page_id in self.pages:
            return
        if page_id in self._page_specs and not getattr(sys, 'frozen', False):
            self._load_page_class(page_id)
        if page_id in self.pages:
            self._switch_to_page(page_id, invoke_on_show=invoke_on_show)
        else:
            self.root.after(
                0,
                lambda pid=page_id, should_invoke=invoke_on_show: self._ensure_and_show_page(
                    pid,
                    invoke_on_show=should_invoke,
                ),
            )

    def _ensure_and_show_page(self, page_id, *, invoke_on_show=True):
        page = self._ensure_page(page_id)
        if not page:
            return
        self._switch_to_page(page_id, invoke_on_show=invoke_on_show)

    def _switch_to_page(self, page_id, *, invoke_on_show=True):
        page = self.pages.get(page_id)
        if not page:
            return

        for _pid, built_page in self.pages.items():
            built_page.frame.pack_forget()

        self.current_page_id = page_id
        self._refresh_top_nav_buttons()
        page.frame.pack(fill=tk.BOTH, expand=True)
        if invoke_on_show and hasattr(page, 'on_show'):
            page.on_show()
        if hasattr(self, 'content_view'):
            self.content_view.scroll_to_top()
        self._write_app_log(f'页面切换: {page_id}')

    def _invoke_page_on_show(self, page_id):
        if self.current_page_id != page_id:
            return
        page = self.pages.get(page_id)
        if page and hasattr(page, 'on_show'):
            page.on_show()

    def _create_dialog_shell(self, title, geometry='1600x1200'):
        window = tk.Toplevel(self.root)
        window.title(f'纸研社 - {title}')
        window.configure(bg=COLORS['bg_main'])
        window.transient(self.root)
        window.resizable(False, False)
        self._center_window(window, geometry)

        card = tk.Frame(window, bg=COLORS['shadow'])
        card.pack(fill=tk.BOTH, expand=True, padx=18, pady=18)

        body = tk.Frame(
            card,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=3,
            bd=0,
        )
        body.pack(fill=tk.BOTH, expand=True, padx=(0, 8), pady=(0, 8))

        self.dialogs.append(window)
        window.protocol('WM_DELETE_WINDOW', lambda win=window: self._close_dialog(win))
        return window, body

    def _create_info_dialog_shell(self, title, geometry, *, min_width, min_height):
        window, body = self._create_dialog_shell(title, geometry)
        window.resizable(True, True)
        apply_adaptive_window_geometry(window, geometry, min_width=min_width, min_height=min_height)

        footer = tk.Frame(body, bg=COLORS['card_bg'])
        footer.pack(side=tk.BOTTOM, fill=tk.X, padx=24, pady=(16, 24))

        content_view = ScrollablePage(body, bg=COLORS['card_bg'])
        content_view.pack(fill=tk.BOTH, expand=True, padx=24, pady=(24, 0))

        window.after_idle(content_view.scroll_to_top)
        return window, content_view.inner, footer

    @staticmethod
    def _normalize_info_image_item(item):
        if isinstance(item, str):
            return {
                'source': str(item or '').strip(),
                'caption': '',
                'max_width': 560,
                'max_height': 420,
            }
        if not isinstance(item, dict):
            return {
                'source': '',
                'caption': '',
                'max_width': 560,
                'max_height': 420,
            }
        return {
            'source': str(item.get('url') or item.get('path') or item.get('src') or '').strip(),
            'caption': str(item.get('caption') or item.get('alt') or '').strip(),
            'max_width': max(int(item.get('max_width', 560) or 560), 1),
            'max_height': max(int(item.get('max_height', 420) or 420), 1),
        }

    @staticmethod
    def _resolve_info_image_source(source):
        raw_source = str(source or '').strip()
        if not raw_source:
            return ''
        parsed = urllib.parse.urlsplit(raw_source)
        if parsed.scheme in {'http', 'https'}:
            return raw_source
        normalized_path = raw_source.replace('\\', '/').lstrip('/')
        local_path = get_resource_path(normalized_path)
        if os.path.exists(local_path):
            return local_path
        quoted_path = urllib.parse.quote(normalized_path, safe='/')
        return f'{REPO_RAW_BASE_URL}/{quoted_path}'

    @staticmethod
    def _load_info_image(source, max_size):
        try:
            from PIL import Image as _PILImage
            from PIL import ImageTk as _ImageTk
        except Exception:
            return None

        try:
            parsed = urllib.parse.urlsplit(str(source or '').strip())
            if parsed.scheme in {'http', 'https'}:
                request = urllib.request.Request(source, method='GET')
                request.add_header('User-Agent', 'PaperLab/1.0')
                request.add_header('Cache-Control', 'no-cache')
                with urllib.request.urlopen(request, timeout=10) as response:
                    raw_bytes = response.read()
                image_stream = io.BytesIO(raw_bytes)
                with _PILImage.open(image_stream) as source_image:
                    image = source_image.convert('RGBA')
            else:
                with _PILImage.open(source) as source_image:
                    image = source_image.convert('RGBA')

            if max_size:
                resampling = getattr(getattr(_PILImage, 'Resampling', _PILImage), 'LANCZOS', getattr(_PILImage, 'LANCZOS', 1))
                image.thumbnail(max_size, resampling)
            return _ImageTk.PhotoImage(image)
        except Exception:
            return None

    def _render_info_images(self, parent, images, owner):
        image_items = list(images or [])
        if not image_items:
            return

        image_refs = getattr(owner, '_info_image_refs', None)
        if image_refs is None:
            image_refs = []
            setattr(owner, '_info_image_refs', image_refs)

        for item in image_items:
            image_meta = self._normalize_info_image_item(item)
            image_source = self._resolve_info_image_source(image_meta.get('source', ''))
            if not image_source:
                continue
            photo = self._load_info_image(
                image_source,
                max_size=(image_meta.get('max_width', 560), image_meta.get('max_height', 420)),
            )
            if photo is None:
                continue

            image_refs.append(photo)
            image_label = tk.Label(parent, image=photo, bg=COLORS['card_bg'], bd=0, highlightthickness=0)
            image_label.pack(anchor='center', pady=(8, 8))

            caption = image_meta.get('caption', '')
            if caption:
                caption_label = tk.Label(
                    parent,
                    text=caption,
                    font=FONTS['small'],
                    fg=COLORS['text_sub'],
                    bg=COLORS['card_bg'],
                    anchor='center',
                    justify='center',
                )
                caption_label.pack(anchor='center', fill=tk.X, pady=(0, 8))
                bind_adaptive_wrap(caption_label, parent, padding=16, min_width=320)

    def _close_dialog(self, window):
        if window in self.dialogs:
            self.dialogs.remove(window)
        if window is self.settings_window:
            self.settings_window = None
        if window is self._prompt_manager_window:
            self._prompt_manager_window = None
            self._prompt_manager_panel = None
        if window is self._prompt_compact_window:
            self._prompt_compact_window = None
            self._prompt_compact_panel = None
        if window is self._skills_center_window:
            self._skills_center_window = None
            self._skills_center_panel = None
        if window is self._discover_skills_window:
            self._discover_skills_window = None
            self._discover_skills_panel = None
        if window is self._repo_manage_window:
            self._repo_manage_window = None
        window.destroy()

    def _get_active_model_label(self):
        active_api = self.config_mgr.active_api
        cfg = self.config_mgr.get_api_config(active_api) or {}
        name = (cfg.get('name', '') or '').strip() or active_api or '未配置'
        model = resolve_model_display_name(cfg)
        return f'{name} / {model}' if model else name

    def _prefetch_announcement(self):
        """启动后预拉取公告，用于红点提示"""
        if self._is_shutting_down or not self._remote_content:
            return
        self._remote_content.fetch('announcement', on_success=self._on_announcement_prefetch)

    def _on_announcement_prefetch(self, data):
        if self._is_shutting_down:
            return
        last_seen = self.config_mgr.get_setting('last_seen_announcement_id', '')
        current_id = data.get('id', '')
        if current_id and current_id != last_seen:
            self._show_bell_badge()
        else:
            self._clear_bell_badge()

    def _prefetch_push(self):
        if self._is_shutting_down or not self._remote_content or self.launch_silently:
            return
        self._remote_content.fetch('push', on_success=self._on_push_prefetch)

    def _on_push_prefetch(self, data):
        if self._is_shutting_down:
            return
        push_id = str((data or {}).get('id', '') or '').strip()
        if not push_id:
            return
        last_seen = self.config_mgr.get_setting('last_seen_push_id', '')
        if push_id == last_seen:
            return
        self._show_push_dialog(prefetched_data=data)

    def _show_bell_badge(self):
        self._bell_badge_visible = True
        bell_button = self._resolve_tool_button(getattr(self, 'bell_button', None))
        if bell_button is not None:
            try:
                bell_button._tool_has_badge = True
                self._refresh_top_tool_button(getattr(self, 'bell_button', None))
            except tk.TclError:
                pass

    def _clear_bell_badge(self):
        self._bell_badge_visible = False
        bell_button = self._resolve_tool_button(getattr(self, 'bell_button', None))
        if bell_button is not None:
            try:
                bell_button._tool_has_badge = False
                self._refresh_top_tool_button(getattr(self, 'bell_button', None))
            except tk.TclError:
                pass

    def _show_announcement(self):
        window, content, footer = self._create_info_dialog_shell('系统公告', '860x680', min_width=720, min_height=560)

        tk.Label(content, text='纸研社', font=FONTS['title'], fg=COLORS['text_main'], bg=COLORS['card_bg']).pack(anchor='w', fill=tk.X, pady=(0, 8))

        loading_label = tk.Label(content, text='正在加载公告内容...', font=FONTS['body'], fg=COLORS['text_sub'], bg=COLORS['card_bg'], anchor='w')
        loading_label.pack(anchor='w', fill=tk.X)

        def _safe_exists():
            try:
                return window.winfo_exists()
            except tk.TclError:
                return False

        def _render_content(data, from_cache=False):
            if not _safe_exists():
                return
            loading_label.destroy()
            self._render_info_images(content, data.get('images', []), window)
            for section in data.get('sections', []):
                heading = section.get('heading', '')
                if heading:
                    tk.Label(content, text=heading, font=FONTS['body_bold'], fg=COLORS['text_main'], bg=COLORS['card_bg'], anchor='w').pack(anchor='w', fill=tk.X, pady=(8, 4))
                for item in section.get('items', []):
                    lbl = tk.Label(content, text=f'  · {item}', font=FONTS['body'], fg=COLORS['text_sub'], bg=COLORS['card_bg'], anchor='w', justify='left')
                    lbl.pack(anchor='w', fill=tk.X)
                    bind_adaptive_wrap(lbl, content, padding=8, min_width=320)
                self._render_info_images(content, section.get('images', []), window)
            foot_note = data.get('footer_note', '')
            if foot_note:
                fn_label = tk.Label(content, text=foot_note, font=FONTS['body'], fg=COLORS['text_sub'], bg=COLORS['card_bg'], anchor='w', justify='left')
                fn_label.pack(anchor='w', fill=tk.X, pady=(10, 0))
                bind_adaptive_wrap(fn_label, content, padding=8, min_width=320)
            if from_cache:
                tk.Label(footer, text='(离线数据)', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).pack(side=tk.LEFT)
            # 标记已读
            ann_id = data.get('id', '')
            if ann_id:
                self.config_mgr.set_setting('last_seen_announcement_id', ann_id)
                self.config_mgr.save()
                self._clear_bell_badge()

        def on_loaded(data):
            _render_content(data, from_cache=False)

        def on_error(exc):
            if not _safe_exists():
                return
            cached = self._remote_content.get_cached('announcement')
            if cached:
                _render_content(cached, from_cache=True)
            else:
                loading_label.configure(text='无法加载公告内容，请检查网络连接。')

        ModernButton(footer, '我知道了', style='primary', command=lambda: self._close_dialog(window)).pack(anchor='e')
        self._remote_content.fetch('announcement', on_success=on_loaded, on_error=on_error)

    def _show_push_dialog(self, prefetched_data=None):
        existing_window = getattr(self, '_push_window', None)
        if existing_window is not None:
            try:
                if existing_window.winfo_exists():
                    existing_window.lift()
                    existing_window.focus_force()
                    return
            except tk.TclError:
                pass

        window, content, footer = self._create_info_dialog_shell('消息推送', '860x680', min_width=720, min_height=560)
        self._push_window = window
        window.bind('<Destroy>', lambda _event: setattr(self, '_push_window', None), add='+')

        tk.Label(content, text='消息推送', font=FONTS['title'], fg=COLORS['text_main'], bg=COLORS['card_bg']).pack(anchor='w', fill=tk.X, pady=(0, 8))

        loading_label = tk.Label(content, text='正在加载推送内容...', font=FONTS['body'], fg=COLORS['text_sub'], bg=COLORS['card_bg'], anchor='w')
        loading_label.pack(anchor='w', fill=tk.X)

        def _safe_exists():
            try:
                return window.winfo_exists()
            except tk.TclError:
                return False

        def _mark_seen(push_id):
            push_id = str(push_id or '').strip()
            if not push_id:
                return
            self.config_mgr.set_setting('last_seen_push_id', push_id)
            self.config_mgr.save()

        def _render_content(data, from_cache=False):
            if not _safe_exists():
                return
            loading_label.destroy()
            self._render_info_images(content, data.get('images', []), window)
            title = str(data.get('title', '') or '').strip() or '消息推送'
            publish_date = str(data.get('publish_date', '') or '').strip()
            title_text = title if not publish_date else f'{title}  {publish_date}'
            tk.Label(content, text=title_text, font=FONTS['body_bold'], fg=COLORS['text_main'], bg=COLORS['card_bg'], anchor='w').pack(anchor='w', fill=tk.X, pady=(0, 8))
            description = str(data.get('description', '') or '').strip()
            if description:
                desc_label = tk.Label(content, text=description, font=FONTS['body'], fg=COLORS['text_sub'], bg=COLORS['card_bg'], anchor='w', justify='left')
                desc_label.pack(anchor='w', fill=tk.X, pady=(0, 8))
                bind_adaptive_wrap(desc_label, content, padding=8, min_width=320)
            for section in data.get('sections', []):
                heading = str(section.get('heading', '') or '').strip()
                if heading:
                    tk.Label(content, text=heading, font=FONTS['body_bold'], fg=COLORS['text_main'], bg=COLORS['card_bg'], anchor='w').pack(anchor='w', fill=tk.X, pady=(8, 4))
                for item in section.get('items', []):
                    item_label = tk.Label(content, text=f'  • {item}', font=FONTS['body'], fg=COLORS['text_sub'], bg=COLORS['card_bg'], anchor='w', justify='left')
                    item_label.pack(anchor='w', fill=tk.X)
                    bind_adaptive_wrap(item_label, content, padding=8, min_width=320)
                for link in section.get('links', []):
                    label_text = str(link.get('label', '') or '').strip()
                    url = str(link.get('url', '') or '').strip()
                    if not label_text or not url:
                        continue
                    link_label = tk.Label(content, text=label_text, font=FONTS['body'], fg=COLORS['primary'], bg=COLORS['card_bg'], anchor='w', cursor='hand2')
                    link_label.pack(anchor='w', fill=tk.X, pady=(2, 0))
                    link_label.bind('<Button-1>', lambda _event, u=url: webbrowser.open(u))
                self._render_info_images(content, section.get('images', []), window)
            foot_note = str(data.get('footer_note', '') or '').strip()
            if foot_note:
                fn_label = tk.Label(content, text=foot_note, font=FONTS['body'], fg=COLORS['text_sub'], bg=COLORS['card_bg'], anchor='w', justify='left')
                fn_label.pack(anchor='w', fill=tk.X, pady=(10, 0))
                bind_adaptive_wrap(fn_label, content, padding=8, min_width=320)
            if from_cache:
                tk.Label(footer, text='(缓存内容)', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).pack(side=tk.LEFT)
            _mark_seen(data.get('id', ''))

        def on_loaded(data):
            _render_content(data, from_cache=False)

        def on_error(_exc):
            if not _safe_exists():
                return
            cached = self._remote_content.get_cached('push')
            if cached:
                _render_content(cached, from_cache=True)
            else:
                loading_label.configure(text='无法加载推送内容。')

        ModernButton(footer, '关闭', style='primary', command=lambda: self._close_dialog(window)).pack(anchor='e')
        if prefetched_data:
            on_loaded(prefetched_data)
        else:
            self._remote_content.fetch('push', on_success=on_loaded, on_error=on_error)

    def _show_tutorial(self):
        window, content, footer = self._create_info_dialog_shell('使用教程', '920x720', min_width=760, min_height=600)

        tk.Label(content, text='纸研社使用教程', font=FONTS['title'], fg=COLORS['text_main'], bg=COLORS['card_bg']).pack(anchor='w', fill=tk.X, pady=(0, 10))

        tutorial_text = (
            '纸研社按论文处理流程组织功能，建议按下面顺序使用：\n\n'
            '1. 先进入“模型配置”，填写 API Key、接口地址和模型名称，保存后完成连接测试。\n'
            '2. 再进入“论文写作”，导入文稿或新建草稿，整理大纲并按章节生成、补写正文。\n'
            '3. 论文写作页中的内容可以继续送入“学术润色”“降AI检测”“降查重率”“智能纠错”，按实际需要逐步优化表达、降低风险并检查问题。\n'
            '4. 每次处理结果都会写入“历史记录”，便于回看、比对和导出；主题模式、默认启动页等偏好可在“设置”中统一调整。'
        )

        body_label = tk.Label(
            content,
            text=tutorial_text,
            justify='left',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            anchor='w',
        )
        body_label.pack(anchor='w', fill=tk.X)
        bind_adaptive_wrap(body_label, content, padding=8, min_width=360)

        ModernButton(
            footer,
            '打开模型配置',
            style='secondary',
            command=lambda: [self._close_dialog(window), self._show_api_config_dialog()],
        ).pack(anchor='e')

    def _show_about_dialog(self):
        window, content, footer = self._create_info_dialog_shell('关于纸研社', '760x620', min_width=620, min_height=500)

        tk.Label(content, text='纸研社', font=FONTS['title'], fg=COLORS['text_main'], bg=COLORS['card_bg']).pack(anchor='w', fill=tk.X, pady=(0, 8))

        loading_label = tk.Label(content, text='正在加载...', font=FONTS['body'], fg=COLORS['text_sub'], bg=COLORS['card_bg'], anchor='w')
        loading_label.pack(anchor='w', fill=tk.X)

        def _safe_exists():
            try:
                return window.winfo_exists()
            except tk.TclError:
                return False

        def _render_content(data, from_cache=False):
            if not _safe_exists():
                return
            loading_label.destroy()
            self._render_info_images(content, data.get('images', []), window)
            desc = data.get('description', '')
            if desc:
                desc_label = tk.Label(content, text=desc, font=FONTS['body'], fg=COLORS['text_sub'], bg=COLORS['card_bg'], anchor='w', justify='left')
                desc_label.pack(anchor='w', fill=tk.X, pady=(0, 8))
                bind_adaptive_wrap(desc_label, content, padding=8, min_width=320)
            features = data.get('features', [])
            if features:
                tk.Label(content, text='主要功能', font=FONTS['body_bold'], fg=COLORS['text_main'], bg=COLORS['card_bg'], anchor='w').pack(anchor='w', fill=tk.X, pady=(4, 4))
                for feat in features:
                    tk.Label(content, text=f'  · {feat}', font=FONTS['body'], fg=COLORS['text_sub'], bg=COLORS['card_bg'], anchor='w').pack(anchor='w', fill=tk.X)
            links = data.get('links', [])
            if links:
                tk.Label(content, text='相关链接', font=FONTS['body_bold'], fg=COLORS['text_main'], bg=COLORS['card_bg'], anchor='w').pack(anchor='w', fill=tk.X, pady=(10, 4))
                for link in links:
                    label_text = link.get('label', '')
                    url = link.get('url', '')
                    link_label = tk.Label(content, text=label_text, font=FONTS['body'], fg=COLORS['primary'], bg=COLORS['card_bg'], anchor='w', cursor='hand2')
                    link_label.pack(anchor='w', fill=tk.X)
                    link_label.bind('<Button-1>', lambda e, u=url: webbrowser.open(u))
            acknowledgements = data.get('acknowledgements', [])
            if acknowledgements:
                tk.Label(content, text='致谢', font=FONTS['body_bold'], fg=COLORS['text_main'], bg=COLORS['card_bg'], anchor='w').pack(anchor='w', fill=tk.X, pady=(10, 4))
                for item in acknowledgements:
                    name = str(item or '').strip()
                    if not name:
                        continue
                    tk.Label(content, text=f'  - {name}', font=FONTS['body'], fg=COLORS['text_sub'], bg=COLORS['card_bg'], anchor='w').pack(anchor='w', fill=tk.X)
            copyright_text = data.get('copyright', '')
            if copyright_text:
                tk.Label(content, text=copyright_text, font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg'], anchor='w').pack(anchor='w', fill=tk.X, pady=(12, 0))
            if from_cache:
                tk.Label(footer, text='(离线数据)', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).pack(side=tk.LEFT)

        def on_loaded(data):
            _render_content(data, from_cache=False)

        def on_error(exc):
            if not _safe_exists():
                return
            cached = self._remote_content.get_cached('about')
            if cached:
                _render_content(cached, from_cache=True)
            else:
                loading_label.configure(text='面向论文写作、模型配置与学术处理的本地桌面工具。')

        ModernButton(footer, '关闭', style='primary', command=lambda: self._close_dialog(window)).pack(anchor='e')
        self._remote_content.fetch('about', on_success=on_loaded, on_error=on_error)

    def _show_theme_menu(self):
        if self._theme_menu_window and self._theme_menu_window.winfo_exists():
            self._close_theme_menu()
            return

        current_mode = self.config_mgr.get_setting('theme_mode', 'light')
        current_system = get_system_theme()

        window = tk.Toplevel(self.root)
        window.wm_overrideredirect(True)
        window.transient(self.root)
        window.configure(bg=COLORS['shadow'])

        shell = tk.Frame(window, bg=COLORS['shadow'])
        shell.pack(fill=tk.BOTH, expand=True)

        card = tk.Frame(
            shell,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
            bd=0,
        )
        card.pack(fill=tk.BOTH, expand=True, padx=(0, 3), pady=(0, 3))

        options_host = tk.Frame(card, bg=COLORS['card_bg'])
        options_host.pack(fill=tk.BOTH, expand=True, padx=0, pady=(4, 3))

        theme_items = [
            ('light', '浅色模式', '始终使用浅色主题', 'light'),
            ('dark', '深色模式', '始终使用深色主题', 'dark'),
            ('follow_system', '自动模式', '跟随系统主题设置', 'system'),
        ]

        for value, title, subtitle, icon_kind in theme_items:
            self._build_theme_menu_option(
                options_host,
                value=value,
                title=title,
                subtitle=subtitle,
                icon_kind=icon_kind,
                selected=(current_mode == value),
            )

        divider = tk.Frame(card, bg=COLORS['card_border'], height=1)
        divider.pack(fill=tk.X, padx=10, pady=(0, 0))

        footer = tk.Frame(card, bg=COLORS['card_bg'])
        footer.pack(fill=tk.X, padx=12, pady=(6, 8))
        tk.Label(
            footer,
            text=f'当前跟随系统：{"浅色" if current_system == "light" else "深色"}',
            font=FONTS['tiny'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            anchor='w',
            justify='left',
        ).pack(anchor='w')

        self._theme_menu_window = window
        self._position_theme_menu(window)
        window.update_idletasks()
        self._position_theme_menu(window)
        window.lift(self.root)
        window.bind('<Escape>', lambda _event: self._close_theme_menu())
        window.after(120, self._bind_theme_menu_outside_close)

    def _build_theme_menu_option(self, parent, *, value, title, subtitle, icon_kind, selected=False):
        selected_bg = COLORS['accent_light']
        hover_bg = COLORS['surface_alt']
        base_bg = COLORS['card_bg']
        title_fg = COLORS['text_main']
        subtitle_fg = COLORS['text_sub']
        title_font = (FONTS['body'][0], 9)
        subtitle_font = (FONTS['tiny'][0], 7)
        text_width = 220
        text_height = 66
        subtitle_wraplength = 216

        row = tk.Frame(parent, bg=selected_bg if selected else base_bg, cursor='hand2')
        row.pack(fill=tk.X, padx=4, pady=0)

        icon_wrap = tk.Frame(row, bg=row.cget('bg'), width=26, height=26)
        icon_wrap.pack(side=tk.LEFT, padx=(8, 6), pady=7)
        icon_wrap.pack_propagate(False)

        icon_canvas = tk.Canvas(
            icon_wrap,
            width=18,
            height=18,
            bg=row.cget('bg'),
            bd=0,
            highlightthickness=0,
        )
        icon_canvas.pack(expand=True)

        text_wrap = tk.Frame(row, bg=row.cget('bg'), width=text_width, height=text_height)
        text_wrap.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 8), pady=7)
        text_wrap.pack_propagate(False)

        title_label = tk.Label(
            text_wrap,
            text=title,
            font=title_font,
            fg=title_fg,
            bg=row.cget('bg'),
            anchor='w',
        )
        title_label.pack(anchor='w')

        subtitle_label = tk.Label(
            text_wrap,
            text=subtitle,
            font=subtitle_font,
            fg=subtitle_fg,
            bg=row.cget('bg'),
            anchor='w',
            justify='left',
            wraplength=subtitle_wraplength,
        )
        subtitle_label.pack(anchor='w', pady=(1, 0))

        option_widgets = []
        restore_job = {'id': None}

        def cancel_restore_job():
            job_id = restore_job['id']
            if job_id is None:
                return
            try:
                row.after_cancel(job_id)
            except tk.TclError:
                pass
            restore_job['id'] = None

        def is_pointer_inside_option():
            if not row.winfo_exists():
                return False
            try:
                target = row.winfo_containing(row.winfo_pointerx(), row.winfo_pointery())
            except tk.TclError:
                return False
            if not target:
                return False
            return any(target is widget or str(target).startswith(str(widget)) for widget in option_widgets)

        def apply_visual(bg, *, active=False):
            icon_color = COLORS['primary'] if active else COLORS['text_main']
            row.configure(bg=bg)
            icon_wrap.configure(bg=bg)
            icon_canvas.configure(bg=bg)
            text_wrap.configure(bg=bg)
            title_label.configure(bg=bg)
            subtitle_label.configure(bg=bg)
            self._draw_theme_menu_icon(icon_canvas, icon_kind, icon_color)

        def on_enter(_event=None):
            cancel_restore_job()
            if selected:
                return
            apply_visual(hover_bg)

        def on_leave(_event=None):
            cancel_restore_job()
            if selected:
                apply_visual(selected_bg, active=True)
                return

            def restore_if_pointer_outside():
                restore_job['id'] = None
                if is_pointer_inside_option():
                    return
                apply_visual(base_bg)

            # 鼠标在同一行的子控件之间移动时，Tk 会连续派发 Enter/Leave。
            # 延后一次再判断真实位置，避免主题子菜单在两种样式间闪烁。
            restore_job['id'] = row.after(16, restore_if_pointer_outside)

        def on_click(_event=None):
            cancel_restore_job()
            self._close_theme_menu()
            self._apply_theme(value)
            return 'break'

        apply_visual(selected_bg if selected else base_bg, active=selected)
        option_widgets = [row, icon_wrap, icon_canvas, text_wrap, title_label, subtitle_label]

        for widget in option_widgets:
            widget.bind('<Enter>', on_enter, add='+')
            widget.bind('<Leave>', on_leave, add='+')
            widget.bind('<Button-1>', on_click, add='+')

    def _draw_theme_menu_icon(self, canvas, icon_kind, color):
        canvas.delete('all')
        if icon_kind == 'light':
            canvas.create_oval(6, 6, 12, 12, outline=color, width=1.5)
            rays = (
                (9, 0.5, 9, 3),
                (9, 15, 9, 17.5),
                (0.5, 9, 3, 9),
                (15, 9, 17.5, 9),
                (3, 3, 4.7, 4.7),
                (13.3, 13.3, 15, 15),
                (3, 15, 4.7, 13.3),
                (13.3, 4.7, 15, 3),
            )
            for x1, y1, x2, y2 in rays:
                canvas.create_line(x1, y1, x2, y2, fill=color, width=1.4, capstyle=tk.ROUND)
            return

        if icon_kind == 'dark':
            canvas.create_oval(2, 2, 13, 13, outline=color, width=1.5)
            canvas.create_oval(6.5, 1, 16, 11.5, outline=canvas.cget('bg'), fill=canvas.cget('bg'), width=0)
            return

        canvas.create_rectangle(2.5, 2.5, 15.5, 10.5, outline=color, width=1.5)
        canvas.create_line(9, 10.5, 9, 13.5, fill=color, width=1.5)
        canvas.create_line(5.5, 14.5, 12.5, 14.5, fill=color, width=1.5)

    def _position_theme_menu(self, window):
        if not window or not window.winfo_exists():
            return
        anchor = self.theme_tool_button if self.theme_tool_button and self.theme_tool_button.winfo_exists() else self.root
        anchor.update_idletasks()
        window.update_idletasks()

        width = window.winfo_reqwidth()
        height = window.winfo_reqheight()
        x = anchor.winfo_rootx() + anchor.winfo_width() - width
        y = anchor.winfo_rooty() + anchor.winfo_height() + 8
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max(12, min(x, screen_width - width - 12))
        y = max(12, min(y, screen_height - height - 12))
        window.geometry(f'+{x}+{y}')

    def _bind_theme_menu_outside_close(self):
        if self._theme_menu_root_click_bind:
            return
        self._theme_menu_root_click_bind = self.root.bind('<Button-1>', self._on_theme_menu_root_click, add='+')
        self._theme_menu_focusout_bind = self.root.bind('<FocusOut>', self._on_theme_menu_root_focus_out, add='+')
        self._theme_menu_unmap_bind = self.root.bind('<Unmap>', self._on_theme_menu_root_unmap, add='+')

    def _is_theme_menu_related_widget(self, widget):
        if not widget:
            return False
        theme_menu = self._theme_menu_window
        if theme_menu and theme_menu.winfo_exists():
            if widget is theme_menu or str(widget).startswith(str(theme_menu)):
                return True
        anchor = self.theme_tool_button
        if anchor and anchor.winfo_exists():
            if widget is anchor or str(widget).startswith(str(anchor)):
                return True
        return False

    def _on_theme_menu_root_click(self, event=None):
        if self._is_theme_menu_related_widget(getattr(event, 'widget', None)):
            return
        self._close_theme_menu()

    def _on_theme_menu_root_focus_out(self, _event=None):
        if not self._theme_menu_window or not self._theme_menu_window.winfo_exists():
            return
        self.root.after(60, self._close_theme_menu_if_app_inactive)

    def _on_theme_menu_root_unmap(self, _event=None):
        self._close_theme_menu()

    def _close_theme_menu_if_app_inactive(self):
        if not self._theme_menu_window or not self._theme_menu_window.winfo_exists():
            return
        try:
            focused = self.root.focus_displayof()
        except tk.TclError:
            focused = None
        if focused is None:
            self._close_theme_menu()

    def _close_theme_menu(self):
        if self._theme_menu_root_click_bind:
            try:
                self.root.unbind('<Button-1>', self._theme_menu_root_click_bind)
            except tk.TclError:
                pass
            self._theme_menu_root_click_bind = None
        if self._theme_menu_focusout_bind:
            try:
                self.root.unbind('<FocusOut>', self._theme_menu_focusout_bind)
            except tk.TclError:
                pass
            self._theme_menu_focusout_bind = None
        if self._theme_menu_unmap_bind:
            try:
                self.root.unbind('<Unmap>', self._theme_menu_unmap_bind)
            except tk.TclError:
                pass
            self._theme_menu_unmap_bind = None

        if self._theme_menu_window and self._theme_menu_window.winfo_exists():
            try:
                self._theme_menu_window.destroy()
            except tk.TclError:
                pass
        self._theme_menu_window = None

    def _show_api_config_dialog(self, return_to_model_list=False):
        if return_to_model_list:
            self._api_config_return_to_model_list = True
        if hasattr(self, '_api_config_window') and self._api_config_window and self._api_config_window.winfo_exists():
            self._api_config_window.lift()
            self._api_config_window.focus_force()
            return
        self._dialog_api_page = None
        self._api_config_return_to_model_list = bool(return_to_model_list)

        dialog_geometry = '1600x1200'
        window, body = self._create_dialog_shell('模型配置', dialog_geometry)
        window.resizable(True, True)
        apply_adaptive_window_geometry(window, dialog_geometry, min_width=1320, min_height=960)
        self._api_config_window = window

        # 底部悬浮保存按钮（先 pack，使内容区 expand 正确）
        footer = tk.Frame(body, bg=COLORS['card_bg'],
                          highlightbackground=COLORS['card_border'], highlightthickness=1)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        save_row = tk.Frame(footer, bg=COLORS['card_bg'])
        save_row.pack(fill=tk.X, padx=24, pady=12)

        self._api_config_tip = tk.Label(
            save_row, text='', font=FONTS['small'],
            fg=COLORS['success'], bg=COLORS['card_bg'], anchor='w',
        )
        self._api_config_tip.pack(side=tk.LEFT, expand=True, fill=tk.X)

        action_row = tk.Frame(save_row, bg=COLORS['card_bg'])
        action_row.pack(side=tk.RIGHT)

        # 内容区
        content = tk.Frame(body, bg=COLORS['bg_main'])
        content.pack(fill=tk.BOTH, expand=True)

        from pages.api_config_page import APIConfigPage
        dialog_api_page = APIConfigPage(
            content,
            self.config_mgr,
            self.api_client,
            self.history_mgr,
            self._set_status,
            navigate_page=self._show_page,
            app_bridge=self.app_bridge,
            force_new=True,
        )
        self._dialog_api_page = dialog_api_page
        dialog_api_page.frame.pack(fill=tk.BOTH, expand=True)

        save_button = ModernButton(
            action_row, '保存配置', style='primary',
            command=lambda: _save_and_notify(), padx=20, pady=10,
        )
        save_button.pack(side=tk.RIGHT)

        def _refresh_model_list():
            home = self.pages.get('home')
            if home and hasattr(home, '_model_list_refresh') and callable(home._model_list_refresh):
                home._model_list_refresh()

        def _refresh_footer_actions():
            if getattr(dialog_api_page, '_current_api_id', None):
                if not delete_button.winfo_manager():
                    delete_button.pack(side=tk.RIGHT, padx=(0, 10))
            elif delete_button.winfo_manager():
                delete_button.pack_forget()

        def _delete_and_refresh():
            current_api_id = getattr(dialog_api_page, '_current_api_id', None)
            dialog_api_page._delete_current()
            if current_api_id and current_api_id != getattr(dialog_api_page, '_current_api_id', None):
                _refresh_model_list()

        delete_button = ModernButton(
            action_row, '删除此记录', style='danger',
            command=_delete_and_refresh, padx=20, pady=10,
        )

        dialog_api_page._on_state_change_callback = _refresh_footer_actions
        _refresh_footer_actions()

        def _save_and_notify():
            if not dialog_api_page._save_all():
                return
            return_to_model_list = self._api_config_return_to_model_list
            self._set_status('配置已保存')
            _on_close()
            if return_to_model_list:
                self.root.after(120, self._reopen_model_list_dialog)

        def _on_close():
            self._api_config_window = None
            self._dialog_api_page = None
            self._api_config_return_to_model_list = False
            self._close_dialog(window)

        window.protocol('WM_DELETE_WINDOW', _on_close)

    def _reopen_model_list_dialog(self):
        home = self.pages.get('home')
        if home and hasattr(home, '_show_model_list'):
            home._show_model_list()

    def _switch_api_provider_in_dialog(self, api_id):
        """在已打开的配置弹窗中切换到指定服务商"""
        if self._dialog_api_page:
            self._dialog_api_page._select_api(api_id)
        else:
            self._show_api_config_dialog()
            if self._api_config_window:
                self._api_config_window.after(
                    200,
                    lambda: self._dialog_api_page._select_api(api_id)
                    if self._dialog_api_page else None
                )

    def _add_new_provider_in_dialog(self):
        """在已打开的配置弹窗中触发添加新服务商"""
        if self._dialog_api_page:
            self._dialog_api_page._select_preset('openai')
            return
        self._show_api_config_dialog()
        if self._api_config_window:
            self._api_config_window.after(
                200,
                lambda: self._dialog_api_page._select_preset('openai')
                if self._dialog_api_page else None
            )

    def _show_model_routing(self):
        from pages.model_routing_page import ModelRoutingPanel

        existing_window = getattr(self, '_model_routing_window', None)
        if existing_window and existing_window.winfo_exists():
            existing_window.lift()
            existing_window.focus_force()
            return getattr(self, '_model_routing_panel', None)

        geometry = '1280x960'
        window, body = self._create_dialog_shell('模型路由', geometry)
        window.resizable(True, True)
        apply_adaptive_window_geometry(window, geometry, min_width=960, min_height=720)
        self._model_routing_window = window

        # 底部悬浮保存按钮（与模型配置弹窗的底部栏保持一致）
        footer = tk.Frame(body, bg=COLORS['card_bg'],
                          highlightbackground=COLORS['card_border'], highlightthickness=1)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        save_row = tk.Frame(footer, bg=COLORS['card_bg'])
        save_row.pack(fill=tk.X, padx=24, pady=12)

        tip_label = tk.Label(
            save_row, text='', font=FONTS['small'],
            fg=COLORS['success'], bg=COLORS['card_bg'], anchor='w',
        )
        tip_label.pack(side=tk.LEFT, expand=True, fill=tk.X)

        action_row = tk.Frame(save_row, bg=COLORS['card_bg'])
        action_row.pack(side=tk.RIGHT)

        # 内容区
        content = tk.Frame(body, bg=COLORS['bg_main'])
        content.pack(fill=tk.BOTH, expand=True, padx=24, pady=24)

        def _close():
            self._model_routing_window = None
            self._model_routing_panel = None
            self._close_dialog(window)

        panel = ModelRoutingPanel(
            content,
            self.config_mgr,
            set_status=self._set_status,
            close_panel=_close,
            embed_action_bar=False,
        )
        panel.frame.pack(fill=tk.BOTH, expand=True)
        panel.attach_tip_label(tip_label)
        self._model_routing_panel = panel

        ModernButton(
            action_row, '保存配置', style='primary',
            command=panel.save, padx=20, pady=10,
        ).pack(side=tk.RIGHT)

        ModernButton(
            action_row, '重置', style='secondary',
            command=panel.reset_to_global, padx=20, pady=10,
        ).pack(side=tk.RIGHT, padx=(0, 10))

        window.protocol('WM_DELETE_WINDOW', _close)
        return panel

    def _show_prompt_manager(self, page_id=None, compact=False, scene_id=None):
        from pages.prompt_manager_page import PromptManagerPanel

        prompt_pages = {'paper_write', 'ai_reduce', 'plagiarism', 'polish', 'correction'}
        if not page_id and not scene_id and self.current_page_id in prompt_pages:
            page_id = self.current_page_id

        if compact:
            window_attr = '_prompt_compact_window'
            panel_attr = '_prompt_compact_panel'
            title = '提示词'
            geometry = '1600x1200'
            min_width, min_height = 1320, 960
            padding = 28
        else:
            window_attr = '_prompt_manager_window'
            panel_attr = '_prompt_manager_panel'
            title = '提示词管理中心'
            geometry = '1600x1200'
            min_width, min_height = 1320, 960
            padding = 28

        existing_window = getattr(self, window_attr, None)
        existing_panel = getattr(self, panel_attr, None)
        if existing_window and existing_window.winfo_exists() and existing_panel:
            existing_panel.focus_scene(page_id=page_id, scene_id=scene_id)
            existing_window.lift()
            existing_window.focus_force()
            return existing_panel

        window, body = self._create_dialog_shell(title, geometry)
        window.resizable(True, True)
        apply_adaptive_window_geometry(window, geometry, min_width=min_width, min_height=min_height)
        setattr(self, window_attr, window)

        panel = PromptManagerPanel(
            body,
            self.config_mgr,
            self._set_status,
            compact=compact,
            page_id=page_id,
            scene_id=scene_id,
            open_full=None,
            close_panel=(lambda win=window: self._close_dialog(win)) if compact else None,
        )
        panel.frame.pack(fill=tk.BOTH, expand=True, padx=padding, pady=padding)
        setattr(self, panel_attr, panel)
        return panel

    def _show_skills_center(self):
        from pages.skills_center_page import SkillsCenterPanel

        existing_window = self._skills_center_window
        existing_panel = self._skills_center_panel
        if existing_window and existing_window.winfo_exists() and existing_panel:
            existing_window.lift()
            existing_window.focus_force()
            if hasattr(existing_panel, 'refresh_all'):
                existing_panel.refresh_all(force_registry=False)
            return existing_panel

        window, body = self._create_dialog_shell('Skills 管理', '1600x1200')
        window.resizable(True, True)
        apply_adaptive_window_geometry(window, '1600x1200', min_width=1360, min_height=960)
        self._skills_center_window = window

        panel = SkillsCenterPanel(
            body,
            self.config_mgr,
            self.skill_manager,
            self._remote_content,
            set_status=self._set_status,
            close_panel=lambda win=window: self._close_dialog(win),
            app_bridge=self.app_bridge,
        )
        panel.frame.pack(fill=tk.BOTH, expand=True, padx=28, pady=28)
        self._skills_center_panel = panel
        return panel

    def _show_discover_skills(self):
        from pages.discover_skills_page import DiscoverSkillsPanel
        from modules.skill_marketplace import SkillMarketplaceClient

        existing_window = self._discover_skills_window
        existing_panel = self._discover_skills_panel
        if existing_window and existing_window.winfo_exists() and existing_panel:
            existing_window.lift()
            existing_window.focus_force()
            existing_panel._refresh()
            return existing_panel

        window, body = self._create_dialog_shell('发现技能', '1200x800')
        window.resizable(True, True)
        apply_adaptive_window_geometry(window, '1200x800', min_width=900, min_height=640)
        self._discover_skills_window = window

        # 创建或复用 marketplace 客户端
        if not hasattr(self, '_marketplace_client') or self._marketplace_client is None:
            skills_root = self.skill_manager.resolve_skills_root() if self.skill_manager else os.path.join(self.config_mgr.app_dir, 'skills')
            self._marketplace_client = SkillMarketplaceClient(
                skills_root,
                self.root,
                log_callback=self._write_app_log if hasattr(self, '_write_app_log') else None,
                project_root=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            )

        # 安装后回调，同步 Skills 管理面板
        def on_installed():
            if self._skills_center_panel and hasattr(self._skills_center_panel, 'refresh_all'):
                try:
                    self._skills_center_panel.refresh_all(force_registry=False)
                except Exception:
                    pass

        panel = DiscoverSkillsPanel(
            body,
            self.config_mgr,
            self.skill_manager,
            self._remote_content,
            self._marketplace_client,
            set_status=self._set_status,
            close_panel=lambda win=window: self._close_discover_dialog(win),
            on_skill_installed=on_installed,
            on_open_repo_manage=self._show_repo_manage,
        )
        panel.frame.pack(fill=tk.BOTH, expand=True, padx=28, pady=28)
        self._discover_skills_panel = panel
        return panel

    def _close_discover_dialog(self, window):
        self._discover_skills_window = None
        self._discover_skills_panel = None
        self._close_dialog(window)

    def _show_repo_manage(self):
        """关闭发现技能弹窗，打开仓库管理弹窗；关闭仓库管理弹窗后自动重新打开发现技能弹窗。"""
        # 复用已有窗口
        if self._repo_manage_window and self._repo_manage_window.winfo_exists():
            self._repo_manage_window.lift()
            self._repo_manage_window.focus_force()
            return
        from pages.discover_skills_page import RepoManagePanel
        # 先关闭发现技能弹窗
        if self._discover_skills_window and self._discover_skills_window.winfo_exists():
            self._close_discover_dialog(self._discover_skills_window)

        window, body = self._create_dialog_shell('仓库管理', '1200x800')
        window.resizable(True, True)
        apply_adaptive_window_geometry(window, '800x700', min_width=640, min_height=520)
        # 覆盖关闭协议：点 X 也走回到发现技能弹窗的逻辑
        window.protocol('WM_DELETE_WINDOW', lambda win=window: self._close_repo_manage_and_reopen_discover(win))

        # 仓库管理面板
        repo_panel = RepoManagePanel(
            body,
            self.config_mgr,
            self.skill_manager,
            self._remote_content,
            set_status=self._set_status,
            close_panel=lambda win=window: self._close_repo_manage_and_reopen_discover(win),
        )
        repo_panel.frame.pack(fill=tk.BOTH, expand=True, padx=28, pady=28)
        self._repo_manage_window = window

    def _close_repo_manage_and_reopen_discover(self, window):
        self._repo_manage_window = None
        self._close_dialog(window)
        # 重新打开发现技能弹窗
        self.root.after(100, self._show_discover_skills)

    def _collect_runtime_backup_zip_bytes(self):
        app_dir = os.path.abspath(self.config_mgr.app_dir)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
            for root, _dirs, files in os.walk(app_dir):
                for file_name in files:
                    abs_path = os.path.join(root, file_name)
                    rel_path = os.path.relpath(abs_path, app_dir).replace('\\', '/')
                    archive.write(abs_path, rel_path)
        return buffer.getvalue()

    def _get_local_data_timestamp(self):
        app_dir = os.path.abspath(self.config_mgr.app_dir)
        latest = 0
        for root, _dirs, files in os.walk(app_dir):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                try:
                    mtime = int(os.path.getmtime(file_path))
                except Exception:
                    continue
                if mtime > latest:
                    latest = mtime
        return latest or int(time.time())

    def _parse_backup_timestamp(self, payload):
        if not isinstance(payload, dict):
            return 0
        raw_epoch = payload.get('data_timestamp')
        try:
            epoch = int(raw_epoch or 0)
        except Exception:
            epoch = 0
        if epoch > 0:
            return epoch

        for key in ('exported_at',):
            text = str(payload.get(key, '') or '').strip()
            if not text:
                continue
            try:
                dt = datetime.strptime(text, '%Y-%m-%d %H:%M:%S')
                return int(dt.timestamp())
            except Exception:
                continue
        return 0

    def _build_local_backup_payload(self):
        from modules.usage_stats import safe_datetime_fromtimestamp
        zip_bytes = self._collect_runtime_backup_zip_bytes()
        data_timestamp = self._get_local_data_timestamp()
        return {
            'format': 'paperlab-backup-v1',
            'app_name': APP_NAME,
            'app_version': APP_VERSION,
            'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'data_timestamp': data_timestamp,
            'data_datetime': safe_datetime_fromtimestamp(data_timestamp).strftime('%Y-%m-%d %H:%M:%S'),
            'data_dir': os.path.abspath(self.config_mgr.app_dir),
            'payload_base64': base64.b64encode(zip_bytes).decode('ascii'),
        }

    def _restore_runtime_from_payload(self, payload):
        if not isinstance(payload, dict) or payload.get('format') != 'paperlab-backup-v1':
            raise ValueError('备份文件格式无效，无法识别。')
        encoded = str(payload.get('payload_base64', '') or '').strip()
        if not encoded:
            raise ValueError('备份文件缺少数据内容。')
        try:
            zip_bytes = base64.b64decode(encoded)
        except Exception as exc:
            raise ValueError(f'备份数据损坏：{exc}') from exc

        app_dir = os.path.abspath(self.config_mgr.app_dir)
        os.makedirs(app_dir, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(zip_bytes), mode='r') as archive:
            for member in archive.namelist():
                normalized = os.path.normpath(member).replace('\\', '/')
                if normalized.startswith('../') or normalized.startswith('/'):
                    raise ValueError(f'备份包含非法路径：{member}')
            archive.extractall(app_dir)

        self.history_mgr.reload_data_directory()
        self._sync_runtime_paths()
        self._set_status('备份数据已导入，请重启应用以完全生效', COLORS['success'])

    def _get_webdav_settings(self):
        raw_interval = self.config_mgr.get_setting('backup_webdav_auto_interval_sec', 3600)
        try:
            interval_sec = int(raw_interval or 3600)
        except Exception:
            interval_sec = 3600
        return {
            'url': str(self.config_mgr.get_setting('backup_webdav_url', '') or '').strip(),
            'username': str(self.config_mgr.get_setting('backup_webdav_username', '') or '').strip(),
            'password': str(self.config_mgr.get_setting('backup_webdav_password', '') or '').strip(),
            'auto_enabled': bool(self.config_mgr.get_setting('backup_webdav_auto_enabled', False)),
            'auto_interval_sec': interval_sec,
            'auto_strategy': str(self.config_mgr.get_setting('backup_webdav_auto_strategy', 'smart_merge') or 'smart_merge'),
        }

    def _build_webdav_remote_file_url(self, base_url):
        raw = str(base_url or '').strip()
        if not raw:
            raise ValueError('请先填写 WebDAV 地址。')
        parsed = urllib.parse.urlparse(raw)
        if parsed.scheme not in {'http', 'https'}:
            raise ValueError('WebDAV 地址必须以 http:// 或 https:// 开头。')
        if raw.endswith('.json'):
            return raw
        return raw.rstrip('/') + '/paperlab_backup.json'

    def _webdav_request(self, method, target_url, username='', password='', payload=None, timeout=20):
        request = urllib.request.Request(target_url, data=payload, method=method)
        request.add_header('User-Agent', f'{APP_NAME}/{APP_VERSION}')
        if payload is not None:
            request.add_header('Content-Type', 'application/json; charset=utf-8')
        if username:
            raw_token = f'{username}:{password}'.encode('utf-8')
            request.add_header('Authorization', 'Basic ' + base64.b64encode(raw_token).decode('ascii'))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), int(getattr(response, 'status', 200) or 200)

    def _webdav_test_connection(self, settings):
        target_url = self._build_webdav_remote_file_url(settings['url'])
        try:
            self._webdav_request('OPTIONS', target_url, settings['username'], settings['password'], timeout=15)
        except urllib.error.HTTPError as exc:
            if exc.code in {404, 405, 501}:
                self._webdav_request('HEAD', target_url, settings['username'], settings['password'], timeout=15)
                return target_url
            raise
        return target_url

    def _upload_backup_to_webdav(self, settings):
        target_url = self._build_webdav_remote_file_url(settings['url'])
        payload = json.dumps(self._build_local_backup_payload(), ensure_ascii=False, indent=2).encode('utf-8')
        self._webdav_request('PUT', target_url, settings['username'], settings['password'], payload=payload, timeout=45)
        return target_url

    def _download_backup_from_webdav(self, settings):
        target_url = self._build_webdav_remote_file_url(settings['url'])
        body, _status = self._webdav_request('GET', target_url, settings['username'], settings['password'], timeout=45)
        try:
            payload = json.loads(body.decode('utf-8'))
        except Exception as exc:
            raise ValueError(f'WebDAV 返回数据不是有效 JSON：{exc}') from exc
        self._restore_runtime_from_payload(payload)
        return target_url

    def _fetch_backup_payload_from_webdav(self, settings):
        target_url = self._build_webdav_remote_file_url(settings['url'])
        try:
            body, _status = self._webdav_request('GET', target_url, settings['username'], settings['password'], timeout=45)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None, target_url
            raise
        try:
            payload = json.loads(body.decode('utf-8'))
        except Exception as exc:
            raise ValueError(f'WebDAV 返回数据不是有效 JSON：{exc}') from exc
        return payload, target_url

    def _smart_merge_webdav(self, settings):
        remote_payload, target_url = self._fetch_backup_payload_from_webdav(settings)
        local_payload = self._build_local_backup_payload()
        local_ts = self._parse_backup_timestamp(local_payload)

        if not remote_payload:
            self._upload_backup_to_webdav(settings)
            return {'action': 'upload', 'target_url': target_url, 'local_ts': local_ts, 'remote_ts': 0}

        remote_ts = self._parse_backup_timestamp(remote_payload)
        if remote_ts > local_ts:
            self._restore_runtime_from_payload(remote_payload)
            return {'action': 'download', 'target_url': target_url, 'local_ts': local_ts, 'remote_ts': remote_ts}

        if local_ts > remote_ts:
            self._upload_backup_to_webdav(settings)
            return {'action': 'upload', 'target_url': target_url, 'local_ts': local_ts, 'remote_ts': remote_ts}

        return {'action': 'skip', 'target_url': target_url, 'local_ts': local_ts, 'remote_ts': remote_ts}

    def _schedule_webdav_auto_sync(self):
        if self._webdav_auto_sync_job:
            try:
                self.root.after_cancel(self._webdav_auto_sync_job)
            except Exception:
                pass
            self._webdav_auto_sync_job = None

        settings = self._get_webdav_settings() if self.config_mgr else {}
        if not settings.get('auto_enabled'):
            return

        interval_sec = max(60, int(settings.get('auto_interval_sec', 3600) or 3600))
        self._webdav_auto_sync_job = self.root.after(interval_sec * 1000, self._run_webdav_auto_sync)

    def _run_webdav_auto_sync(self):
        self._webdav_auto_sync_job = None
        settings = self._get_webdav_settings()
        if not settings.get('auto_enabled'):
            return
        if self._webdav_auto_sync_busy:
            self._schedule_webdav_auto_sync()
            return

        self._webdav_auto_sync_busy = True

        def worker():
            error_message = ''
            try:
                strategy = settings.get('auto_strategy', 'smart_merge')
                if strategy == 'smart_merge':
                    result = self._smart_merge_webdav(settings)
                    self._write_app_log(
                        f'WebDAV 智能合并完成: action={result["action"]} '
                        f'local_ts={result["local_ts"]} remote_ts={result["remote_ts"]}'
                    )
                elif strategy == 'upload_only':
                    self._upload_backup_to_webdav(settings)
                elif strategy == 'download_only':
                    self._download_backup_from_webdav(settings)
                else:
                    result = self._smart_merge_webdav(settings)
                    self._write_app_log(
                        f'WebDAV 智能合并完成: action={result["action"]} '
                        f'local_ts={result["local_ts"]} remote_ts={result["remote_ts"]}'
                    )
            except Exception as exc:
                error_message = str(exc)
                self._write_app_log(f'WebDAV 自动同步失败: {exc}', level='WARN')
            finally:
                def finish():
                    self._webdav_auto_sync_busy = False
                    self._webdav_auto_sync_last_error = error_message
                    self._schedule_webdav_auto_sync()
                self.root.after(0, finish)

        threading.Thread(target=worker, name='WebDAVAutoSync', daemon=True).start()

    def _show_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        dialog_geometry = '1600x1200'
        window, body = self._create_dialog_shell('设置', dialog_geometry)
        self.settings_window = window
        window.resizable(True, True)
        apply_adaptive_window_geometry(window, dialog_geometry, min_width=1320, min_height=960)

        theme_display = {
            'light': '浅色模式',
            'dark': '深色模式',
            'follow_system': '跟随系统',
        }
        billing_mode_display = {
            'request_model': '按请求模型匹配',
            'response_model': '按返回模型匹配',
        }
        import_recognition_display = {
            'local': '本地识别',
            'ai': 'AI识别',
        }
        startup_display = {
            'home': '首页',
            'api_config': '模型配置',
            **{page_id: label for page_id, label in TOP_NAV_ITEMS if page_id != 'home'},
        }
        theme_reverse = {label: key for key, label in theme_display.items()}
        billing_mode_reverse = {label: key for key, label in billing_mode_display.items()}
        import_recognition_reverse = {label: key for key, label in import_recognition_display.items()}
        startup_reverse = {label: key for key, label in startup_display.items()}
        billing_settings = self.config_mgr.get_global_billing_settings()
        parameter_settings = self.config_mgr.get_global_parameter_settings()

        theme_var = tk.StringVar(value=theme_display.get(self.config_mgr.get_setting('theme_mode', 'light'), '浅色模式'))
        startup_var = tk.StringVar(value=startup_display.get(self.config_mgr.get_setting('startup_page', 'home'), '首页'))
        launch_on_startup_var = tk.BooleanVar(value=self.config_mgr.get_setting('launch_on_startup', False))
        silent_startup_var = tk.BooleanVar(value=self.config_mgr.get_setting('silent_startup', False))
        minimize_to_tray_on_minimize_var = tk.BooleanVar(
            value=self.config_mgr.get_setting('minimize_to_tray_on_minimize', False)
        )
        minimize_to_tray_on_close_var = tk.BooleanVar(
            value=self.config_mgr.get_setting('minimize_to_tray_on_close', False)
        )
        home_stats_var = tk.BooleanVar(value=self.config_mgr.get_setting('show_home_stats', True))
        loading_var = tk.BooleanVar(value=self.config_mgr.get_setting('enable_loading_animation', True))
        import_recognition_var = tk.StringVar(
            value=import_recognition_display.get(
                self.config_mgr.get_setting('paper_write_import_recognition_mode', 'local'),
                '本地识别',
            )
        )
        global_test_prompt_var = tk.StringVar(value=self.config_mgr.get_setting('global_test_prompt', 'Who are you?'))
        global_test_timeout_var = tk.StringVar(value=str(self.config_mgr.get_setting('global_test_timeout_sec', 45)))
        global_test_degrade_var = tk.StringVar(value=str(self.config_mgr.get_setting('global_test_degrade_ms', 6000)))
        global_test_retries_var = tk.StringVar(value=str(self.config_mgr.get_setting('global_test_max_retries', 2)))
        global_billing_mode_var = tk.StringVar(value=billing_mode_display.get(billing_settings['mode'], '按请求模型匹配'))
        global_parameter_vars = {
            field: tk.StringVar(value=parameter_settings.get(field, ''))
            for field in (
                'temperature',
                'max_tokens',
                'timeout',
                'top_p',
                'presence_penalty',
                'frequency_penalty',
            )
        }
        webdav_url_var = tk.StringVar(value=self.config_mgr.get_setting('backup_webdav_url', ''))
        webdav_username_var = tk.StringVar(value=self.config_mgr.get_setting('backup_webdav_username', ''))
        webdav_password_var = tk.StringVar(value=self.config_mgr.get_setting('backup_webdav_password', ''))
        webdav_auto_enabled_var = tk.BooleanVar(value=self.config_mgr.get_setting('backup_webdav_auto_enabled', False))
        webdav_auto_interval_var = tk.StringVar(value=str(self.config_mgr.get_setting('backup_webdav_auto_interval_sec', 3600)))
        webdav_auto_strategy_display = {
            'smart_merge': '智能合并（优先上传本地）',
            'upload_only': '仅上传本地数据',
            'download_only': '仅下载远端数据',
        }
        webdav_auto_strategy_reverse = {label: key for key, label in webdav_auto_strategy_display.items()}
        webdav_auto_strategy_var = tk.StringVar(
            value=webdav_auto_strategy_display.get(
                self.config_mgr.get_setting('backup_webdav_auto_strategy', 'smart_merge'),
                '智能合并（优先上传本地）',
            )
        )

        header = tk.Frame(body, bg=COLORS['card_bg'])
        header.pack(fill=tk.X, padx=28, pady=(28, 18))

        tk.Label(
            header,
            text='纸研社设置中心',
            font=FONTS['title'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w')

        tab_row = tk.Frame(body, bg=COLORS['card_bg'])
        tab_row.pack(fill=tk.X, padx=28, pady=(0, 18))

        active_section = tk.StringVar(value='general')
        tab_buttons = {}
        section_pages = {}

        content_card = CardFrame(body, padding=22)
        content_card.pack(fill=tk.BOTH, expand=True, padx=28)

        content_view = ScrollablePage(content_card.inner, bg=COLORS['card_bg'])
        content_view.pack(fill=tk.BOTH, expand=True)
        content_host = content_view.inner

        for key in ('general', 'advanced', 'backup', 'about'):
            page = tk.Frame(content_host, bg=COLORS['card_bg'])
            section_pages[key] = page

        def refresh_settings_scroll():
            content_host.update_idletasks()
            content_view.update_idletasks()
            bbox = content_view.canvas.bbox('all')
            if bbox:
                content_view.canvas.configure(scrollregion=bbox)
            content_view.scroll_to_top()

        def switch_section(section_key):
            active_section.set(section_key)
            for key, button in tab_buttons.items():
                button.set_style('primary' if key == section_key else 'secondary')
            for key, page in section_pages.items():
                if key == section_key:
                    page.pack(fill=tk.BOTH, expand=True)
                else:
                    page.pack_forget()
            window.after_idle(refresh_settings_scroll)

        for key, label in (
            ('general', '通用'),
            ('advanced', '高级'),
            ('backup', '备份'),
            ('about', '关于'),
        ):
            button_shell, button = create_home_shell_button(
                tab_row,
                label,
                command=lambda current=key: switch_section(current),
                style='primary' if key == active_section.get() else 'secondary',
                font=FONTS['body_bold'],
                padx=30,
                pady=11,
            )
            button_shell.pack(side=tk.LEFT, padx=(0, 12))
            tab_buttons[key] = button

        def add_block(parent, title, description):
            shell = tk.Frame(parent, bg=COLORS['shadow'], bd=0, highlightthickness=0)
            shell.pack(fill=tk.X, pady=(0, 14))

            inner = tk.Frame(
                shell,
                bg=COLORS['card_bg'],
                highlightbackground=COLORS['card_border'],
                highlightthickness=1,
                bd=0,
            )
            inner.pack(fill=tk.X, padx=(0, 4), pady=(0, 4))

            tk.Label(
                inner,
                text=title,
                font=FONTS['body_bold'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
            ).pack(anchor='w', padx=16, pady=(14, 0))
            tk.Label(
                inner,
                text=description,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                justify='left',
                wraplength=1220,
            ).pack(anchor='w', padx=16, pady=(6, 0))

            control = tk.Frame(inner, bg=COLORS['card_bg'])
            control.pack(fill=tk.X, padx=16, pady=(12, 14))
            return control

        def add_toggle(parent, title, description, variable):
            shell = tk.Frame(parent, bg=COLORS['shadow'], bd=0, highlightthickness=0)
            shell.pack(fill=tk.X, pady=(0, 14))

            inner = tk.Frame(
                shell,
                bg=COLORS['card_bg'],
                highlightbackground=COLORS['card_border'],
                highlightthickness=1,
                bd=0,
            )
            inner.pack(fill=tk.X, padx=(0, 4), pady=(0, 4))
            inner.grid_columnconfigure(0, weight=1)

            text_col = tk.Frame(inner, bg=COLORS['card_bg'])
            text_col.grid(row=0, column=0, sticky='nsew', padx=(16, 20), pady=(14, 14))

            tk.Label(
                text_col,
                text=title,
                font=FONTS['body_bold'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
            ).pack(anchor='w')
            desc_label = tk.Label(
                text_col,
                text=description,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                justify='left',
                anchor='w',
            )
            desc_label.pack(fill=tk.X, pady=(6, 0))
            bind_adaptive_wrap(desc_label, text_col, padding=4, min_width=280)

            toggle_shell = tk.Frame(inner, bg='#000000', bd=0, highlightthickness=0)

            toggle = tk.Checkbutton(
                toggle_shell,
                variable=variable,
                indicatoron=False,
                relief=tk.FLAT,
                bd=0,
                cursor='hand2',
                font=FONTS['small'],
                padx=16,
                pady=9,
                highlightthickness=0,
                selectcolor=COLORS['accent'],
            )

            def refresh_toggle():
                active = bool(variable.get())
                toggle.configure(
                    text='已开启' if active else '已关闭',
                    bg=COLORS['accent'] if active else COLORS['surface_alt'],
                    fg=COLORS['text_main'] if active else COLORS['text_sub'],
                    activebackground=COLORS['accent'] if active else COLORS['surface_alt'],
                    activeforeground=COLORS['text_main'] if active else COLORS['text_sub'],
                )

            toggle.configure(command=refresh_toggle)
            refresh_toggle()
            toggle.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
            toggle_shell.grid(row=0, column=1, sticky='e', padx=(0, 16), pady=14)

        def add_select(parent, title, description, widget=None, *, textvariable=None, values=None, width=16):
            shell = tk.Frame(parent, bg=COLORS['shadow'], bd=0, highlightthickness=0)
            shell.pack(fill=tk.X, pady=(0, 14))

            inner = tk.Frame(
                shell,
                bg=COLORS['card_bg'],
                highlightbackground=COLORS['card_border'],
                highlightthickness=1,
                bd=0,
            )
            inner.pack(fill=tk.X, padx=(0, 4), pady=(0, 4))
            inner.grid_columnconfigure(0, weight=1)

            text_col = tk.Frame(inner, bg=COLORS['card_bg'])
            text_col.grid(row=0, column=0, sticky='nsew', padx=(16, 20), pady=(14, 14))

            tk.Label(
                text_col,
                text=title,
                font=FONTS['body_bold'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
            ).pack(anchor='w')
            desc_label = tk.Label(
                text_col,
                text=description,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                justify='left',
                anchor='w',
            )
            desc_label.pack(fill=tk.X, pady=(6, 0))
            bind_adaptive_wrap(desc_label, text_col, padding=4, min_width=280)

            style = 'Modern.TCombobox'
            state = 'readonly'

            if widget is not None:
                textvariable = widget.cget('textvariable')
                values = widget.cget('values')
                width = int(widget.cget('width') or width)
                style = widget.cget('style') or style
                state = widget.cget('state') or state
                try:
                    widget.destroy()
                except tk.TclError:
                    pass

            widget = ttk.Combobox(
                inner,
                textvariable=textvariable,
                values=values,
                style=style,
                width=width,
                state=state,
            )
            widget.grid(row=0, column=1, sticky='e', padx=(0, 16), pady=14)
            return widget

        def add_actions(
            parent,
            title,
            description,
            button_specs,
            note_text=None,
            note_color=None,
            use_home_button_border=False,
            inline_buttons=False,
        ):
            use_home_button_border = bool(use_home_button_border or parent in {advanced_page, about_page})
            if inline_buttons:
                shell = tk.Frame(parent, bg=COLORS['shadow'], bd=0, highlightthickness=0)
                shell.pack(fill=tk.X, pady=(0, 14))

                inner = tk.Frame(
                    shell,
                    bg=COLORS['card_bg'],
                    highlightbackground=COLORS['card_border'],
                    highlightthickness=1,
                    bd=0,
                )
                inner.pack(fill=tk.X, padx=(0, 4), pady=(0, 4))
                inner.grid_columnconfigure(0, weight=1)

                text_col = tk.Frame(inner, bg=COLORS['card_bg'])
                text_col.grid(row=0, column=0, sticky='nsew', padx=(16, 20), pady=(14, 14))

                tk.Label(
                    text_col,
                    text=title,
                    font=FONTS['body_bold'],
                    fg=COLORS['text_main'],
                    bg=COLORS['card_bg'],
                ).pack(anchor='w')
                desc_label = tk.Label(
                    text_col,
                    text=description,
                    font=FONTS['small'],
                    fg=COLORS['text_sub'],
                    bg=COLORS['card_bg'],
                    justify='left',
                    anchor='w',
                )
                desc_label.pack(fill=tk.X, pady=(6, 0))
                bind_adaptive_wrap(desc_label, text_col, padding=4, min_width=280)

                note_label = None
                if note_text is not None:
                    note_label = tk.Label(
                        text_col,
                        text=note_text,
                        font=FONTS['small'],
                        fg=note_color or COLORS['text_sub'],
                        bg=COLORS['card_bg'],
                        justify='left',
                        anchor='w',
                    )
                    note_label.pack(fill=tk.X, pady=(8, 0))
                    bind_adaptive_wrap(note_label, text_col, padding=4, min_width=280)

                button_row = tk.Frame(inner, bg=COLORS['card_bg'])
                button_row.grid(row=0, column=1, sticky='e', padx=(0, 16), pady=(14, 14))
            else:
                control = add_block(parent, title, description)
                note_label = None
                if note_text is not None:
                    note_label = tk.Label(
                        control,
                        text=note_text,
                        font=FONTS['small'],
                        fg=note_color or COLORS['text_sub'],
                        bg=COLORS['card_bg'],
                        justify='left',
                        wraplength=1220,
                    )
                    note_label.pack(anchor='w', pady=(0, 12))

                button_row = tk.Frame(control, bg=COLORS['card_bg'])
                button_row.pack(fill=tk.X)

            for index, spec in enumerate(button_specs):
                if use_home_button_border:
                    button_shell, button = create_home_shell_button(
                        button_row,
                        spec['text'],
                        command=spec['command'],
                        style=spec.get('style', 'secondary'),
                        font=FONTS['small'],
                        padx=12,
                        pady=7,
                    )
                    button_shell.pack(side=tk.LEFT, padx=(0, 10 if index < len(button_specs) - 1 else 0))
                    spec['widget'] = button
                    spec['shell'] = button_shell
                else:
                    button = ModernButton(
                        button_row,
                        spec['text'],
                        style=spec.get('style', 'secondary'),
                        command=spec['command'],
                        font=FONTS['small'],
                        padx=12,
                        pady=7,
                    )
                    button.pack(side=tk.LEFT, padx=(0, 10 if index < len(button_specs) - 1 else 0))
                    spec['widget'] = button
            return note_label, button_specs

        general_page = section_pages['general']
        advanced_page = section_pages['advanced']
        backup_page = section_pages['backup']
        about_page = section_pages['about']

        add_select(
            general_page,
            '主题模式',
            '保留原有主题设置，可在设置内直接切换浅色、深色或跟随系统。',
            textvariable=theme_var,
            values=list(theme_display.values()),
            width=16,
        )

        add_select(
            general_page,
            '默认启动页',
            '保留原有默认启动页设置，控制软件启动后的首个页面。',
            textvariable=startup_var,
            values=list(startup_display.values()),
            width=16,
        )

        add_toggle(general_page, '开机启动', '登录 Windows 后自动启动纸研社。保存设置后会同步当前用户的系统启动项。', launch_on_startup_var)
        add_toggle(general_page, '静默启动', '用于开机启动场景，启动后以较安静的最小化方式进入后台。', silent_startup_var)
        add_toggle(
            general_page,
            '最小化按钮进入托盘',
            '点击窗口最小化按钮时隐藏主窗口并驻留系统托盘；关闭后可从托盘恢复。',
            minimize_to_tray_on_minimize_var,
        )
        add_toggle(
            general_page,
            '关闭按钮进入托盘',
            '点击关闭按钮时不退出程序，改为最小化到系统托盘并继续后台驻留。',
            minimize_to_tray_on_close_var,
        )
        add_toggle(general_page, '首页统计面板', '保留原有首页统计显示偏好，可随时关闭或重新开启统计区。', home_stats_var)
        add_toggle(general_page, '加载动画', '保留原有 loading.gif 加载动画开关，控制异步操作的视觉反馈。', loading_var)
        add_select(
            general_page,
            '论文导入识别方式',
            '本地识别使用 Word 样式和格式信号解析大纲；AI识别会调用当前模型识别结构，但不会上传原始 DOCX 文件。',
            textvariable=import_recognition_var,
            values=list(import_recognition_display.values()),
            width=16,
        )

        model_test_shell = tk.Frame(advanced_page, bg=COLORS['shadow'], bd=0, highlightthickness=0)
        model_test_shell.pack(fill=tk.X, pady=(0, 14))

        model_test_card = tk.Frame(
            model_test_shell,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
            bd=0,
        )
        model_test_card.pack(fill=tk.X, padx=(0, 4), pady=(0, 4))

        tk.Label(
            model_test_card,
            text='模型测试配置（全局）',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w', padx=16, pady=(14, 0))
        tk.Label(
            model_test_card,
            text='这里配置模型配置中心测试连接时默认复用的提示词、超时与重试策略，模型本身仍以模型配置中心当前填写或选择的模型为准。',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='left',
            wraplength=1220,
        ).pack(anchor='w', padx=16, pady=(6, 0))

        model_form = tk.Frame(model_test_card, bg=COLORS['card_bg'])
        model_form.pack(fill=tk.X, padx=16, pady=(16, 12))
        model_form.grid_columnconfigure(1, weight=1)

        def add_test_row(row_index, label_text, variable, width=28, placeholder=''):
            tk.Label(
                model_form,
                text=label_text,
                font=FONTS['body'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
                anchor='w',
            ).grid(row=row_index, column=0, sticky='w', padx=(0, 22), pady=(0, 14))
            entry = ModernEntry(model_form, textvariable=variable, placeholder=placeholder, width=width)
            entry.grid(row=row_index, column=1, sticky='ew', pady=(0, 14), ipady=7)
            return entry

        add_test_row(0, '提示词', global_test_prompt_var, width=68)
        add_test_row(1, '超时（秒）', global_test_timeout_var, width=14)
        add_test_row(2, '降级阈值（毫秒）', global_test_degrade_var, width=14)
        add_test_row(3, '最大重试次数', global_test_retries_var, width=14)

        model_action_row = tk.Frame(model_test_card, bg=COLORS['card_bg'])
        model_action_row.pack(fill=tk.X, padx=16, pady=(0, 8))

        config_shell, _config_button = create_home_shell_button(
            model_action_row,
            '前往模型配置',
            command=lambda: [self._close_dialog(window), self._show_api_config_dialog()],
            style='secondary',
            font=FONTS['body_bold'],
            padx=22,
            pady=10,
        )
        config_shell.pack(side=tk.RIGHT)

        def parse_positive_number(text, fallback, cast_type=float, minimum=0):
            try:
                value = cast_type(text)
            except Exception:
                return fallback
            if value < minimum:
                return fallback
            return value

        def parse_optional_positive_float(text, fallback=1.0):
            raw = (text or '').strip()
            if not raw:
                return '', fallback, False

            try:
                value = float(raw)
            except Exception:
                return '', fallback, True

            if value <= 0:
                return '', fallback, True

            return f'{value:g}', value, False

        parameter_shell = tk.Frame(advanced_page, bg=COLORS['shadow'], bd=0, highlightthickness=0)
        parameter_shell.pack(fill=tk.X, pady=(0, 14))

        parameter_card = tk.Frame(
            parameter_shell,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
            bd=0,
        )
        parameter_card.pack(fill=tk.X, padx=(0, 4), pady=(0, 4))

        tk.Label(
            parameter_card,
            text='参数需求（全局）',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w', padx=16, pady=(14, 0))
        tk.Label(
            parameter_card,
            text='未启用模型单独参数时，请求会直接复用这里的默认参数；最大生成长度留空时不额外限制。',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='left',
            wraplength=1220,
        ).pack(anchor='w', padx=16, pady=(6, 0))

        parameter_grid = tk.Frame(parameter_card, bg=COLORS['card_bg'])
        parameter_grid.pack(fill=tk.X, padx=16, pady=(16, 12))
        parameter_grid.grid_columnconfigure(0, weight=1, uniform='global_params')
        parameter_grid.grid_columnconfigure(1, weight=1, uniform='global_params')

        def add_parameter_field(row_index, column_index, field_key, label_text, placeholder, note_text):
            column = tk.Frame(parameter_grid, bg=COLORS['card_bg'])
            padx = (0, 16) if column_index == 0 else (0, 0)
            column.grid(row=row_index, column=column_index, sticky='nsew', padx=padx, pady=(0, 14))

            tk.Label(
                column,
                text=label_text,
                font=FONTS['body_bold'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
            ).pack(anchor='w')
            entry = ModernEntry(
                column,
                textvariable=global_parameter_vars[field_key],
                placeholder=placeholder,
                width=34,
            )
            entry.pack(fill=tk.X, pady=(10, 0), ipady=9)
            note = tk.Label(
                column,
                text=note_text,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                justify='left',
                wraplength=540,
                anchor='w',
            )
            note.pack(fill=tk.X, pady=(8, 0))
            bind_adaptive_wrap(note, column, padding=4, min_width=300)

        add_parameter_field(0, 0, 'temperature', '温度', '留空使用服务商默认值', '适合按模型统一控制输出发散程度。')
        add_parameter_field(0, 1, 'max_tokens', '最大生成长度', '留空表示不限制', '长文本任务建议保持留空，只在确实需要上限时填写。')
        add_parameter_field(1, 0, 'timeout', '请求超时（秒）', '留空启用自动策略', '未填写时会根据提示词长度和生成规模自动放宽超时。')
        add_parameter_field(1, 1, 'top_p', '核采样', '留空使用服务商默认值', '仅对支持该参数的供应商生效。')
        add_parameter_field(2, 0, 'presence_penalty', '存在惩罚', '留空使用服务商默认值', '仅对支持该参数的供应商生效。')
        add_parameter_field(2, 1, 'frequency_penalty', '频率惩罚', '留空使用服务商默认值', '仅对支持该参数的供应商生效。')

        billing_shell = tk.Frame(advanced_page, bg=COLORS['shadow'], bd=0, highlightthickness=0)
        billing_shell.pack(fill=tk.X, pady=(0, 14))

        billing_card = tk.Frame(
            billing_shell,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
            bd=0,
        )
        billing_card.pack(fill=tk.X, padx=(0, 4), pady=(0, 4))

        tk.Label(
            billing_card,
            text='计费配置（全局）',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w', padx=16, pady=(14, 0))
        tk.Label(
            billing_card,
            text='为全局默认计费规则配置成本倍率和模型匹配方式，后续费用估算或供应商覆盖规则可直接复用这里的默认值。',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='left',
            wraplength=1220,
        ).pack(anchor='w', padx=16, pady=(6, 0))

        billing_grid = tk.Frame(billing_card, bg=COLORS['card_bg'])
        billing_grid.pack(fill=tk.X, padx=16, pady=(16, 12))
        billing_grid.grid_columnconfigure(0, weight=1, uniform='billing')
        billing_grid.grid_columnconfigure(1, weight=1, uniform='billing')

        billing_multiplier_col = tk.Frame(billing_grid, bg=COLORS['card_bg'])
        billing_multiplier_col.grid(row=0, column=0, sticky='nsew', padx=(0, 16))
        tk.Label(
            billing_multiplier_col,
            text='成本倍率',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w')
        billing_multiplier_entry = ModernEntry(
            billing_multiplier_col,
            placeholder='留空使用默认值（1）',
            width=36,
        )
        billing_multiplier_entry.pack(fill=tk.X, pady=(10, 0), ipady=9)
        if billing_settings['raw_multiplier']:
            billing_multiplier_entry.delete(0, tk.END)
            billing_multiplier_entry.insert(0, billing_settings['raw_multiplier'])
            billing_multiplier_entry.configure(fg=COLORS['text_main'])
            billing_multiplier_entry._placeholder_active = False
        billing_multiplier_note = tk.Label(
            billing_multiplier_col,
            text='实际成本 = 基础成本 × 倍率，支持小数如 1.5。',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='left',
            wraplength=640,
            anchor='w',
        )
        billing_multiplier_note.pack(fill=tk.X, pady=(10, 0))
        bind_adaptive_wrap(billing_multiplier_note, billing_multiplier_col, padding=4, min_width=360)

        billing_mode_col = tk.Frame(billing_grid, bg=COLORS['card_bg'])
        billing_mode_col.grid(row=0, column=1, sticky='nsew')
        tk.Label(
            billing_mode_col,
            text='计费模式',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w')
        billing_mode_combo = ttk.Combobox(
            billing_mode_col,
            textvariable=global_billing_mode_var,
            values=list(billing_mode_display.values()),
            style='Modern.TCombobox',
            state='readonly',
            width=28,
        )
        billing_mode_combo.pack(fill=tk.X, pady=(10, 0), ipady=7)
        tk.Label(
            billing_mode_col,
            text='选择按请求模型还是返回模型进行定价匹配。',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='left',
            wraplength=540,
        ).pack(anchor='w', pady=(10, 0))

        def clear_logs():
            removed = self._clear_directory_contents(self.logs_dir)
            self._write_app_log(f'已清理日志目录，移除 {removed} 项')
            messagebox.showinfo('日志管理', f'已清理 {removed} 项日志内容。', parent=window)

        def clear_temp():
            removed = self._clear_directory_contents(self.temp_dir)
            self._write_app_log(f'已清理临时目录，移除 {removed} 项')
            messagebox.showinfo('清理完成', f'已清理 {removed} 项临时内容。', parent=window)

        def change_config_directory():
            selected_dir = filedialog.askdirectory(
                parent=window,
                title='选择新的运行数据目录',
                initialdir=self.config_mgr.app_dir,
                mustexist=False,
            )
            if not selected_dir:
                return

            target_dir = os.path.abspath(selected_dir)
            current_dir = os.path.abspath(self.config_mgr.app_dir)
            if target_dir == current_dir:
                messagebox.showinfo('运行数据目录', '当前已经在该目录中。', parent=window)
                return

            try:
                new_path = self.config_mgr.switch_config_directory(target_dir)
                self.history_mgr.reload_data_directory()
                self._sync_runtime_paths()
            except Exception as exc:
                self._write_app_log(f'调整运行数据目录失败: {exc}', 'ERROR')
                messagebox.showerror('运行数据目录', f'调整失败：\n{exc}', parent=window)
                return

            self._write_app_log(
                f'运行数据目录已切换: {current_dir} -> {self.config_mgr.app_dir} '
                f'(logs={self.logs_dir}, temp={self.temp_dir})'
            )
            messagebox.showinfo(
                '运行数据目录',
                f'运行数据目录已切换到：\n{self.config_mgr.app_dir}\n\n当前配置文件：\n{new_path}',
                parent=window,
            )

        add_actions(
            advanced_page,
            '日志管理',
            f'应用日志统一保存在 logs 目录，当前日志文件：{os.path.basename(self.log_path)}。',
            [
                {'text': '打开日志目录', 'style': 'secondary', 'command': lambda: self._open_directory(self.logs_dir)},
                {'text': '清理日志', 'style': 'warning', 'command': clear_logs},
            ],
            inline_buttons=True,
        )

        add_actions(
            advanced_page,
            '运行数据目录',
            f'模型配置、历史记录、日志与临时目录统一使用同一目录，当前配置文件：{os.path.basename(self.config_mgr.config_path)}。',
            [
                {'text': '调整目录位置', 'style': 'secondary', 'command': change_config_directory},
                {'text': '打开当前目录', 'style': 'secondary', 'command': lambda: self._open_directory(self.config_mgr.app_dir)},
            ],
            inline_buttons=True,
        )

        add_actions(
            advanced_page,
            '清理临时文件',
            '清理纸研社运行期间生成的临时目录内容，不影响模型配置、历史记录与导出文件。',
            [
                {'text': '立即清理', 'style': 'danger', 'command': clear_temp},
                {'text': '打开'
                         '目录', 'style': 'secondary', 'command': lambda: self._open_directory(self.temp_dir)},
            ],
            inline_buttons=True,
        )

        backup_intro = tk.Label(
            backup_page,
            text='备份支持本地导入导出和 WebDAV 同步，可快速迁移当前设备的模型配置、历史记录与工作区状态。',
            justify='left',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
        )
        backup_intro.pack(anchor='w', pady=(0, 16))

        def run_in_background(job, success_message, *, done_callback=None):
            self._set_status('处理中，请稍候...', COLORS['warning'])

            def worker():
                error = None
                try:
                    result = job()
                except Exception as exc:
                    result = None
                    error = exc

                def finalize():
                    if error is not None:
                        self._set_status('操作失败', COLORS['error'])
                        messagebox.showerror('备份', str(error), parent=window)
                        return
                    self._set_status(success_message, COLORS['success'])
                    if done_callback:
                        done_callback(result)

                self.root.after(0, finalize)

            threading.Thread(target=worker, name='SettingsBackupAction', daemon=True).start()

        def export_local_backup():
            now = datetime.now().strftime('%Y%m%d_%H%M%S')
            save_path = filedialog.asksaveasfilename(
                parent=window,
                title='导出备份数据',
                defaultextension='.json',
                initialfile=f'paperlab_backup_{now}.json',
                filetypes=[('JSON 文件', '*.json')],
            )
            if not save_path:
                return

            def job():
                payload = self._build_local_backup_payload()
                with open(save_path, 'w', encoding='utf-8') as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                return save_path

            run_in_background(
                job,
                '导出完成',
                done_callback=lambda path: messagebox.showinfo('导出成功', f'备份已导出到：\n{path}', parent=window),
            )

        def import_local_backup():
            backup_path = filedialog.askopenfilename(
                parent=window,
                title='导入备份数据',
                filetypes=[('JSON 文件', '*.json')],
            )
            if not backup_path:
                return
            if not messagebox.askyesno(
                '导入确认',
                '导入会覆盖当前运行目录中的同名数据。\n建议先手动导出当前数据后再继续。\n\n是否继续导入？',
                parent=window,
            ):
                return

            def job():
                with open(backup_path, 'r', encoding='utf-8') as handle:
                    payload = json.load(handle)
                self._restore_runtime_from_payload(payload)
                return backup_path

            run_in_background(
                job,
                '导入完成',
                done_callback=lambda path: messagebox.showinfo(
                    '导入成功',
                    f'已从以下文件恢复数据：\n{path}\n\n建议重启应用以完整加载所有页面状态。',
                    parent=window,
                ),
            )

        add_actions(
            backup_page,
            '导入/导出',
            '将当前运行目录完整打包为 JSON 备份文件，支持跨设备一键恢复全部配置与文本数据。',
            [
                {'text': '导出', 'style': 'primary', 'command': export_local_backup},
                {'text': '导入', 'style': 'secondary', 'command': import_local_backup},
            ],
            note_text='导入会覆盖已有同名文件，建议先执行一次手动导出备份。',
            note_color=COLORS['warning'],
        )

        webdav_form_shell = tk.Frame(backup_page, bg=COLORS['shadow'], bd=0, highlightthickness=0)
        webdav_form_shell.pack(fill=tk.X, pady=(0, 14))
        webdav_form = tk.Frame(
            webdav_form_shell,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
            bd=0,
        )
        webdav_form.pack(fill=tk.X, padx=(0, 4), pady=(0, 4))
        tk.Label(
            webdav_form,
            text='WebDAV 同步',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w', padx=16, pady=(14, 0))
        tk.Label(
            webdav_form,
            text='配置 WebDAV 后可共享备份数据。支持连接测试、手动上传与下载恢复。',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='left',
            wraplength=1220,
        ).pack(anchor='w', padx=16, pady=(6, 0))

        webdav_grid = tk.Frame(webdav_form, bg=COLORS['card_bg'])
        webdav_grid.pack(fill=tk.X, padx=16, pady=(16, 8))
        webdav_grid.grid_columnconfigure(1, weight=1)
        webdav_grid.grid_columnconfigure(3, weight=1)

        tk.Label(webdav_grid, text='WebDAV 地址', font=FONTS['body'], fg=COLORS['text_main'], bg=COLORS['card_bg']).grid(
            row=0, column=0, sticky='w', padx=(0, 10), pady=(0, 12)
        )
        ModernEntry(webdav_grid, textvariable=webdav_url_var, width=90, placeholder='https://example.com/dav/').grid(
            row=0, column=1, columnspan=3, sticky='ew', pady=(0, 12), ipady=7
        )

        tk.Label(webdav_grid, text='用户名', font=FONTS['body'], fg=COLORS['text_main'], bg=COLORS['card_bg']).grid(
            row=1, column=0, sticky='w', padx=(0, 10), pady=(0, 12)
        )
        ModernEntry(webdav_grid, textvariable=webdav_username_var, width=36, placeholder='账号').grid(
            row=1, column=1, sticky='ew', padx=(0, 16), pady=(0, 12), ipady=7
        )

        tk.Label(webdav_grid, text='密码', font=FONTS['body'], fg=COLORS['text_main'], bg=COLORS['card_bg']).grid(
            row=1, column=2, sticky='w', padx=(0, 10), pady=(0, 12)
        )
        ModernEntry(webdav_grid, textvariable=webdav_password_var, width=36, placeholder='密码', show='*').grid(
            row=1, column=3, sticky='ew', pady=(0, 12), ipady=7
        )

        def current_webdav_settings():
            return {
                'url': (webdav_url_var.get() or '').strip(),
                'username': (webdav_username_var.get() or '').strip(),
                'password': webdav_password_var.get() or '',
            }

        def save_webdav_settings():
            self.config_mgr.set_setting('backup_webdav_url', (webdav_url_var.get() or '').strip())
            self.config_mgr.set_setting('backup_webdav_username', (webdav_username_var.get() or '').strip())
            self.config_mgr.set_setting('backup_webdav_password', webdav_password_var.get() or '')
            self.config_mgr.save()
            self._set_status('WebDAV 配置已保存', COLORS['success'])
            messagebox.showinfo('WebDAV', '配置已保存。', parent=window)

        def test_webdav_connection():
            run_in_background(
                lambda: self._webdav_test_connection(current_webdav_settings()),
                'WebDAV 连接正常',
                done_callback=lambda target: messagebox.showinfo('连接成功', f'连接地址可用：\n{target}', parent=window),
            )

        def upload_webdav_backup():
            run_in_background(
                lambda: self._upload_backup_to_webdav(current_webdav_settings()),
                'WebDAV 上传完成',
                done_callback=lambda target: messagebox.showinfo('上传成功', f'已上传到：\n{target}', parent=window),
            )

        def download_webdav_backup():
            if not messagebox.askyesno(
                '下载并导入确认',
                '该操作会从 WebDAV 下载备份并覆盖本地同名文件。\n建议先手动导出当前本地数据。\n\n是否继续？',
                parent=window,
            ):
                return
            run_in_background(
                lambda: self._download_backup_from_webdav(current_webdav_settings()),
                'WebDAV 导入完成',
                done_callback=lambda target: messagebox.showinfo(
                    '下载导入成功',
                    f'已从以下地址下载并恢复：\n{target}\n\n建议重启应用以完整加载恢复内容。',
                    parent=window,
                ),
            )

        webdav_action_row = tk.Frame(webdav_form, bg=COLORS['card_bg'])
        webdav_action_row.pack(fill=tk.X, padx=16, pady=(0, 14))
        webdav_buttons = [
            ('保存配置', 'primary', save_webdav_settings),
            ('测试连接', 'secondary', test_webdav_connection),
            ('上传同步数据', 'primary', upload_webdav_backup),
            ('下载并导入共享数据', 'secondary', download_webdav_backup),
        ]
        for idx, (text, style, command) in enumerate(webdav_buttons):
            shell, _button = create_home_shell_button(
                webdav_action_row,
                text,
                command=command,
                style=style,
                font=FONTS['small'],
                padx=12,
                pady=8,
            )
            shell.pack(side=tk.LEFT, padx=(0, 10 if idx < len(webdav_buttons) - 1 else 0))

        add_toggle(
            backup_page,
            'WebDAV 自动同步',
            '开启后按间隔在后台执行同步任务，可用于多设备快速保持配置一致。',
            webdav_auto_enabled_var,
        )
        add_select(
            backup_page,
            '同步间隔（秒）',
            '建议设置为 600 秒以上；过短间隔可能触发远端限流。',
            textvariable=webdav_auto_interval_var,
            values=('600', '1200', '1800', '3600', '7200'),
            width=12,
        )
        add_select(
            backup_page,
            '同步策略',
            '智能合并默认优先上传本地最新状态；也可切换成仅上传或仅下载。',
            textvariable=webdav_auto_strategy_var,
            values=list(webdav_auto_strategy_display.values()),
            width=28,
        )

        current_theme = theme_display.get(self.config_mgr.get_setting('theme_mode', 'light'), '浅色模式')
        current_page = startup_display.get(self.config_mgr.get_setting('startup_page', 'home'), '首页')
        tk.Label(
            about_page,
            text=f'{APP_NAME} {APP_VERSION}\n当前模型：{self._get_active_model_label()}\n当前主题：{current_theme}\n默认启动页：{current_page}',
            justify='left',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w', pady=(0, 16))

        version_button_specs = [
            {'text': '检查更新', 'style': 'primary', 'command': lambda: None},
        ]
        _version_note_label, version_button_specs = add_actions(
            about_page,
            '版本更新',
            '查看当前版本状态，并使用本地离线更新说明了解如何替换新版程序。',
            version_button_specs,
            inline_buttons=True,
        )
        check_update_button = version_button_specs[0].get('widget')
        if check_update_button is not None:
            check_update_button.configure(command=lambda current=check_update_button: self._check_version_update(current))

        add_actions(
            about_page,
            '品牌与帮助',
            '保留原有关于信息与帮助入口，便于查看教程、公告和当前运行说明。',
            [
                {'text': '系统公告', 'style': 'secondary', 'command': self._show_announcement},
                {'text': '使用教程', 'style': 'secondary', 'command': self._show_tutorial},
                {'text': '关于纸研社', 'style': 'secondary', 'command': self._show_about_dialog},
            ],
        )

        footer = tk.Frame(body, bg=COLORS['card_bg'])
        footer.pack(fill=tk.X, padx=28, pady=(18, 28))

        def save_settings():
            warnings = []
            theme_mode = theme_reverse.get(theme_var.get(), 'light')
            startup_page = startup_reverse.get(startup_var.get(), 'home')

            self.config_mgr.set_setting('theme_mode', theme_mode)
            self.config_mgr.set_setting('startup_page', startup_page)
            self.config_mgr.set_setting('show_home_stats', home_stats_var.get())
            self.config_mgr.set_setting('enable_loading_animation', loading_var.get())
            self.config_mgr.set_setting(
                'paper_write_import_recognition_mode',
                import_recognition_reverse.get(import_recognition_var.get(), 'local'),
            )
            self.config_mgr.set_setting('launch_on_startup', launch_on_startup_var.get())
            self.config_mgr.set_setting('silent_startup', silent_startup_var.get())
            self.config_mgr.set_setting('minimize_to_tray_on_minimize', minimize_to_tray_on_minimize_var.get())
            self.config_mgr.set_setting('minimize_to_tray_on_close', minimize_to_tray_on_close_var.get())
            self.config_mgr.set_setting('global_test_prompt', (global_test_prompt_var.get() or '').strip() or 'Who are you?')
            self.config_mgr.set_setting('global_test_timeout_sec', parse_positive_number(global_test_timeout_var.get(), 45.0, float, minimum=1.0))
            self.config_mgr.set_setting('global_test_degrade_ms', parse_positive_number(global_test_degrade_var.get(), 6000, int, minimum=0))
            self.config_mgr.set_setting('global_test_max_retries', parse_positive_number(global_test_retries_var.get(), 2, int, minimum=0))
            for field, variable in global_parameter_vars.items():
                self.config_mgr.set_setting(f'global_{field}', (variable.get() or '').strip())
            billing_multiplier_text, billing_multiplier_value, billing_multiplier_invalid = parse_optional_positive_float(
                billing_multiplier_entry.get_value(),
                fallback=1.0,
            )
            if billing_multiplier_invalid:
                warnings.append('计费配置中的成本倍率无效，已自动恢复为默认值 x1。')
            self.config_mgr.set_setting('global_billing_multiplier', billing_multiplier_text)
            self.config_mgr.set_setting('global_billing_mode', billing_mode_reverse.get(global_billing_mode_var.get(), 'request_model'))
            self.config_mgr.set_setting('backup_webdav_url', (webdav_url_var.get() or '').strip())
            self.config_mgr.set_setting('backup_webdav_username', (webdav_username_var.get() or '').strip())
            self.config_mgr.set_setting('backup_webdav_password', webdav_password_var.get() or '')
            self.config_mgr.set_setting('backup_webdav_auto_enabled', webdav_auto_enabled_var.get())
            self.config_mgr.set_setting(
                'backup_webdav_auto_interval_sec',
                parse_positive_number(webdav_auto_interval_var.get(), 3600, int, minimum=60),
            )
            self.config_mgr.set_setting(
                'backup_webdav_auto_strategy',
                webdav_auto_strategy_reverse.get(webdav_auto_strategy_var.get(), 'smart_merge'),
            )

            try:
                self._set_launch_on_startup(launch_on_startup_var.get(), silent=silent_startup_var.get())
            except Exception as exc:
                warnings.append(f'开机启动设置未能完全同步到系统：{exc}')

            self.config_mgr.save()
            self._schedule_webdav_auto_sync()
            self._apply_theme(theme_mode)

            if 'home' in self.pages and hasattr(self.pages['home'], 'refresh_dashboard'):
                self.pages['home'].refresh_dashboard()

            self._write_app_log(
                '设置已保存: '
                f'theme={theme_mode}, startup_page={startup_page}, launch_on_startup={launch_on_startup_var.get()}, '
                f'silent_startup={silent_startup_var.get()}, '
                f'minimize_to_tray_on_minimize={minimize_to_tray_on_minimize_var.get()}, '
                f'minimize_to_tray_on_close={minimize_to_tray_on_close_var.get()}, '
                f'paper_write_import_recognition_mode={import_recognition_reverse.get(import_recognition_var.get(), "local")}, '
                f'global_max_tokens={(global_parameter_vars["max_tokens"].get() or "").strip() or "-"}, '
                f'global_timeout={(global_parameter_vars["timeout"].get() or "").strip() or "-"}, '
                f'global_billing_multiplier={billing_multiplier_text or "1"}, '
                f'global_billing_mode={billing_mode_reverse.get(global_billing_mode_var.get(), "request_model")}, '
                f'webdav_auto_enabled={webdav_auto_enabled_var.get()}, '
                f'webdav_auto_interval={parse_positive_number(webdav_auto_interval_var.get(), 3600, int, minimum=60)}'
            )

            self._close_dialog(window)
            self._set_status('设置已保存')

            if warnings:
                messagebox.showwarning('部分设置需要处理', '\n'.join(warnings), parent=self.root)

        cancel_shell, _cancel_button = create_home_shell_button(
            footer,
            '取消',
            command=lambda: self._close_dialog(window),
            style='secondary',
            padx=22,
            pady=10,
            font=FONTS['body_bold'],
        )
        cancel_shell.pack(side=tk.RIGHT)
        save_shell, _save_button = create_home_shell_button(
            footer,
            '保存设置',
            command=save_settings,
            style='primary',
            padx=22,
            pady=10,
            font=FONTS['body_bold'],
        )
        save_shell.pack(side=tk.RIGHT, padx=(0, 12))

        switch_section(active_section.get())

    def _apply_dwm_titlebar_color(self, resolved_mode):
        """使用 DWM API 将系统标题栏颜色适配当前主题（Windows 10 1809+）。"""
        if sys.platform != 'win32':
            return
        if self._custom_window_chrome_enabled:
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if not hwnd:
                hwnd = self.root.winfo_id()
            # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (旧值 19 兼容 1809)
            dark = 1 if resolved_mode == 'dark' else 0
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(ctypes.c_int(dark)),
                ctypes.sizeof(ctypes.c_int),
            )
        except Exception:
            pass
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if not hwnd:
                hwnd = self.root.winfo_id()
            theme = THEMES.get(resolved_mode, THEMES['light'])
            nav_hex = theme.get('nav_bg', '#FFFFFF').lstrip('#')
            r, g, b = int(nav_hex[0:2], 16), int(nav_hex[2:4], 16), int(nav_hex[4:6], 16)
            # COLORREF: 0x00BBGGRR
            color_ref = ctypes.c_int(r | (g << 8) | (b << 16))
            DWMWA_CAPTION_COLOR = 35
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_CAPTION_COLOR,
                ctypes.byref(color_ref),
                ctypes.sizeof(color_ref),
            )
        except Exception:
            pass

    def _apply_theme(self, theme_mode, refresh=True):
        self._close_theme_menu()
        resolved, previous = set_theme_mode(theme_mode)
        self.config_mgr.set_setting('theme_mode', theme_mode)
        setup_styles(self.root)
        self.root.configure(bg=COLORS['bg_main'])
        self.root.after_idle(lambda m=resolved: self._apply_dwm_titlebar_color(m))

        if refresh:
            apply_theme_to_tree(self.root, previous)
            for dialog in list(self.dialogs):
                if dialog.winfo_exists():
                    dialog.configure(bg=COLORS['bg_main'])
                    apply_theme_to_tree(dialog, previous)
            self._refresh_shell_styles()
            if self.current_page_id and self.current_page_id in self.pages and hasattr(self.pages[self.current_page_id], 'on_show'):
                self.pages[self.current_page_id].on_show()

        self._set_status(f'主题已切换为{ {"light": "浅色模式", "dark": "深色模式"}.get(resolved, "浅色模式") }')
        self.config_mgr.save()

    def _refresh_shell_styles(self):
        self._refresh_window_chrome()

        for shell in self.nav_button_shells:
            shell.configure(bg=COLORS['nav_bg'])

        for border in self.nav_button_borders:
            border.configure(bg='#121317')

        self._refresh_top_nav_buttons()

        for shell in self.tool_button_shells:
            shell.configure(bg=COLORS['shadow'])
            self._refresh_top_tool_button(shell)

        for border in self.tool_button_borders:
            if border is not None:
                border.configure(bg=COLORS['card_border'])

        for button in self.tool_buttons:
            if hasattr(button, 'set_style'):
                self._refresh_top_tool_button(button)
            elif isinstance(button, tk.Canvas):
                self._render_top_tool_canvas(button)
            else:
                button.configure(bg=COLORS['toolbar_icon_bg'], fg=COLORS['toolbar_icon_fg'])
        bell_button = self._resolve_tool_button(getattr(self, 'bell_button', None))
        if bell_button is not None:
            self._refresh_top_tool_button(getattr(self, 'bell_button', None))

        if getattr(self, 'user_box', None):
            self.user_box.configure(bg=COLORS['shadow'])
            if getattr(self, 'user_inner', None):
                self.user_inner.configure(bg=COLORS['card_border'])
            if getattr(self, 'user_content', None):
                self.user_content.configure(bg=COLORS['card_bg'])
            if getattr(self, 'user_canvas', None):
                self.user_canvas.configure(bg=COLORS['card_bg'])
                self._render_user_profile_canvas(self.user_canvas)

        if hasattr(self, 'status_label'):
            self.status_label.configure(bg=COLORS['card_bg'], fg=COLORS['text_sub'])

    def run(self):
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        self.root.mainloop()

    def _on_close(self):
        if self._is_shutting_down:
            self._perform_exit()
            return

        if self.config_mgr and self.config_mgr.get_setting('minimize_to_tray_on_close', False):
            self._write_app_log('关闭主窗口时执行后台最小化')
            self._minimize_to_tray(reason='close_button')
            return

        self._perform_exit()

    def _perform_exit(self):
        self._is_shutting_down = True
        self._write_app_log('应用退出')
        if self.config_mgr:
            try:
                self._flush_page_workspace_states()
                state = self.root.state()
                # 如果窗口处于最小化状态，先恢复以获取正确位置
                if state == 'iconic' and self._window_restore_geometry:
                    geometry = self._window_restore_geometry
                elif self._window_is_maximized and self._window_restore_geometry:
                    geometry = self._window_restore_geometry
                elif state == 'normal':
                    geometry = self._capture_window_geometry()
                else:
                    geometry = self._window_restore_geometry or self._capture_window_geometry()
                if geometry:
                    self.config_mgr.set_setting('window_x', geometry['x'])
                    self.config_mgr.set_setting('window_y', geometry['y'])
                    self.config_mgr.set_setting('window_w', geometry['width'])
                    self.config_mgr.set_setting('window_h', geometry['height'])
            except Exception:
                pass
            self.config_mgr.save()
        self._stop_tray_icon()
        self._cancel_pending_after_jobs()
        self._restore_runtime_log_hooks()
        self._clear_runtime_log_file()
        self.root.destroy()


def main():
    app = SmartPaperTool()
    app.run()


if __name__ == '__main__':
    main()
