"""应用内自动更新模块

提供跨平台的自动下载、校验、安装更新功能。
支持 Windows (Inno Setup 安装版 + 便携版)、macOS (DMG)、Linux (AppImage)。
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Literal, NoReturn

# 平台特定导入（可选）
try:
    if sys.platform == 'win32':
        import winreg
except ImportError:
    winreg = None

try:
    if sys.platform == 'darwin':
        import plistlib
except ImportError:
    plistlib = None


InstallMode = Literal['installer', 'portable', 'dmg', 'appimage', 'deb_rpm', 'dev']


# ============================================================================
# 异常类
# ============================================================================

class UpdateCancelled(Exception):
    """用户取消更新"""
    pass


class UnsupportedArchError(Exception):
    """不支持的系统架构"""
    pass


class UpdateNetworkError(Exception):
    """网络错误"""
    pass


class UpdateDiskError(Exception):
    """磁盘空间不足"""
    pass


# ============================================================================
# 公共接口
# ============================================================================

def detect_install_mode() -> InstallMode:
    """检测当前应用的安装形态

    Returns:
        InstallMode: 安装形态类型
    """
    # 开发模式（未打包）
    if not getattr(sys, 'frozen', False):
        return 'dev'

    # Windows 平台
    if sys.platform == 'win32':
        exe_dir = os.path.dirname(sys.executable)

        # 方法 1: 读取注册表 Inno Setup 卸载项
        if winreg:
            try:
                key_path = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{B8F3C2A1-5E7D-4A9B-8C6F-1D2E3F4A5B6C}_is1'
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                    install_location, _ = winreg.QueryValueEx(key, 'InstallLocation')
                    # 规范化路径比较
                    if os.path.normcase(os.path.normpath(install_location)) == os.path.normcase(os.path.normpath(exe_dir)):
                        return 'installer'
            except (OSError, FileNotFoundError):
                pass

        # 方法 2: 检查 Inno Setup 卸载器特征文件
        if os.path.exists(os.path.join(exe_dir, 'unins000.exe')):
            return 'installer'

        # 其余视为便携版
        return 'portable'

    # macOS 平台
    if sys.platform == 'darwin':
        return 'dmg'

    # Linux 平台
    if os.environ.get('APPIMAGE'):
        return 'appimage'

    # 其他 Linux 安装方式（deb/rpm）不在自动更新范围
    return 'deb_rpm'


def can_auto_update() -> tuple[bool, str]:
    """检查是否支持自动更新

    Returns:
        (是否支持, 不支持时的原因)
    """
    mode = detect_install_mode()

    if mode == 'dev':
        return False, '当前为开发模式（未打包），无法自动更新'

    if mode == 'deb_rpm':
        return False, '当前为系统包管理器安装，请使用包管理器更新'

    # 架构检查（仅 64 位）
    machine = platform.machine().upper()
    if mode in ('installer', 'portable', 'appimage'):
        if machine not in ('AMD64', 'X86_64'):
            return False, f'暂不支持 {machine} 架构的自动更新'

    return True, ''


def build_asset_url(latest_version: str, mode: InstallMode) -> str:
    """根据版本号和安装形态构建资产下载 URL

    Args:
        latest_version: 版本号（如 'v1.5.3'）
        mode: 安装形态

    Returns:
        完整的 GitHub release 资产 URL

    Raises:
        UnsupportedArchError: 不支持的架构
    """
    base = f'https://github.com/Abnerla/AI_paper/releases/download/{latest_version}/'

    if mode == 'installer':
        return f'{base}AI_Paper-{latest_version}-windows-setup.exe'

    if mode == 'portable':
        return f'{base}AI_Paper-{latest_version}-windows.exe'

    if mode == 'dmg':
        # macOS 架构检测
        if platform.machine() == 'arm64':
            return f'{base}AI_Paper-{latest_version}-macos-apple-silicon.dmg'
        else:
            return f'{base}AI_Paper-{latest_version}-macos-intel.dmg'

    if mode == 'appimage':
        return f'{base}AI_Paper-{latest_version}-linux.AppImage'

    raise UnsupportedArchError(f'不支持的安装形态: {mode}')


def download_with_progress(
    url: str,
    dest_path: str | Path,
    on_progress: Callable[[int, int, float], None],
    cancel_event: threading.Event,
) -> Path:
    """下载文件并回调进度

    Args:
        url: 下载 URL
        dest_path: 目标文件路径
        on_progress: 进度回调 (已下载字节, 总字节, 速率 bytes/s)
        cancel_event: 取消事件

    Returns:
        下载完成的文件路径

    Raises:
        UpdateCancelled: 用户取消
        UpdateNetworkError: 网络错误
        UpdateDiskError: 磁盘空间不足
    """
    dest_path = Path(dest_path)
    dest_dir = dest_path.parent
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 临时文件名
    temp_path = dest_path.with_suffix(dest_path.suffix + '.part')

    try:
        # HEAD 请求获取文件大小
        req = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(req, timeout=10) as resp:
            total_size = int(resp.headers.get('Content-Length', 0))

        # 检查磁盘空间
        if total_size > 0:
            free_space = shutil.disk_usage(dest_dir).free
            required = int(total_size * 1.5)
            if free_space < required:
                raise UpdateDiskError(f'磁盘空间不足，请释放至少 {required / 1024 / 1024:.0f} MB')

        # 开始下载
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'AI_Paper_Updater/1.0')

        downloaded = 0
        start_time = time.time()
        speed_samples = []  # (时间戳, 已下载字节) 用于计算速率

        with urllib.request.urlopen(req, timeout=30) as resp:
            with open(temp_path, 'wb') as f:
                while True:
                    # 检查取消
                    if cancel_event.is_set():
                        raise UpdateCancelled('用户取消下载')

                    chunk = resp.read(65536)  # 64 KiB
                    if not chunk:
                        break

                    f.write(chunk)
                    downloaded += len(chunk)

                    # 计算速率（最近 2 秒滑动平均）
                    now = time.time()
                    speed_samples.append((now, downloaded))
                    speed_samples = [(t, b) for t, b in speed_samples if now - t <= 2.0]

                    if len(speed_samples) >= 2:
                        time_span = speed_samples[-1][0] - speed_samples[0][0]
                        bytes_span = speed_samples[-1][1] - speed_samples[0][1]
                        speed = bytes_span / time_span if time_span > 0 else 0
                    else:
                        speed = 0

                    # 回调进度
                    on_progress(downloaded, total_size or downloaded, speed)

        # 下载完成，重命名
        if dest_path.exists():
            dest_path.unlink()
        temp_path.rename(dest_path)

        return dest_path

    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateNetworkError('未找到安装包，可能版本尚未发布')
        else:
            raise UpdateNetworkError(f'下载失败 (HTTP {e.code})')

    except urllib.error.URLError as e:
        raise UpdateNetworkError(f'网络连接失败: {e.reason}')

    except UpdateCancelled:
        # 清理临时文件
        if temp_path.exists():
            temp_path.unlink()
        raise

    except Exception as e:
        # 清理临时文件
        if temp_path.exists():
            temp_path.unlink()
        raise UpdateNetworkError(f'下载失败: {e}')


def verify_sha256(file_path: Path, expected_hex: str | None) -> bool:
    """校验文件 SHA256

    Args:
        file_path: 文件路径
        expected_hex: 期望的 SHA256 十六进制字符串，None 则跳过校验

    Returns:
        校验是否通过（expected_hex 为 None 时返回 True）
    """
    if not expected_hex:
        return True

    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while chunk := f.read(1048576):  # 1 MiB
            sha256.update(chunk)

    return sha256.hexdigest().lower() == expected_hex.lower()


def apply_update(asset_path: Path, mode: InstallMode) -> NoReturn:
    """应用更新并重启

    此函数不会返回，最终会退出当前进程。

    Args:
        asset_path: 下载的安装包路径
        mode: 安装形态

    Raises:
        RuntimeError: 不应调用的模式
    """
    if mode == 'installer':
        _apply_windows_installer(asset_path)
    elif mode == 'portable':
        _apply_windows_portable(asset_path)
    elif mode == 'dmg':
        _apply_macos_dmg(asset_path)
    elif mode == 'appimage':
        _apply_linux_appimage(asset_path)
    else:
        raise RuntimeError(f'apply_update 不应在 {mode} 模式下调用')


# ============================================================================
# 平台特定实现
# ============================================================================

def _apply_windows_installer(setup_exe: Path) -> NoReturn:
    """Windows Inno Setup 静默安装"""
    subprocess.Popen(
        [
            str(setup_exe),
            '/VERYSILENT',
            '/SUPPRESSMSGBOXES',
            '/NORESTART',
            '/CLOSEAPPLICATIONS',
            '/RESTARTAPPLICATIONS',
        ],
        close_fds=True,
    )
    os._exit(0)


def _apply_windows_portable(new_exe: Path) -> NoReturn:
    """Windows 便携版替换并重启"""
    # 生成辅助批处理脚本
    swap_script = new_exe.parent / 'swap.cmd'
    swap_script.write_text(
        '@echo off\n'
        ':wait\n'
        'tasklist /FI "PID eq %1" | find "%1" >nul && (timeout /t 1 /nobreak >nul & goto wait)\n'
        'move /Y "%~3" "%~2"\n'
        'start "" "%~2"\n'
        '(goto) 2>nul & del "%~f0"\n',
        encoding='gbk',
    )

    # 启动脚本（分离进程）
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    DETACHED_PROCESS = 0x00000008

    subprocess.Popen(
        ['cmd', '/c', 'start', '', '/min', str(swap_script), str(os.getpid()), sys.executable, str(new_exe)],
        creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
        close_fds=True,
    )

    os._exit(0)


def _apply_macos_dmg(dmg_path: Path) -> NoReturn:
    """macOS DMG 自动安装"""
    try:
        # 挂载 DMG
        result = subprocess.run(
            ['hdiutil', 'attach', '-nobrowse', '-quiet', '-plist', str(dmg_path)],
            capture_output=True,
            check=True,
        )

        # 解析挂载点
        if not plistlib:
            raise RuntimeError('plistlib 不可用')

        plist_data = plistlib.loads(result.stdout)
        mount_point = None
        for entity in plist_data.get('system-entities', []):
            if entity.get('mount-point'):
                mount_point = entity['mount-point']
                break

        if not mount_point:
            raise RuntimeError('无法解析 DMG 挂载点')

        # 复制到 /Applications
        app_name = '纸研社.app'
        source = os.path.join(mount_point, app_name)
        target = f'/Applications/{app_name}'

        try:
            subprocess.run(['ditto', source, target], check=True)
            # 移除 Gatekeeper 隔离
            subprocess.run(['xattr', '-dr', 'com.apple.quarantine', target], check=False)
            # 卸载 DMG
            subprocess.run(['hdiutil', 'detach', '-quiet', mount_point], check=False)
            # 启动新版本
            subprocess.Popen(['open', target])
            os._exit(0)

        except subprocess.CalledProcessError:
            # /Applications 写入失败，降级为手动拖拽
            subprocess.run(['hdiutil', 'detach', '-quiet', mount_point], check=False)
            subprocess.Popen(['open', str(dmg_path)])
            os._exit(0)

    except Exception:
        # 任何错误都降级为打开 DMG
        subprocess.Popen(['open', str(dmg_path)])
        os._exit(0)


def _apply_linux_appimage(new_appimage: Path) -> NoReturn:
    """Linux AppImage 替换并重启"""
    current_appimage = os.environ.get('APPIMAGE')
    if not current_appimage:
        raise RuntimeError('APPIMAGE 环境变量不存在')

    # 替换文件
    shutil.move(str(new_appimage), current_appimage)
    os.chmod(current_appimage, 0o755)

    # 启动新版本
    subprocess.Popen([current_appimage], start_new_session=True)
    os._exit(0)
