# -*- coding: utf-8 -*-
"""
UI组件模块 - 纸研社主题与公共控件
"""

import math
import os
import sys
import base64
import calendar
import ctypes
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from datetime import datetime

from modules.runtime_paths import get_runtime_paths

try:
    import winreg
except ImportError:
    winreg = None

try:
    from ctypes import wintypes
except ImportError:
    wintypes = None


THEMES = {
    'light': {
        'bg_main': '#E9F0FF',
        'sidebar': '#FFFDF8',
        'primary': '#2E61F2',
        'primary_light': '#FFF1A8',
        'primary_dark': '#2144B0',
        'accent': '#FFD84A',
        'accent_light': '#FFF5BF',
        'accent_soft': '#FFF9E0',
        'card_bg': '#FFFDF8',
        'card_border': '#121317',
        'text_main': '#15161A',
        'text_sub': '#5E6372',
        'text_muted': '#82889A',
        'success': '#2F9E44',
        'warning': '#E9A312',
        'error': '#D9485F',
        'info': '#2E61F2',
        'divider': '#E8DFCA',
        'input_bg': '#F5F7FE',
        'input_border': '#121317',
        'btn_hover': '#E7C13B',
        'tag_bg': '#F4F6FC',
        'tag_text': '#2E61F2',
        'nav_bg': '#E9F0FF',
        'nav_active': '#FFD84A',
        'panel_alt': '#F7F1E6',
        'surface_alt': '#F1F4FB',
        'shadow': '#121317',
        'hero_stripe_a': '#FFFDF8',
        'hero_stripe_b': '#F6F4EE',
        'pill_bg': '#F7F8FC',
        'pill_active_bg': '#17181D',
        'pill_active_fg': '#FFFFFF',
        'toolbar_icon_bg': '#FFFDF8',
        'toolbar_icon_fg': '#121317',
        'menu_bg': '#FFFDF8',
        'menu_fg': '#15161A',
    },
    'dark': {
        'bg_main': '#151824',
        'sidebar': '#1F2330',
        'primary': '#6F93FF',
        'primary_light': '#3A435C',
        'primary_dark': '#AFC2FF',
        'accent': '#FFD84A',
        'accent_light': '#5C4D1C',
        'accent_soft': '#3A3420',
        'card_bg': '#202636',
        'card_border': '#F7F0D8',
        'text_main': '#F8F4E8',
        'text_sub': '#C5CBE0',
        'text_muted': '#99A1BC',
        'success': '#64D98B',
        'warning': '#F2C94C',
        'error': '#FF7D8F',
        'info': '#8EB0FF',
        'divider': '#343C50',
        'input_bg': '#171C28',
        'input_border': '#F7F0D8',
        'btn_hover': '#FFE37B',
        'tag_bg': '#252C3E',
        'tag_text': '#AFC2FF',
        'nav_bg': '#151824',
        'nav_active': '#FFD84A',
        'panel_alt': '#262D3F',
        'surface_alt': '#1B2130',
        'shadow': '#07080B',
        'hero_stripe_a': '#202636',
        'hero_stripe_b': '#232B3C',
        'pill_bg': '#2A3042',
        'pill_active_bg': '#FFD84A',
        'pill_active_fg': '#121317',
        'toolbar_icon_bg': '#202636',
        'toolbar_icon_fg': '#F8F4E8',
        'menu_bg': '#202636',
        'menu_fg': '#F8F4E8',
    },
}

COLORS = THEMES['light'].copy()
_IMAGE_CACHE = {}
_GIF_FRAME_CACHE = {}
_FONT_MEASURE_CACHE = {}

UI_FONT_CANDIDATES = (
    'Microsoft YaHei UI',
    '微软雅黑',
    'Microsoft YaHei',
    'PingFang SC',
    'Segoe UI',
)
MONO_FONT_CANDIDATES = (
    'Cascadia Mono',
    'JetBrains Mono',
    'Consolas',
)

DEFAULT_FONT_SPECS = {
    'title': (20, 'bold'),
    'subtitle': (15, 'bold'),
    'heading': (13, 'bold'),
    'body': (11, 'normal'),
    'body_bold': (11, 'bold'),
    'small': (10, 'normal'),
    'tiny': (9, 'normal'),
    'nav': (12, 'bold'),
    'nav_active': (12, 'bold'),
    'mono': (11, 'normal'),
    'code': (10, 'normal'),
    'brand': (26, 'bold'),
    'hero': (28, 'bold'),
    'hero_sub': (12, 'normal'),
}
FONTS = {}

MONITOR_DEFAULTTONEAREST = 2
SPI_GETWORKAREA = 0x0030


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

THEME_OPTION_NAMES = (
    'bg',
    'fg',
    'activebackground',
    'activeforeground',
    'highlightbackground',
    'highlightcolor',
    'insertbackground',
    'selectbackground',
    'selectforeground',
    'disabledforeground',
    'readonlybackground',
)


def _pick_font_family(root, candidates, fallback='TkDefaultFont'):
    try:
        available = {name.lower(): name for name in tkfont.families(root)}
    except tk.TclError:
        available = {}

    for candidate in candidates:
        if candidate.lower() in available:
            return available[candidate.lower()]
    return fallback


def _font_tuple(family, size, weight='normal'):
    if weight == 'bold':
        return (family, size, 'bold')
    return (family, size)


FONTS.update(
    {
        key: _font_tuple(
            MONO_FONT_CANDIDATES[0] if key in {'mono', 'code'} else UI_FONT_CANDIDATES[0],
            size,
            weight,
        )
        for key, (size, weight) in DEFAULT_FONT_SPECS.items()
    }
)


def configure_fonts(root):
    """根据当前系统可用字体初始化全局字体配置。"""
    ui_family = _pick_font_family(root, UI_FONT_CANDIDATES, fallback='TkDefaultFont')
    mono_family = _pick_font_family(root, MONO_FONT_CANDIDATES, fallback='TkFixedFont')

    FONTS.clear()
    for key, (size, weight) in DEFAULT_FONT_SPECS.items():
        family = mono_family if key in {'mono', 'code'} else ui_family
        FONTS[key] = _font_tuple(family, size, weight)

    named_defaults = {
        'TkDefaultFont': (ui_family, 11, 'normal'),
        'TkTextFont': (ui_family, 11, 'normal'),
        'TkMenuFont': (ui_family, 11, 'normal'),
        'TkHeadingFont': (ui_family, 11, 'bold'),
        'TkCaptionFont': (ui_family, 11, 'normal'),
        'TkSmallCaptionFont': (ui_family, 10, 'normal'),
        'TkTooltipFont': (ui_family, 10, 'normal'),
        'TkIconFont': (ui_family, 11, 'normal'),
        'TkFixedFont': (mono_family, 11, 'normal'),
    }
    for font_name, (family, size, weight) in named_defaults.items():
        try:
            tkfont.nametofont(font_name, root=root).configure(
                family=family,
                size=size,
                weight=weight,
            )
        except tk.TclError:
            pass


def _iter_resource_base_dirs():
    """按优先级枚举资源根目录，兼容源码运行、单文件打包和外置资源目录。"""
    seen = set()
    runtime_paths = get_runtime_paths()
    candidates = [
        runtime_paths.resource_root,
        runtime_paths.app_root,
        os.getcwd(),
    ]

    for base_dir in candidates:
        if not base_dir:
            continue
        normalized = os.path.normpath(base_dir)
        if normalized in seen:
            continue
        seen.add(normalized)
        yield normalized


def _iter_resource_candidate_paths(filename):
    normalized_name = os.path.normpath(str(filename or '').strip())
    if not normalized_name:
        return
    if os.path.isabs(normalized_name):
        yield normalized_name
        return
    for base_dir in _iter_resource_base_dirs():
        yield os.path.normpath(os.path.join(base_dir, normalized_name))


def _build_missing_resource_error(filename):
    search_paths = list(_iter_resource_candidate_paths(filename))
    joined_paths = '\n'.join(search_paths)
    return FileNotFoundError(f'未找到资源文件：{filename}\n已检查路径：\n{joined_paths}')


def get_resource_path(filename):
    """获取实际存在的资源路径，找不到时返回首选候选路径。"""
    candidate_paths = list(_iter_resource_candidate_paths(filename))
    for candidate in candidate_paths:
        if os.path.exists(candidate):
            return candidate.replace('\\', '/')
    if candidate_paths:
        return candidate_paths[0].replace('\\', '/')
    return os.path.normpath(str(filename or '')).replace('\\', '/')


def _get_pillow_resample_filter(pil_image_module):
    resampling = getattr(pil_image_module, 'Resampling', pil_image_module)
    return getattr(resampling, 'LANCZOS', getattr(pil_image_module, 'LANCZOS', 1))


def parse_window_size(geometry, default_width=1200, default_height=900):
    """解析窗口尺寸字符串，仅保留宽高部分。"""
    if isinstance(geometry, (tuple, list)) and len(geometry) >= 2:
        try:
            return max(int(geometry[0]), 1), max(int(geometry[1]), 1)
        except Exception:
            return default_width, default_height

    text = str(geometry or '').strip().lower()
    if 'x' not in text:
        return default_width, default_height

    size_text = text.split('+', 1)[0]
    width_text, height_text = size_text.split('x', 1)
    try:
        width = max(int(width_text), 1)
        height = max(int(height_text), 1)
        return width, height
    except Exception:
        return default_width, default_height


def get_window_work_area(widget):
    """获取窗口所在显示器的可用工作区。"""
    if sys.platform == 'win32' and wintypes is not None and MONITORINFO is not None:
        try:
            hwnd = widget.winfo_id()
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
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()


def apply_adaptive_window_geometry(
    window,
    geometry,
    *,
    min_width=None,
    min_height=None,
    margin_x=96,
    margin_y=80,
):
    """按工作区约束窗口尺寸和位置，避免窗口超出常见屏幕。"""
    target_width, target_height = parse_window_size(geometry)
    work_x, work_y, work_width, work_height = get_window_work_area(window)
    safe_width = max(1, int(work_width) - int(margin_x))
    safe_height = max(1, int(work_height) - int(margin_y))
    width = min(max(int(target_width), 1), safe_width)
    height = min(max(int(target_height), 1), safe_height)

    if min_width is not None or min_height is not None:
        applied_min_width = min(width, max(int(min_width or 1), 1))
        applied_min_height = min(height, max(int(min_height or 1), 1))
        window.minsize(applied_min_width, applied_min_height)

    x = int(work_x) + max(0, (int(work_width) - width) // 2)
    y = int(work_y) + max(0, (int(work_height) - height) // 2)
    window.geometry(f'{width}x{height}+{x}+{y}')
    return {
        'x': x,
        'y': y,
        'width': width,
        'height': height,
    }


def load_image(filename, max_size=None):
    """加载静态图片，并在需要时按比例缩小。"""
    path = get_resource_path(filename)
    size_key = tuple(max_size) if max_size else None
    cache_key = (os.path.abspath(path), size_key)
    cached = _IMAGE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if not os.path.exists(path):
        raise _build_missing_resource_error(filename)

    pil_error = None
    try:
        from PIL import Image as _PILImage
        from PIL import ImageTk as _ImageTk

        with _PILImage.open(path) as source:
            image = source.convert('RGBA')
            if max_size:
                image.thumbnail(max_size, _get_pillow_resample_filter(_PILImage))
            photo = _ImageTk.PhotoImage(image)
            _IMAGE_CACHE[cache_key] = photo
            return photo
    except Exception as exc:
        pil_error = exc

    with open(path, 'rb') as file_obj:
        raw = base64.b64encode(file_obj.read()).decode('ascii')
    try:
        image = tk.PhotoImage(data=raw)
    except tk.TclError as exc:
        if pil_error is not None:
            raise RuntimeError(f'图像资源加载失败：{filename}；Pillow 错误：{pil_error}；Tk 错误：{exc}') from exc
        raise
    if max_size:
        w_limit, h_limit = max_size
        factor = max(
            1,
            math.ceil(image.width() / max(w_limit, 1)),
            math.ceil(image.height() / max(h_limit, 1)),
        )
        if factor > 1:
            image = image.subsample(factor, factor)
    _IMAGE_CACHE[cache_key] = image
    return image


def load_gif_frames(filename, max_size=None):
    """读取GIF帧及每帧延迟，用于加载动画。
    返回 (frames, delays) 两个列表，delays 单位为毫秒。
    """
    path = get_resource_path(filename)
    size_key = tuple(max_size) if max_size else None
    cache_key = (os.path.abspath(path), size_key)
    cached = _GIF_FRAME_CACHE.get(cache_key)
    if cached is not None:
        frames, delays = cached
        return list(frames), list(delays)
    if not os.path.exists(path):
        raise _build_missing_resource_error(filename)

    delays = []
    try:
        from PIL import Image as _PILImage
        with _PILImage.open(path) as _im:
            try:
                while True:
                    delays.append(max(_im.info.get('duration', 33), 10))
                    _im.seek(_im.tell() + 1)
            except EOFError:
                pass
    except Exception:
        delays = []

    with open(path, 'rb') as file_obj:
        raw = base64.b64encode(file_obj.read()).decode('ascii')
    frames = []
    index = 0

    while True:
        try:
            frame = tk.PhotoImage(data=raw, format=f'gif -index {index}')
        except tk.TclError:
            break

        if max_size:
            w_limit, h_limit = max_size
            factor = max(
                1,
                math.ceil(frame.width() / max(w_limit, 1)),
                math.ceil(frame.height() / max(h_limit, 1)),
            )
            if factor > 1:
                frame = frame.subsample(factor, factor)
        frames.append(frame)
        index += 1

    if not frames:
        frames.append(tk.PhotoImage(data=raw))
        delays = [100]

    if len(delays) != len(frames):
        delays = [33] * len(frames)

    cached_value = (tuple(frames), tuple(delays))
    _GIF_FRAME_CACHE[cache_key] = cached_value
    return list(cached_value[0]), list(cached_value[1])


def get_system_theme():
    """读取系统主题（Windows / macOS / Linux），失败时回退浅色。"""
    if sys.platform == 'win32' and winreg:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize'
            )
            value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
            winreg.CloseKey(key)
            return 'light' if value else 'dark'
        except Exception:
            return 'light'

    if sys.platform == 'darwin':
        try:
            import subprocess
            result = subprocess.run(
                ['defaults', 'read', '-g', 'AppleInterfaceStyle'],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0 and 'dark' in result.stdout.strip().lower():
                return 'dark'
        except Exception:
            pass
        return 'light'

    # Linux: check common desktop environment settings
    if sys.platform.startswith('linux'):
        try:
            import subprocess
            result = subprocess.run(
                ['gsettings', 'get', 'org.gnome.desktop.interface', 'color-scheme'],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0 and 'dark' in result.stdout.strip().lower():
                return 'dark'
        except Exception:
            pass
        try:
            import subprocess
            result = subprocess.run(
                ['gsettings', 'get', 'org.gnome.desktop.interface', 'gtk-theme'],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0 and 'dark' in result.stdout.strip().lower():
                return 'dark'
        except Exception:
            pass
        return 'light'

    return 'light'


def resolve_theme_mode(mode):
    if mode == 'follow_system':
        return get_system_theme()
    if mode in THEMES:
        return mode
    return 'light'


def set_theme_mode(mode):
    """切换主题，返回(生效主题, 旧配色拷贝)。"""
    previous = COLORS.copy()
    resolved = resolve_theme_mode(mode)
    COLORS.clear()
    COLORS.update(THEMES[resolved])
    return resolved, previous


def setup_styles(root):
    """配置ttk样式。"""
    style = ttk.Style(root)
    style.theme_use('clam')
    body_font = tkfont.Font(root=root, font=FONTS['body'])
    treeview_rowheight = max(30, body_font.metrics('linespace') + 12)

    root.option_add('*Font', FONTS['body'])
    root.option_add('*Menu.font', FONTS['body'])
    root.option_add('*TCombobox*Listbox.background', COLORS['card_bg'])
    root.option_add('*TCombobox*Listbox.foreground', COLORS['text_main'])
    root.option_add('*TCombobox*Listbox.font', FONTS['body'])
    root.option_add('*TCombobox*Listbox.selectBackground', COLORS['accent'])
    root.option_add('*TCombobox*Listbox.selectForeground', COLORS['text_main'])

    style.configure(
        'Card.TNotebook',
        background=COLORS['bg_main'],
        borderwidth=0,
        tabmargins=[0, 0, 0, 0],
    )
    style.configure(
        'Card.TNotebook.Tab',
        background=COLORS['card_bg'],
        foreground=COLORS['text_sub'],
        borderwidth=3,
        relief='flat',
        padding=[14, 8],
        font=FONTS['body_bold'],
    )
    style.map(
        'Card.TNotebook.Tab',
        background=[('selected', COLORS['accent']), ('active', COLORS['accent_light'])],
        foreground=[('selected', COLORS['text_main']), ('active', COLORS['text_main'])],
    )

    style.configure(
        'Primary.Horizontal.TProgressbar',
        background=COLORS['accent'],
        troughcolor=COLORS['surface_alt'],
        bordercolor=COLORS['card_border'],
        lightcolor=COLORS['accent'],
        darkcolor=COLORS['accent'],
        thickness=8,
    )

    style.configure(
        'Thin.Vertical.TScrollbar',
        background=COLORS['card_border'],
        troughcolor=COLORS['surface_alt'],
        bordercolor=COLORS['card_border'],
        arrowcolor=COLORS['text_main'],
        width=12,
    )
    style.configure(
        'Thin.Horizontal.TScrollbar',
        background=COLORS['card_border'],
        troughcolor=COLORS['surface_alt'],
        bordercolor=COLORS['card_border'],
        arrowcolor=COLORS['text_main'],
        width=12,
    )

    style.configure(
        'Modern.TCombobox',
        background=COLORS['input_bg'],
        fieldbackground=COLORS['input_bg'],
        foreground=COLORS['text_main'],
        arrowcolor=COLORS['text_main'],
        bordercolor=COLORS['input_border'],
        lightcolor=COLORS['input_border'],
        darkcolor=COLORS['input_border'],
        padding=6,
    )

    style.map(
        'Modern.TCombobox',
        fieldbackground=[('readonly', COLORS['input_bg'])],
        foreground=[('readonly', COLORS['text_main'])],
        selectbackground=[('readonly', COLORS['accent'])],
        selectforeground=[('readonly', COLORS['text_main'])],
    )

    style.configure(
        'Treeview',
        background=COLORS['card_bg'],
        foreground=COLORS['text_main'],
        fieldbackground=COLORS['card_bg'],
        bordercolor=COLORS['card_border'],
        rowheight=treeview_rowheight,
        relief='flat',
        font=FONTS['body'],
    )
    style.configure(
        'Treeview.Heading',
        background=COLORS['accent'],
        foreground=COLORS['text_main'],
        borderwidth=2,
        relief='flat',
        font=FONTS['body_bold'],
    )
    style.map(
        'Treeview',
        background=[('selected', COLORS['primary']), ('!selected', COLORS['card_bg'])],
        foreground=[('selected', '#FFFFFF'), ('!selected', COLORS['text_main'])],
    )

    style.configure('Divider.TSeparator', background=COLORS['divider'])


def apply_theme_to_tree(widget, previous_colors=None):
    """递归替换控件使用过的主题颜色。"""
    mapping = {}
    if previous_colors:
        for key, old_value in previous_colors.items():
            new_value = COLORS.get(key)
            if isinstance(old_value, str) and old_value.startswith('#') and isinstance(new_value, str):
                mapping[old_value.lower()] = new_value

    def recolor(current):
        try:
            for option in THEME_OPTION_NAMES:
                try:
                    value = current.cget(option)
                except tk.TclError:
                    continue
                if isinstance(value, str):
                    replacement = mapping.get(value.lower())
                    if replacement and replacement != value:
                        try:
                            current.configure(**{option: replacement})
                        except tk.TclError:
                            pass
        except tk.TclError:
            pass

        border_key = getattr(current, '_home_shell_border_key', None)
        border_color = COLORS.get(border_key) if border_key else getattr(current, '_home_shell_border_color', None)
        if border_color:
            try:
                current.configure(bg=border_color)
            except tk.TclError:
                pass

        if hasattr(current, 'set_style') and hasattr(current, 'style_name'):
            try:
                current.set_style(current.style_name)
            except tk.TclError:
                pass

        for child in current.winfo_children():
            recolor(child)

    recolor(widget)


def _resolve_selector_soft_color(accent_key):
    guessed_key = f'{accent_key}_light'
    if guessed_key in COLORS:
        return COLORS[guessed_key]
    if accent_key == 'accent':
        return COLORS['accent_light']
    return COLORS['primary_light']


def create_tooltip_icon_label(
    parent,
    tooltip_text,
    *,
    bg,
    image_path='png/Tip.png',
    max_size=(16, 16),
    padx=10,
    pady=10,
):
    icon_widget = None
    tooltip_text = (tooltip_text or '').strip()
    if image_path:
        try:
            icon_image = load_image(image_path, max_size=max_size)
            icon_widget = tk.Label(
                parent,
                image=icon_image,
                bg=bg,
                cursor='hand2',
                padx=padx,
                pady=pady,
            )
            icon_widget.image = icon_image
        except Exception:
            icon_widget = None
    if icon_widget is None:
        icon_widget = tk.Label(
            parent,
            text='?',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=bg,
            cursor='hand2',
            padx=padx,
            pady=pady,
        )
    if tooltip_text:
        show_tooltip(
            icon_widget,
            tooltip_text,
            placement='top_center',
            y_offset=10,
            wraplength=240,
        )
    return icon_widget


def create_home_shell_button(
    parent,
    text,
    *,
    command,
    style='secondary',
    padx=18,
    pady=6,
    font=None,
    border_color=None,
    **button_kwargs,
):
    """创建与首页“系统公告”同款的外壳按钮。"""

    shell_border_key = None
    if border_color is None:
        shell_border_key = 'card_border'
        border_color = COLORS[shell_border_key]
    shell = tk.Frame(parent, bg=border_color, bd=0, highlightthickness=0)
    button = ModernButton(
        shell,
        text,
        style=style,
        command=command,
        padx=padx,
        pady=pady,
        font=font or FONTS['body_bold'],
        highlightthickness=0,
        **button_kwargs,
    )
    button.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
    shell._home_shell_border_key = shell_border_key
    shell._home_shell_border_color = None if shell_border_key else border_color
    shell._home_shell_button = button
    button._home_shell = shell
    return shell, button


def refresh_home_shell_button(shell, button=None):
    if shell is None:
        return

    target_button = button or getattr(shell, '_home_shell_button', None)
    border_key = getattr(shell, '_home_shell_border_key', None)
    border_color = COLORS.get(border_key) if border_key else getattr(shell, '_home_shell_border_color', None)

    if border_color:
        try:
            shell.configure(bg=border_color)
        except tk.TclError:
            pass

    if target_button is not None and hasattr(target_button, 'set_style'):
        try:
            target_button.set_style(target_button.style_name)
        except tk.TclError:
            pass


def create_selector_card(
    parent,
    *,
    variable,
    value,
    label,
    tooltip_text='',
    accent_key='primary',
    width=220,
    height=76,
    tooltip_image_path='png/Tip.png',
):
    """创建统一的模式选择卡片，保留左侧单选框并用背景色表达选中态。"""

    shell = tk.Frame(
        parent,
        bg=COLORS['shadow'],
        bd=0,
        highlightthickness=0,
        width=width,
        height=height,
    )
    shell.pack_propagate(False)

    card_frame = tk.Frame(
        shell,
        bg=COLORS['surface_alt'],
        highlightbackground=COLORS['card_border'],
        highlightthickness=2,
        bd=0,
    )
    card_frame.pack(fill=tk.BOTH, expand=True, padx=(0, 6), pady=(0, 6))
    card_frame.pack_propagate(False)

    accent_strip = tk.Frame(card_frame, bg=COLORS['divider'], height=6)
    accent_strip.pack(fill=tk.X)

    content_row = tk.Frame(card_frame, bg=COLORS['surface_alt'])
    content_row.pack(fill=tk.BOTH, expand=True)

    radio = tk.Radiobutton(
        content_row,
        text=label,
        variable=variable,
        value=value,
        indicatoron=True,
        relief=tk.FLAT,
        overrelief=tk.FLAT,
        bd=0,
        highlightthickness=0,
        font=FONTS['body_bold'],
        fg=COLORS['text_main'],
        bg=COLORS['surface_alt'],
        selectcolor=COLORS['surface_alt'],
        activebackground=COLORS['surface_alt'],
        activeforeground=COLORS['text_main'],
        anchor='w',
        justify='left',
        cursor='hand2',
        padx=12,
        pady=12,
    )
    radio.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    info_badge = create_tooltip_icon_label(
        content_row,
        tooltip_text,
        bg=COLORS['surface_alt'],
        image_path=tooltip_image_path,
        max_size=(16, 16),
        padx=10,
        pady=12,
    )
    info_badge.pack(side=tk.RIGHT, padx=(0, 6))

    def choose_option(_event=None, selected=value):
        variable.set(selected)

    for widget in (shell, card_frame, accent_strip, content_row, info_badge):
        widget.bind('<Button-1>', choose_option, add='+')

    return {
        'shell': shell,
        'card_frame': card_frame,
        'accent_strip': accent_strip,
        'content_row': content_row,
        'radio': radio,
        'info_badge': info_badge,
        'value': value,
        'accent_key': accent_key,
    }


def style_selector_card(card, *, selected):
    accent_key = card.get('accent_key', 'primary')
    soft_color = _resolve_selector_soft_color(accent_key)
    shell_bg = COLORS['shadow']
    body_bg = soft_color if selected else COLORS['surface_alt']
    strip_bg = COLORS['divider']
    border_color = COLORS['card_border']

    shell = card['shell']
    card_frame = card['card_frame']
    accent_strip = card['accent_strip']
    content_row = card['content_row']
    radio = card['radio']
    info_badge = card.get('info_badge')

    shell.configure(bg=shell_bg)
    card_frame.configure(bg=body_bg, highlightbackground=border_color, highlightthickness=2)
    accent_strip.configure(bg=strip_bg)
    content_row.configure(bg=body_bg)
    radio.configure(
        bg=body_bg,
        fg=COLORS['text_main'],
        activebackground=body_bg,
        activeforeground=COLORS['text_main'],
        selectcolor=body_bg,
        highlightbackground=body_bg,
    )
    if info_badge is not None:
        info_badge.configure(bg=body_bg)
        if info_badge.cget('text'):
            info_badge.configure(fg=COLORS['text_main'] if selected else COLORS['text_sub'])


class CardFrame(tk.Frame):
    """带描边和投影的面板。"""

    def __init__(self, parent, title=None, padding=18, **kwargs):
        kwargs.setdefault('bg', COLORS['shadow'])
        kwargs.setdefault('bd', 0)
        kwargs.setdefault('highlightthickness', 0)
        super().__init__(parent, **kwargs)

        self.body = tk.Frame(
            self,
            bg=COLORS['card_bg'],
            bd=0,
            highlightbackground=COLORS['card_border'],
            highlightthickness=3,
        )
        self.body.pack(fill=tk.BOTH, expand=True, padx=(0, 6), pady=(0, 6))
        self.title_frame = None
        self.title_label = None

        if title:
            self.title_frame = tk.Frame(self.body, bg=COLORS['card_bg'])
            self.title_frame.pack(fill=tk.X, padx=padding, pady=(padding, 0))
            self.title_frame.grid_columnconfigure(0, weight=0)
            self.title_frame.grid_columnconfigure(1, weight=1)
            self.title_label = tk.Label(
                self.title_frame,
                text=title,
                font=FONTS['heading'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
            )
            self.title_label.grid(row=0, column=0, sticky='w')

        self.inner = tk.Frame(self.body, bg=COLORS['card_bg'])
        top_pad = padding if title else padding
        self.inner.pack(fill=tk.BOTH, expand=True, padx=padding, pady=(top_pad, padding))


def _run_resize_batch(root):
    state = getattr(root, '_ui_resize_batch_state', None)
    if not isinstance(state, dict):
        return
    state['job'] = None
    if state.get('running'):
        return
    state['running'] = True
    try:
        rounds = 0
        while state.get('callbacks') and rounds < 6:
            callbacks = list(state.get('callbacks', {}).values())
            state['callbacks'].clear()
            for callback in callbacks:
                try:
                    callback()
                except tk.TclError:
                    continue
            rounds += 1
    finally:
        state['running'] = False

    if state.get('callbacks') and state.get('job') is None:
        try:
            state['job'] = root.after(16, lambda current_root=root: _run_resize_batch(current_root))
        except tk.TclError:
            state['job'] = None


def _schedule_resize_batch(widget, key, callback, delay_ms=16):
    try:
        root = widget.winfo_toplevel()
    except tk.TclError:
        return

    state = getattr(root, '_ui_resize_batch_state', None)
    if not isinstance(state, dict):
        state = {'job': None, 'callbacks': {}, 'running': False}
        setattr(root, '_ui_resize_batch_state', state)

    state['callbacks'][key] = callback
    if state.get('running') or state.get('job') is not None:
        return
    try:
        state['job'] = root.after(delay_ms, lambda current_root=root: _run_resize_batch(current_root))
    except tk.TclError:
        state['job'] = None


class ScrollablePage(tk.Frame):
    """主内容区域滚动容器。"""

    def __init__(self, parent, bg=None, **kwargs):
        kwargs.setdefault('bg', bg or COLORS['bg_main'])
        kwargs.setdefault('bd', 0)
        kwargs.setdefault('highlightthickness', 0)
        super().__init__(parent, **kwargs)

        self.canvas = tk.Canvas(
            self,
            bg=self.cget('bg'),
            bd=0,
            highlightthickness=0,
        )
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._pending_canvas_width = None

        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview, style='Thin.Vertical.TScrollbar')
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.scrollbar.pack_forget()
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.inner = tk.Frame(self.canvas, bg=self.cget('bg'))
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')

        self.canvas.bind('<Configure>', self._on_canvas_configure)
        self.inner.bind('<Configure>', self._on_inner_configure)

        # 鼠标进入/离开整个滚动区域时，在根窗口级别绑定/解绑滚轮，
        # 确保悬停在任意子控件上都能触发滚动。
        self.bind('<Enter>', self._on_enter_scroll_area, add='+')
        self.bind('<Leave>', self._on_leave_scroll_area, add='+')
        self.canvas.bind('<Enter>', self._on_enter_scroll_area, add='+')
        self.canvas.bind('<Leave>', self._on_leave_scroll_area, add='+')

    def _contains_widget(self, widget):
        current = widget
        while current is not None:
            if current is self:
                return True
            try:
                parent_name = current.winfo_parent()
            except tk.TclError:
                return False
            if not parent_name:
                return False
            try:
                current = current.nametowidget(parent_name)
            except (KeyError, tk.TclError):
                return False
        return False

    def _pointer_in_scroll_area(self):
        try:
            x, y = self.winfo_pointerxy()
            widget = self.winfo_containing(x, y)
        except tk.TclError:
            return False
        if widget is None:
            return False
        return self._contains_widget(widget)

    def _on_enter_scroll_area(self, _event=None):
        try:
            root = self.winfo_toplevel()
            root.bind_all('<MouseWheel>', self._on_mousewheel)
            root.bind_all('<Button-4>', self._on_mousewheel)
            root.bind_all('<Button-5>', self._on_mousewheel)
        except tk.TclError:
            pass

    def _on_leave_scroll_area(self, _event=None):
        try:
            # 只有真正离开整个组件区域时才解绑
            x, y = self.winfo_pointerxy()
            widget = self.winfo_containing(x, y)
            if widget and (widget is self or str(widget).startswith(str(self))):
                return
            root = self.winfo_toplevel()
            root.unbind_all('<MouseWheel>')
            root.unbind_all('<Button-4>')
            root.unbind_all('<Button-5>')
        except tk.TclError:
            pass

    def _on_mousewheel(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, 'units')
        elif event.num == 5:
            self.canvas.yview_scroll(1, 'units')
        else:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')

    def _on_canvas_configure(self, event):
        self._pending_canvas_width = max(int(getattr(event, 'width', 0) or 0), 0)
        self._schedule_layout_refresh()

    def _on_inner_configure(self, _event=None):
        self._schedule_layout_refresh()

    def _schedule_layout_refresh(self, delay_ms=16):
        _schedule_resize_batch(
            self,
            ('scrollable_page_layout', str(self)),
            self._apply_layout_refresh,
            delay_ms=delay_ms,
        )

    def _apply_layout_refresh(self):
        try:
            width = max(int(self._pending_canvas_width or 0), self.canvas.winfo_width(), 1)
            self.canvas.itemconfigure(self.window_id, width=width)
            bbox = self.canvas.bbox('all')
            self.canvas.configure(scrollregion=bbox or (0, 0, width, max(self.inner.winfo_reqheight(), 1)))
        except tk.TclError:
            return
        self._pending_canvas_width = None

    def scroll_to_top(self):
        self.canvas.yview_moveto(0)

    def _pointer_in_scroll_area(self):
        try:
            x, y = self.winfo_pointerxy()
            widget = self.winfo_containing(x, y)
        except tk.TclError:
            return False
        if widget is None:
            return False
        current = widget
        while current is not None:
            if current is self:
                return True
            try:
                parent_name = current.winfo_parent()
            except tk.TclError:
                return False
            if not parent_name:
                return False
            try:
                current = current.nametowidget(parent_name)
            except (KeyError, tk.TclError):
                return False
        return False

    def _on_leave_scroll_area(self, _event=None):
        try:
            if self._pointer_in_scroll_area():
                return
            root = self.winfo_toplevel()
            root.unbind_all('<MouseWheel>')
            root.unbind_all('<Button-4>')
            root.unbind_all('<Button-5>')
        except tk.TclError:
            pass

    def _on_mousewheel(self, event):
        if not self._pointer_in_scroll_area():
            return 'break'
        if event.num == 4:
            self.canvas.yview_scroll(-1, 'units')
        elif event.num == 5:
            self.canvas.yview_scroll(1, 'units')
        else:
            delta = int(-1 * (event.delta / 120))
            if delta == 0 and event.delta:
                delta = -1 if event.delta > 0 else 1
            if delta:
                self.canvas.yview_scroll(delta, 'units')
        return 'break'


def bind_combobox_dropdown_mousewheel(combo):
    """为 Combobox 下拉列表绑定独立滚轮，避免事件继续传递到外层页面。"""
    if not isinstance(combo, ttk.Combobox):
        return

    pending_job = {'id': None}

    def _locate_listbox():
        try:
            popdown = combo.tk.eval(f'ttk::combobox::PopdownWindow {combo}')
        except tk.TclError:
            return None

        if not popdown:
            return None

        for child_name in (f'{popdown}.f.l', f'{popdown}.l'):
            try:
                return combo.nametowidget(child_name)
            except (KeyError, tk.TclError):
                continue
        return None

    def _on_listbox_mousewheel(event):
        listbox = event.widget
        if event.num == 4:
            listbox.yview_scroll(-1, 'units')
        elif event.num == 5:
            listbox.yview_scroll(1, 'units')
        else:
            delta = int(-1 * (event.delta / 120))
            if delta == 0 and event.delta:
                delta = -1 if event.delta > 0 else 1
            if delta:
                listbox.yview_scroll(delta, 'units')
        return 'break'

    def _cancel_pending_job():
        job_id = pending_job.get('id')
        if not job_id:
            return
        try:
            combo.after_cancel(job_id)
        except tk.TclError:
            pass
        pending_job['id'] = None

    def _ensure_binding(attempt=0):
        listbox = _locate_listbox()
        if listbox is not None:
            if not getattr(listbox, '_mousewheel_bound_for_combobox', False):
                listbox.bind('<MouseWheel>', _on_listbox_mousewheel, add='+')
                listbox.bind('<Button-4>', _on_listbox_mousewheel, add='+')
                listbox.bind('<Button-5>', _on_listbox_mousewheel, add='+')
                listbox._mousewheel_bound_for_combobox = True
            pending_job['id'] = None
            return
        if attempt >= 10:
            pending_job['id'] = None
            return
        try:
            pending_job['id'] = combo.after(20, lambda: _ensure_binding(attempt + 1))
        except tk.TclError:
            pending_job['id'] = None

    def _schedule_binding(_event=None):
        _cancel_pending_job()
        try:
            combo.after_idle(lambda: _ensure_binding(0))
        except tk.TclError:
            pending_job['id'] = None

    combo.bind('<Button-1>', _schedule_binding, add='+')
    combo.bind('<Down>', _schedule_binding, add='+')
    combo.bind('<FocusIn>', _schedule_binding, add='+')
    _schedule_binding()


class SkillCardGrid(tk.Frame):
    """响应式网格布局容器，用于展示固定宽度的技能卡片。"""

    def __init__(self, parent, card_width=280, gap_x=14, gap_y=14, **kwargs):
        kwargs.setdefault('bg', parent.cget('bg') if 'bg' in parent.keys() else COLORS['bg_main'])
        kwargs.setdefault('bd', 0)
        kwargs.setdefault('highlightthickness', 0)
        super().__init__(parent, **kwargs)
        self._card_width = card_width
        self._gap_x = gap_x
        self._gap_y = gap_y
        self._cards = []
        self._last_layout_signature = None
        self.bind('<Configure>', self._schedule_relayout, add='+')

    def add_card(self, widget):
        self._cards.append(widget)
        self.after_idle(self._schedule_relayout)

    def clear_cards(self):
        for card in self._cards:
            card.grid_forget()
            card.destroy()
        self._cards.clear()
        self._last_layout_signature = None

    def _schedule_relayout(self, _event=None, delay_ms=16):
        _schedule_resize_batch(
            self,
            ('skill_card_grid', str(self)),
            self._relayout,
            delay_ms=delay_ms,
        )

    def _relayout(self):
        if not self._cards:
            return
        width = max(self.winfo_width(), 1)
        cols = max(1, width // (self._card_width + self._gap_x))
        signature = (width, cols, len(self._cards))
        if signature == self._last_layout_signature:
            return
        self._last_layout_signature = signature

        for card in self._cards:
            card.grid_forget()

        for col in range(cols):
            self.grid_columnconfigure(col, weight=1, uniform='skill_col')

        for index, card in enumerate(self._cards):
            row = index // cols
            col = index % cols
            padx = (0, self._gap_x) if col < cols - 1 else (0, 0)
            pady = (0, self._gap_y)
            card.grid(row=row, column=col, padx=padx, pady=pady, sticky='new')


class ResponsiveButtonBar(tk.Frame):
    """根据可用宽度自动换行的按钮容器。"""

    def __init__(self, parent, min_item_width=140, gap_x=8, gap_y=8, stretch=False, **kwargs):
        kwargs.setdefault('bg', parent.cget('bg') if 'bg' in parent.keys() else COLORS['bg_main'])
        kwargs.setdefault('bd', 0)
        kwargs.setdefault('highlightthickness', 0)
        super().__init__(parent, **kwargs)
        self.min_item_width = min_item_width
        self.gap_x = gap_x
        self.gap_y = gap_y
        self.stretch = stretch
        self.widgets = []
        self._last_layout_signature = None
        self.bind('<Configure>', self._schedule_relayout, add='+')

    def add(self, widget):
        self.widgets.append(widget)
        self.after_idle(self._schedule_relayout)

    def _schedule_relayout(self, _event=None, delay_ms=16):
        _schedule_resize_batch(
            self,
            ('responsive_button_bar', str(self)),
            self._relayout,
            delay_ms=delay_ms,
        )

    def _relayout(self, _event=None):
        if not self.widgets:
            return

        width = max(self.winfo_width(), 1)
        requested_widths = [
            max(widget.winfo_reqwidth(), self.min_item_width)
            for widget in self.widgets
        ]
        signature = (width, tuple(requested_widths), self.stretch, self.gap_x, self.gap_y)
        if self._last_layout_signature == signature:
            return
        self._last_layout_signature = signature
        cols = len(self.widgets)
        while cols > 1:
            column_widths = [0] * cols
            for index, req_width in enumerate(requested_widths):
                col = index % cols
                column_widths[col] = max(column_widths[col], req_width)
            total_width = sum(column_widths) + self.gap_x * (cols - 1)
            if total_width <= width:
                break
            cols -= 1

        for widget in self.widgets:
            widget.grid_forget()

        for index, widget in enumerate(self.widgets):
            row = index // cols
            col = index % cols
            padx = (0, self.gap_x) if col < cols - 1 else (0, 0)
            pady = (0, self.gap_y)
            widget.grid(row=row, column=col, padx=padx, pady=pady, sticky='ew' if self.stretch else 'w')

        for col in range(max(len(self.widgets), cols)):
            self.grid_columnconfigure(col, weight=0)
        for col in range(cols):
            self.grid_columnconfigure(col, weight=1 if self.stretch else 0)


def bind_responsive_two_pane(
    container,
    left_widget,
    right_widget,
    breakpoint=1040,
    gap=8,
    left_minsize=280,
    left_weight=1,
    right_weight=2,
    uniform_group=None,
):
    """双栏布局在宽度不足时自动改为上下布局。"""

    state = {'mode': None}

    def relayout(_event=None):
        width = max(container.winfo_width(), container.winfo_reqwidth(), 1)
        stacked = width < breakpoint
        mode = 'stacked' if stacked else 'split'
        if state['mode'] == mode:
            return
        state['mode'] = mode

        left_widget.grid_forget()
        right_widget.grid_forget()

        if stacked:
            container.grid_columnconfigure(0, weight=1, minsize=0, uniform='')
            container.grid_columnconfigure(1, weight=0, minsize=0, uniform='')
            container.grid_rowconfigure(0, weight=1)
            container.grid_rowconfigure(1, weight=1)
            left_widget.grid(row=0, column=0, sticky='nsew', pady=(0, gap))
            right_widget.grid(row=1, column=0, sticky='nsew')
        else:
            container.grid_columnconfigure(0, weight=left_weight, minsize=left_minsize, uniform=uniform_group or '')
            container.grid_columnconfigure(1, weight=right_weight, minsize=0, uniform=uniform_group or '')
            container.grid_rowconfigure(0, weight=1)
            container.grid_rowconfigure(1, weight=0)
            left_widget.grid(row=0, column=0, sticky='nsew', padx=(0, gap))
            right_widget.grid(row=0, column=1, sticky='nsew')

    def schedule_relayout(_event=None):
        _schedule_resize_batch(
            container,
            ('responsive_two_pane', str(container)),
            relayout,
            delay_ms=16,
        )

    container.bind('<Configure>', schedule_relayout, add='+')
    container.after_idle(relayout)


def bind_adaptive_wrap(label, container, padding=40, min_width=180, max_width=None):
    """根据容器宽度动态调整 Label 的 wraplength。"""

    state = {'wraplength': None}

    def resize(_event=None):
        width = max(container.winfo_width() - padding, min_width)
        if max_width:
            width = min(width, max_width)
        width = int(width)
        if state['wraplength'] == width:
            return
        state['wraplength'] = width
        try:
            label.configure(wraplength=width)
        except tk.TclError:
            pass

    def schedule_resize(_event=None):
        _schedule_resize_batch(
            container,
            ('adaptive_wrap', str(label)),
            resize,
            delay_ms=16,
        )

    container.bind('<Configure>', schedule_resize, add='+')
    container.after_idle(resize)


class ModernButton(tk.Button):
    """统一按钮组件。"""

    STYLES = {
        'primary': lambda: {
            'bg': COLORS['accent'],
            'fg': COLORS['text_main'],
            'activebackground': COLORS['btn_hover'],
            'activeforeground': COLORS['text_main'],
            'highlightbackground': COLORS['card_border'],
        },
        'primary_fixed': lambda: {
            'bg': THEMES['light']['accent'],
            'fg': THEMES['light']['text_main'],
            'activebackground': THEMES['light']['btn_hover'],
            'activeforeground': THEMES['light']['text_main'],
            'highlightbackground': THEMES['light']['card_border'],
        },
        'secondary': lambda: {
            'bg': COLORS['card_bg'],
            'fg': COLORS['text_main'],
            'activebackground': COLORS['accent_light'],
            'activeforeground': COLORS['text_main'],
            'highlightbackground': COLORS['card_border'],
        },
        'ghost': lambda: {
            'bg': COLORS['surface_alt'],
            'fg': COLORS['text_main'],
            'activebackground': COLORS['primary_light'],
            'activeforeground': COLORS['text_main'],
            'highlightbackground': COLORS['card_border'],
        },
        'accent': lambda: {
            'bg': COLORS['primary'],
            'fg': '#FFFFFF',
            'activebackground': COLORS['primary_dark'],
            'activeforeground': '#FFFFFF',
            'highlightbackground': COLORS['card_border'],
        },
        'danger': lambda: {
            'bg': COLORS['error'],
            'fg': '#FFFFFF',
            'activebackground': COLORS['error'],
            'activeforeground': '#FFFFFF',
            'highlightbackground': COLORS['card_border'],
        },
        'warning': lambda: {
            'bg': COLORS['warning'],
            'fg': COLORS['text_main'],
            'activebackground': COLORS['warning'],
            'activeforeground': COLORS['text_main'],
            'highlightbackground': COLORS['card_border'],
        },
        'nav': lambda: {
            'bg': COLORS['card_bg'],
            'fg': COLORS['text_main'],
            'activebackground': COLORS['card_bg'],
            'activeforeground': COLORS['text_main'],
            'highlightbackground': COLORS['card_border'],
        },
        'nav_active': lambda: {
            'bg': COLORS['nav_active'],
            'fg': COLORS['text_main'],
            'activebackground': COLORS['nav_active'],
            'activeforeground': COLORS['text_main'],
            'highlightbackground': COLORS['card_border'],
        },
        'tool': lambda: {
            'bg': COLORS['toolbar_icon_bg'],
            'fg': COLORS['toolbar_icon_fg'],
            'activebackground': COLORS['accent_light'],
            'activeforeground': COLORS['text_main'],
            'highlightbackground': COLORS['card_border'],
        },
        'pill': lambda: {
            'bg': COLORS['pill_bg'],
            'fg': COLORS['text_sub'],
            'activebackground': COLORS['accent_light'],
            'activeforeground': COLORS['text_main'],
            'highlightbackground': COLORS['pill_bg'],
        },
        'pill_active': lambda: {
            'bg': COLORS['pill_active_bg'],
            'fg': COLORS['pill_active_fg'],
            'activebackground': COLORS['pill_active_bg'],
            'activeforeground': COLORS['pill_active_fg'],
            'highlightbackground': COLORS['pill_active_bg'],
        },
    }

    def __init__(self, parent, text='', style='primary', **kwargs):
        self.style_name = style
        kwargs.setdefault('font', FONTS['body_bold'])
        kwargs.setdefault('relief', tk.FLAT)
        kwargs.setdefault('bd', 0)
        kwargs.setdefault('cursor', 'hand2')
        kwargs.setdefault('padx', 12)
        kwargs.setdefault('pady', 8)
        kwargs.setdefault('highlightthickness', 3)
        kwargs.setdefault('compound', tk.LEFT)
        super().__init__(parent, text=text, **kwargs)
        self.set_style(style)

    def set_style(self, style):
        self.style_name = style
        style_map = self.STYLES.get(style, self.STYLES['primary'])()
        self.configure(**style_map)


class ToggleSwitch(tk.Frame):
    """圆角矩形开关组件，替代传统 Checkbutton。"""

    def __init__(
        self,
        parent,
        variable=None,
        command=None,
        width=44,
        height=24,
        **kwargs
    ):
        bg = kwargs.pop('bg', COLORS['bg_main'])
        super().__init__(parent, bg=bg, **kwargs)

        self.variable = variable or tk.BooleanVar()
        self.command = command
        self.width = width
        self.height = height
        self.knob_radius = (height - 4) // 2
        self.knob_padding = 2

        self._animating = False
        self._animation_step = 0
        self._animation_steps = 8

        self.canvas = tk.Canvas(
            self,
            width=width,
            height=height,
            bg=bg,
            highlightthickness=0,
            bd=0,
            cursor='hand2',
        )
        self.canvas.pack()

        self.track_id = None
        self.knob_id = None

        self._draw()
        self.canvas.bind('<Button-1>', self._on_click)
        self.variable.trace_add('write', self._on_variable_changed)

    def _draw(self):
        """绘制开关的轨道和滑块。"""
        self.canvas.delete('all')
        is_on = bool(self.variable.get())

        track_color = COLORS['primary'] if is_on else COLORS['surface_alt']
        knob_color = '#FFFFFF'

        track_radius = self.height // 2
        self.track_id = self._draw_rounded_rect(
            0, 0, self.width, self.height, track_radius, fill=track_color, outline=''
        )

        if self._animating:
            progress = self._animation_step / self._animation_steps
            if not is_on:
                progress = 1 - progress
            knob_x = self.knob_padding + self.knob_radius + progress * (
                self.width - 2 * self.knob_padding - 2 * self.knob_radius
            )
        else:
            if is_on:
                knob_x = self.width - self.knob_padding - self.knob_radius
            else:
                knob_x = self.knob_padding + self.knob_radius

        knob_y = self.height // 2
        self.knob_id = self.canvas.create_oval(
            knob_x - self.knob_radius,
            knob_y - self.knob_radius,
            knob_x + self.knob_radius,
            knob_y + self.knob_radius,
            fill=knob_color,
            outline='',
        )

    def _draw_rounded_rect(self, x1, y1, x2, y2, radius, **kwargs):
        """绘制圆角矩形。"""
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]
        return self.canvas.create_polygon(points, smooth=True, **kwargs)

    def _on_click(self, event=None):
        """点击切换状态。"""
        if self._animating:
            return
        self.variable.set(not bool(self.variable.get()))
        if callable(self.command):
            try:
                self.command()
            except Exception:
                pass

    def _on_variable_changed(self, *args):
        """变量改变时触发动画。"""
        if self._animating:
            return
        self._start_animation()

    def _start_animation(self):
        """启动滑块动画。"""
        self._animating = True
        self._animation_step = 0
        self._animate()

    def _animate(self):
        """执行动画的一帧。"""
        if not self._animating:
            return

        self._animation_step += 1
        self._draw()

        if self._animation_step < self._animation_steps:
            self.after(20, self._animate)
        else:
            self._animating = False
            self._draw()

    def configure(self, **kwargs):
        """配置开关属性。"""
        if 'variable' in kwargs:
            self.variable = kwargs.pop('variable')
            self.variable.trace_add('write', self._on_variable_changed)
            self._draw()
        if 'command' in kwargs:
            self.command = kwargs.pop('command')
        if 'state' in kwargs:
            state = kwargs.pop('state')
            if state == 'disabled':
                self.canvas.configure(cursor='')
                self.canvas.unbind('<Button-1>')
            else:
                self.canvas.configure(cursor='hand2')
                self.canvas.bind('<Button-1>', self._on_click)
        super().configure(**kwargs)


class ToolIconButton(ModernButton):
    """顶部工具按钮。"""

    def __init__(self, parent, text='', tooltip=None, **kwargs):
        kwargs.setdefault('width', 2)
        kwargs.setdefault('padx', 6)
        kwargs.setdefault('pady', 6)
        super().__init__(parent, text=text, style='tool', **kwargs)
        if tooltip:
            show_tooltip(self, tooltip)


class DateTimePickerDialog:
    """日期时间选择弹窗，支持精确到分钟。"""

    WEEKDAY_LABELS = ('一', '二', '三', '四', '五', '六', '日')
    INPUT_FORMATS = (
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d %H:%M:%S',
        '%Y/%m/%d %H:%M',
        '%Y/%m/%d %H:%M:%S',
        '%Y-%m-%d',
        '%Y/%m/%d',
    )

    def __init__(self, parent, *, title='选择时间', initial_value=''):
        self.parent = parent
        self.result = None
        self.selected_at = self._parse_initial_value(initial_value)
        self.display_year = self.selected_at.year
        self.display_month = self.selected_at.month
        self.hour_var = tk.StringVar(value=f'{self.selected_at.hour:02d}')
        self.minute_var = tk.StringVar(value=f'{self.selected_at.minute:02d}')

        owner = parent.winfo_toplevel() if parent is not None else None
        self.window = tk.Toplevel(owner)
        self.window.title(title)
        self.window.configure(bg=COLORS['bg_main'])
        self.window.resizable(False, False)
        if owner is not None:
            self.window.transient(owner)
        self.window.grab_set()
        self.window.protocol('WM_DELETE_WINDOW', self._cancel)

        self._build_ui(title)
        self._render_calendar()
        self.window.after_idle(self._center_window)

    def _parse_initial_value(self, value):
        text = str(value or '').strip()
        for fmt in self.INPUT_FORMATS:
            try:
                return datetime.strptime(text, fmt).replace(second=0, microsecond=0)
            except ValueError:
                continue
        return datetime.now().replace(second=0, microsecond=0)

    def _build_ui(self, title):
        card = CardFrame(self.window, padding=16)
        card.pack(padx=14, pady=14)
        body = card.inner

        tk.Label(
            body,
            text=title,
            font=FONTS['heading'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w')

        header = tk.Frame(body, bg=COLORS['card_bg'])
        header.pack(fill=tk.X, pady=(12, 10))
        ModernButton(
            header,
            '<',
            style='secondary',
            command=self._show_previous_month,
            padx=12,
            pady=6,
            font=FONTS['body_bold'],
            width=3,
        ).pack(side=tk.LEFT)
        self.month_label = tk.Label(
            header,
            text='',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        )
        self.month_label.pack(side=tk.LEFT, expand=True)
        ModernButton(
            header,
            '>',
            style='secondary',
            command=self._show_next_month,
            padx=12,
            pady=6,
            font=FONTS['body_bold'],
            width=3,
        ).pack(side=tk.RIGHT)

        weekday_row = tk.Frame(body, bg=COLORS['card_bg'])
        weekday_row.pack(fill=tk.X)
        for index, label in enumerate(self.WEEKDAY_LABELS):
            weekday_row.grid_columnconfigure(index, weight=1, uniform='picker_week')
            tk.Label(
                weekday_row,
                text=label,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                width=4,
            ).grid(row=0, column=index, padx=3, pady=(0, 4), sticky='ew')

        self.calendar_frame = tk.Frame(body, bg=COLORS['card_bg'])
        self.calendar_frame.pack(fill=tk.X)
        for index in range(7):
            self.calendar_frame.grid_columnconfigure(index, weight=1, uniform='picker_day')

        time_row = tk.Frame(body, bg=COLORS['card_bg'])
        time_row.pack(fill=tk.X, pady=(14, 0))
        tk.Label(
            time_row,
            text='时间',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)
        ttk.Combobox(
            time_row,
            textvariable=self.hour_var,
            values=[f'{value:02d}' for value in range(24)],
            state='readonly',
            width=4,
            style='Modern.TCombobox',
        ).pack(side=tk.LEFT, padx=(10, 4))
        tk.Label(
            time_row,
            text=':',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)
        ttk.Combobox(
            time_row,
            textvariable=self.minute_var,
            values=[f'{value:02d}' for value in range(60)],
            state='readonly',
            width=4,
            style='Modern.TCombobox',
        ).pack(side=tk.LEFT, padx=(4, 0))

        action_row = tk.Frame(body, bg=COLORS['card_bg'])
        action_row.pack(fill=tk.X, pady=(16, 0))
        ModernButton(
            action_row,
            '应用',
            style='primary',
            command=self._apply,
            padx=16,
            pady=8,
            font=FONTS['body_bold'],
        ).pack(side=tk.RIGHT)
        ModernButton(
            action_row,
            '取消',
            style='secondary',
            command=self._cancel,
            padx=16,
            pady=8,
            font=FONTS['body_bold'],
        ).pack(side=tk.RIGHT, padx=(0, 8))

    def _center_window(self):
        self.window.update_idletasks()
        owner = self.parent.winfo_toplevel() if self.parent is not None else self.window
        owner.update_idletasks()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        x = owner.winfo_rootx() + max((owner.winfo_width() - width) // 2, 20)
        y = owner.winfo_rooty() + max((owner.winfo_height() - height) // 2, 20)
        self.window.geometry(f'+{x}+{y}')

    def _show_previous_month(self):
        if self.display_month == 1:
            self.display_year -= 1
            self.display_month = 12
        else:
            self.display_month -= 1
        self._render_calendar()

    def _show_next_month(self):
        if self.display_month == 12:
            self.display_year += 1
            self.display_month = 1
        else:
            self.display_month += 1
        self._render_calendar()

    def _select_day(self, day):
        self.selected_at = self.selected_at.replace(
            year=self.display_year,
            month=self.display_month,
            day=day,
        )
        self._render_calendar()

    def _render_calendar(self):
        for child in self.calendar_frame.winfo_children():
            child.destroy()

        self.month_label.configure(text=f'{self.display_year:04d}-{self.display_month:02d}')
        weeks = calendar.monthcalendar(self.display_year, self.display_month)
        selected_key = (
            self.selected_at.year,
            self.selected_at.month,
            self.selected_at.day,
        )

        for row_index, week in enumerate(weeks):
            self.calendar_frame.grid_rowconfigure(row_index, weight=1)
            for column_index, day in enumerate(week):
                if day == 0:
                    tk.Label(
                        self.calendar_frame,
                        text='',
                        bg=COLORS['card_bg'],
                        width=4,
                    ).grid(row=row_index, column=column_index, padx=3, pady=3, sticky='nsew')
                    continue

                is_selected = selected_key == (self.display_year, self.display_month, day)
                button = tk.Button(
                    self.calendar_frame,
                    text=str(day),
                    command=lambda value=day: self._select_day(value),
                    font=FONTS['small'],
                    bg=COLORS['accent'] if is_selected else COLORS['surface_alt'],
                    fg=COLORS['text_main'],
                    activebackground=COLORS['btn_hover'] if is_selected else COLORS['accent_light'],
                    activeforeground=COLORS['text_main'],
                    relief=tk.FLAT,
                    bd=0,
                    highlightthickness=2,
                    highlightbackground=COLORS['card_border'],
                    cursor='hand2',
                    width=4,
                    pady=6,
                )
                button.grid(row=row_index, column=column_index, padx=3, pady=3, sticky='nsew')

    def _apply(self):
        try:
            hour = int(self.hour_var.get())
            minute = int(self.minute_var.get())
        except Exception:
            hour = self.selected_at.hour
            minute = self.selected_at.minute
        self.selected_at = self.selected_at.replace(hour=hour, minute=minute, second=0, microsecond=0)
        self.result = self.selected_at.strftime('%Y-%m-%d %H:%M')
        self.window.destroy()

    def _cancel(self):
        self.result = None
        self.window.destroy()

    def show(self):
        self.window.wait_window()
        return self.result


def ask_datetime_string(parent, *, title='选择时间', initial_value=''):
    """打开日期时间选择弹窗并返回格式化字符串。"""

    dialog = DateTimePickerDialog(parent, title=title, initial_value=initial_value)
    return dialog.show()


class ModernEntry(tk.Entry):
    """现代风格输入框。"""

    def __init__(self, parent, placeholder='', show='', **kwargs):
        kwargs.setdefault('bg', COLORS['input_bg'])
        kwargs.setdefault('fg', COLORS['text_main'])
        kwargs.setdefault('font', FONTS['body'])
        kwargs.setdefault('relief', tk.FLAT)
        kwargs.setdefault('bd', 0)
        kwargs.setdefault('highlightthickness', 2)
        kwargs.setdefault('highlightbackground', COLORS['input_border'])
        kwargs.setdefault('highlightcolor', COLORS['accent'])
        kwargs.setdefault('insertbackground', COLORS['text_main'])
        super().__init__(parent, **kwargs)

        self.placeholder = placeholder
        self._mask_char = show or ''
        self._mask_visible = not bool(self._mask_char)
        self._placeholder_active = False
        if placeholder:
            self._show_placeholder()
            self.bind('<FocusIn>', self._on_focus_in)
            self.bind('<FocusOut>', self._on_focus_out)
        else:
            self._apply_show_state()

    def _apply_show_state(self):
        mask_char = ''
        if self._mask_char and not self._mask_visible and not self._placeholder_active:
            mask_char = self._mask_char
        self.configure(show=mask_char)

    def _show_placeholder(self):
        if not self.get():
            self.configure(fg=COLORS['text_muted'])
            self.insert(0, self.placeholder)
            self._placeholder_active = True
            self._apply_show_state()

    def _on_focus_in(self, _event):
        if self._placeholder_active:
            self.delete(0, tk.END)
            self.configure(fg=COLORS['text_main'])
            self._placeholder_active = False
            self._apply_show_state()

    def _on_focus_out(self, _event):
        if not self.get():
            self._show_placeholder()

    def refresh_mask_state(self):
        self._apply_show_state()

    def set_mask_visible(self, visible):
        self._mask_visible = bool(visible) or not self._mask_char
        self._apply_show_state()

    def is_mask_visible(self):
        return self._mask_visible or not self._mask_char

    def toggle_mask(self):
        self.set_mask_visible(not self.is_mask_visible())

    def get_value(self):
        if self._placeholder_active:
            return ''
        return self.get()


class ModernText(tk.Text):
    """现代风格文本框。"""

    def __init__(self, parent, **kwargs):
        kwargs.setdefault('bg', COLORS['input_bg'])
        kwargs.setdefault('fg', COLORS['text_main'])
        kwargs.setdefault('font', FONTS['body'])
        kwargs.setdefault('relief', tk.FLAT)
        kwargs.setdefault('bd', 0)
        kwargs.setdefault('highlightthickness', 2)
        kwargs.setdefault('highlightbackground', COLORS['input_border'])
        kwargs.setdefault('highlightcolor', COLORS['accent'])
        kwargs.setdefault('insertbackground', COLORS['text_main'])
        kwargs.setdefault('selectbackground', COLORS['accent'])
        kwargs.setdefault('selectforeground', COLORS['text_main'])
        kwargs.setdefault('wrap', tk.WORD)
        kwargs.setdefault('spacing1', 2)
        kwargs.setdefault('spacing3', 2)
        super().__init__(parent, **kwargs)


class AnimatedImageLabel(tk.Label):
    """播放GIF动画的标签。"""

    def __init__(self, parent, filename, max_size=None, **kwargs):
        kwargs.setdefault('bg', parent.cget('bg'))
        super().__init__(parent, **kwargs)
        self.frames, self.delays = load_gif_frames(filename, max_size=max_size)
        self._frame_index = 0
        self._after_id = None
        self.configure(image=self.frames[0])

    def start(self, delay=None):
        self.stop()

        def animate():
            self._frame_index = (self._frame_index + 1) % len(self.frames)
            self.configure(image=self.frames[self._frame_index])
            frame_delay = delay if delay is not None else self.delays[self._frame_index]
            self._after_id = self.after(frame_delay, animate)

        if len(self.frames) > 1:
            first_delay = delay if delay is not None else self.delays[0]
            self._after_id = self.after(first_delay, animate)

    def stop(self):
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        self._frame_index = 0
        if self.frames:
            self.configure(image=self.frames[0])


class LoadingOverlay(tk.Frame):
    """页面中央加载卡片。"""

    def __init__(self, parent, config_mgr=None, text='处理中，请稍候...'):
        super().__init__(parent, bg=parent.cget('bg'), bd=0, highlightthickness=0)
        self.config_mgr = config_mgr
        self.default_text = text
        self.place_forget()

        self.card = CardFrame(self, padding=18)
        self.card.pack()

        self.spinner = None

        self.label = tk.Label(
            self.card.inner,
            text=text,
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        )
        self.label.pack()

    def _ensure_spinner(self):
        if self.spinner is not None:
            return self.spinner
        self.spinner = AnimatedImageLabel(self.card.inner, 'loading.gif', max_size=(72, 72))
        self.spinner.pack(pady=(0, 12), before=self.label)
        return self.spinner

    def show(self, text=None):
        if self.config_mgr and not self.config_mgr.get_setting('enable_loading_animation', True):
            return
        self.label.configure(text=text or self.default_text)
        self.place(relx=0.5, rely=0.5, anchor='center')
        self.lift()
        self._ensure_spinner().start()

    def hide(self):
        if self.spinner is not None:
            self.spinner.stop()
        self.place_forget()


def create_scrolled_text(parent, height=10, show_scrollbar=False, **kwargs):
    """创建带滚动条的文本框。"""
    frame = tk.Frame(
        parent,
        bg=COLORS['card_bg'],
        highlightthickness=3,
        highlightbackground=COLORS['input_border'],
        bd=0,
    )

    text = ModernText(frame, height=height, highlightthickness=0, **kwargs)

    def _on_text_mousewheel(event):
        if event.num == 4:
            text.yview_scroll(-1, 'units')
        elif event.num == 5:
            text.yview_scroll(1, 'units')
        else:
            delta = int(-1 * (event.delta / 120))
            if delta == 0 and event.delta:
                delta = -1 if event.delta > 0 else 1
            if delta:
                text.yview_scroll(delta, 'units')
        return 'break'

    for widget in (frame, text):
        widget.bind('<MouseWheel>', _on_text_mousewheel, add='+')
        widget.bind('<Button-4>', _on_text_mousewheel, add='+')
        widget.bind('<Button-5>', _on_text_mousewheel, add='+')

    vsb = ttk.Scrollbar(
        frame,
        orient=tk.VERTICAL,
        command=text.yview,
        style='Thin.Vertical.TScrollbar',
    )
    text.configure(yscrollcommand=vsb.set)
    if show_scrollbar:
        vsb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=4)

    # vsb 不显示，但保留绑定以支持键盘/触控板滚动
    text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)

    return frame, text


def create_label_entry(parent, label_text, placeholder='', show='', width=30):
    """创建标签+输入框组合。"""
    frame = tk.Frame(parent, bg=COLORS['card_bg'])

    tk.Label(
        frame,
        text=label_text,
        font=FONTS['body'],
        fg=COLORS['text_sub'],
        bg=COLORS['card_bg'],
        width=10,
        anchor='e',
    ).pack(side=tk.LEFT, padx=(0, 8))

    entry = ModernEntry(frame, placeholder=placeholder, show=show, width=width)
    entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)

    return frame, entry


def _build_tooltip_shell(tooltip, text, *, wraplength, tooltip_style='default'):
    style_key = (tooltip_style or 'default').strip().lower()
    if style_key == 'theme':
        tooltip.configure(bg=COLORS['shadow'])
        shell = tk.Frame(tooltip, bg=COLORS['shadow'], bd=0, highlightthickness=0)
        shell.pack()
        body = tk.Frame(
            shell,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
            bd=0,
        )
        body.pack(padx=(0, 4), pady=(0, 4))
        label = tk.Label(
            body,
            text=text,
            font=FONTS['small'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
            padx=10,
            pady=6,
            justify='left',
            anchor='w',
            wraplength=wraplength,
        )
        label.pack()
        return

    tooltip.configure(bg=COLORS['card_border'])
    frame = tk.Frame(
        tooltip,
        bg=COLORS['card_border'],
        highlightbackground=COLORS['card_border'],
        highlightthickness=1,
    )
    frame.pack()
    label = tk.Label(
        frame,
        text=text,
        font=FONTS['small'],
        fg=COLORS.get('menu_fg', COLORS['text_main']),
        bg=COLORS.get('menu_bg', COLORS['card_bg']),
        padx=10,
        pady=6,
        justify='left',
        anchor='w',
        wraplength=wraplength,
    )
    label.pack()


def show_tooltip(widget, text, *, placement='bottom_center', x_offset=0, y_offset=6, wraplength=260, tooltip_style='default'):
    """为控件添加提示框。"""
    tooltip = None

    def show(_event):
        nonlocal tooltip
        if tooltip or not text:
            return
        tooltip = tk.Toplevel(widget)
        tooltip.wm_overrideredirect(True)
        _build_tooltip_shell(tooltip, text, wraplength=wraplength, tooltip_style=tooltip_style)

        tooltip.update_idletasks()

        width = tooltip.winfo_reqwidth()
        height = tooltip.winfo_reqheight()
        widget_center_x = widget.winfo_rootx() + widget.winfo_width() // 2
        x = widget_center_x - width // 2 + x_offset

        if placement == 'top_center':
            y = widget.winfo_rooty() - height - y_offset
            if y < 8:
                y = widget.winfo_rooty() + widget.winfo_height() + y_offset
        else:
            y = widget.winfo_rooty() + widget.winfo_height() + y_offset

        screen_width = widget.winfo_screenwidth()
        x = max(8, min(x, screen_width - width - 8))
        tooltip.wm_geometry(f'+{x}+{y}')

    def hide(_event):
        nonlocal tooltip
        if tooltip:
            tooltip.destroy()
            tooltip = None

    widget.bind('<Enter>', show)
    widget.bind('<Leave>', hide)


def _measure_font_text(font_spec, text):
    try:
        cache_key = repr(font_spec)
        font = _FONT_MEASURE_CACHE.get(cache_key)
        if font is None:
            if isinstance(font_spec, str):
                font = tkfont.nametofont(font_spec)
            else:
                font = tkfont.Font(font=font_spec)
            _FONT_MEASURE_CACHE[cache_key] = font
        return font.measure(text)
    except tk.TclError:
        return len(text) * 7


def _ellipsize_text(text, font_spec, max_width):
    value = text or ''
    if not value or max_width <= 0:
        return value, False
    if _measure_font_text(font_spec, value) <= max_width:
        return value, False

    suffix = '...'
    suffix_width = _measure_font_text(font_spec, suffix)
    if suffix_width >= max_width:
        return suffix, True

    low = 0
    high = len(value)
    while low < high:
        mid = (low + high + 1) // 2
        candidate = value[:mid] + suffix
        if _measure_font_text(font_spec, candidate) <= max_width:
            low = mid
        else:
            high = mid - 1
    return value[:low] + suffix, True


def bind_ellipsis_tooltip(label, *, padding=0, wraplength=320, tooltip_style='default'):
    state = {'tooltip': None, 'signature': None}

    def refresh(_event=None):
        full_text = getattr(label, '_ellipsis_full_text', '') or ''
        available_width = max(label.winfo_width() - padding, 0)
        signature = (full_text, available_width, repr(label.cget('font')))
        if state['signature'] == signature:
            return
        state['signature'] = signature
        if available_width <= 1:
            label.configure(text=full_text)
            label._ellipsis_tooltip_text = ''
            return
        display_text, truncated = _ellipsize_text(full_text, label.cget('font'), available_width)
        label.configure(text=display_text)
        label._ellipsis_tooltip_text = full_text if truncated else ''

    def show(_event=None):
        text = getattr(label, '_ellipsis_tooltip_text', '') or ''
        if state['tooltip'] or not text:
            return
        state['tooltip'] = tk.Toplevel(label)
        state['tooltip'].wm_overrideredirect(True)
        _build_tooltip_shell(state['tooltip'], text, wraplength=wraplength, tooltip_style=tooltip_style)
        state['tooltip'].update_idletasks()
        width = state['tooltip'].winfo_reqwidth()
        x = label.winfo_rootx() + max(label.winfo_width() - width, 0)
        y = label.winfo_rooty() + label.winfo_height() + 6
        screen_width = label.winfo_screenwidth()
        x = max(8, min(x, screen_width - width - 8))
        state['tooltip'].wm_geometry(f'+{x}+{y}')

    def hide(_event=None):
        if state['tooltip'] is not None:
            state['tooltip'].destroy()
            state['tooltip'] = None

    def schedule_refresh(_event=None):
        _schedule_resize_batch(
            label,
            ('ellipsis_tooltip', str(label)),
            refresh,
            delay_ms=16,
        )

    label.bind('<Configure>', schedule_refresh, add='+')
    label.bind('<Enter>', show, add='+')
    label.bind('<Leave>', hide, add='+')
    label._refresh_ellipsis_text = refresh
    label._ellipsis_tooltip_text = ''
    label.after_idle(refresh)


def set_ellipsized_label_text(label, text):
    label._ellipsis_full_text = (text or '').strip()
    refresh = getattr(label, '_refresh_ellipsis_text', None)
    if callable(refresh):
        refresh()
    else:
        label.configure(text=label._ellipsis_full_text)


# ──────────────────────────────────────────────
# 中英文混合字体工具
# ──────────────────────────────────────────────

def _is_cjk_char(ch):
    """判断字符是否为中文/CJK字符"""
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0x20000 <= cp <= 0x2A6DF
        or 0xF900 <= cp <= 0xFAFF
        or 0x2F800 <= cp <= 0x2FA1F
        or 0x3000 <= cp <= 0x303F
        or 0xFF00 <= cp <= 0xFFEF
        or 0x2000 <= cp <= 0x206F
    )


def apply_mixed_fonts(widget, cn_font_name, en_font_name, size_pt):
    """为Text widget应用中英文混合字体：中文用cn_font，英文用en_font。

    基础字体设置为中文字体，英文字符区间加 _font_en tag 覆盖。
    """
    size_pt = int(size_pt)
    widget.configure(font=(cn_font_name, size_pt))

    en_font = tkfont.Font(root=widget, family=en_font_name, size=size_pt)
    widget.tag_configure('_font_en', font=en_font)

    widget.tag_remove('_font_en', '1.0', tk.END)
    text_end = widget.index('end-1c')
    content = widget.get('1.0', text_end)
    if not content:
        return

    line = 1
    col = 0
    en_start = None
    for ch in content:
        if ch == '\n':
            if en_start is not None:
                widget.tag_add('_font_en', en_start, f'{line}.{col}')
                en_start = None
            line += 1
            col = 0
            continue
        if _is_cjk_char(ch):
            if en_start is not None:
                widget.tag_add('_font_en', en_start, f'{line}.{col}')
                en_start = None
        else:
            if en_start is None:
                en_start = f'{line}.{col}'
        col += 1
    if en_start is not None:
        widget.tag_add('_font_en', en_start, text_end)
    widget.tag_lower('_font_en')
