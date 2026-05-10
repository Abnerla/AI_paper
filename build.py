# -*- coding: utf-8 -*-
import argparse
import os
import platform
import re
import shutil
import subprocess
import sys

# 确保 CI 环境下中文输出不报错
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

APP_NAME = 'AI_Paper'
APP_PACKAGE_ID = 'paperlab-zhiyanshe'
APP_DESCRIPTION = 'AI 智能论文工作台'
APP_HOMEPAGE = 'https://github.com/Abnerla/AI_paper'
APP_MAINTAINER = 'PaperLab <1444170707@qq.com>'
SPEC_FILE = '纸研社.spec'
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, 'dist')
BUILD_DIR = os.path.join(PROJECT_DIR, 'build')
VERSION_PATTERN = re.compile(r'^v?(?P<version>\d+\.\d+\.\d+)$')
DEB_ARCH_MAP = {
    'x86_64': 'amd64',
    'amd64': 'amd64',
    'aarch64': 'arm64',
    'arm64': 'arm64',
}
RPM_ARCH_MAP = {
    'x86_64': 'x86_64',
    'amd64': 'x86_64',
    'aarch64': 'aarch64',
    'arm64': 'aarch64',
}
LINUX_DESKTOP_FILE_CANDIDATES = (
    f'{APP_NAME}.desktop',
    '纸研社.desktop',
)


def read_command_output(command):
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_DIR,
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
        )
    except Exception:
        return ''
    return completed.stdout.strip()


def normalize_version(value):
    if not value:
        return None

    candidate = value.strip()
    if candidate.startswith('refs/tags/'):
        candidate = candidate[len('refs/tags/'):]

    match = VERSION_PATTERN.fullmatch(candidate)
    if not match:
        return None

    version = match.group('version')
    return version, f'v{version}'


def resolve_version():
    candidates = [
        os.environ.get('BUILD_VERSION'),
        os.environ.get('GITHUB_REF_NAME'),
    ]

    point_tags = read_command_output(['git', 'tag', '--points-at', 'HEAD'])
    if point_tags:
        candidates.extend(line.strip() for line in point_tags.splitlines() if line.strip())

    latest_tag = read_command_output(['git', 'describe', '--tags', '--abbrev=0'])
    if latest_tag:
        candidates.append(latest_tag)

    for candidate in candidates:
        normalized = normalize_version(candidate)
        if normalized:
            return normalized

    return '0.0.0', 'v0.0.0'


APP_VERSION, APP_VERSION_TAG = resolve_version()


def require_path(path, description):
    if not os.path.exists(path):
        raise FileNotFoundError(f'[build] Missing {description}: {path}')
    return path


def require_command(name):
    command = shutil.which(name)
    if not command:
        raise FileNotFoundError(f'[build] Missing dependency: {name}')
    return command


def write_text_file(path, content, executable=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as file:
        file.write(content)
    if executable:
        os.chmod(path, 0o755)


def resolve_linux_desktop_source():
    linux_installer_dir = os.path.join(PROJECT_DIR, 'installers', 'linux')
    for filename in LINUX_DESKTOP_FILE_CANDIDATES:
        candidate = os.path.join(linux_installer_dir, filename)
        if os.path.isfile(candidate):
            return candidate
    expected = ', '.join(LINUX_DESKTOP_FILE_CANDIDATES)
    raise FileNotFoundError(f'[build] Missing Linux desktop file. Expected one of: {expected}')


def build_linux_desktop_content(source_path):
    with open(source_path, 'r', encoding='utf-8') as file:
        lines = file.read().splitlines()

    replacements = {
        'Exec': APP_NAME,
        'Icon': APP_NAME,
        'StartupWMClass': APP_NAME,
    }
    seen_keys = set()
    normalized_lines = []

    for line in lines:
        replaced = False
        for key, value in replacements.items():
            if line.startswith(f'{key}='):
                normalized_lines.append(f'{key}={value}')
                seen_keys.add(key)
                replaced = True
                break
        if not replaced:
            normalized_lines.append(line)

    for key, value in replacements.items():
        if key not in seen_keys:
            normalized_lines.append(f'{key}={value}')

    return '\n'.join(normalized_lines) + '\n'


def write_linux_desktop_file(source_path, target_path):
    content = build_linux_desktop_content(source_path)
    write_text_file(target_path, content)


def get_linux_paths():
    executable_path = require_path(os.path.join(DIST_DIR, APP_NAME), 'Linux executable')
    desktop_source = resolve_linux_desktop_source()
    icon_source = require_path(os.path.join(PROJECT_DIR, 'logo.png'), 'Linux icon')
    return executable_path, desktop_source, icon_source


def get_linux_architectures():
    machine = platform.machine().lower()
    deb_arch = DEB_ARCH_MAP.get(machine)
    rpm_arch = RPM_ARCH_MAP.get(machine)
    if not deb_arch or not rpm_arch:
        raise ValueError(f'[build] Unsupported Linux architecture: {machine}')
    return deb_arch, rpm_arch


def create_linux_payload():
    executable_path, desktop_source, icon_source = get_linux_paths()
    payload_root = os.path.join(BUILD_DIR, 'linux-payload')

    if os.path.isdir(payload_root):
        shutil.rmtree(payload_root)

    app_dir = os.path.join(payload_root, 'opt', APP_PACKAGE_ID)
    installed_executable = os.path.join(app_dir, APP_NAME)
    wrapper_path = os.path.join(payload_root, 'usr', 'bin', APP_NAME)
    desktop_target = os.path.join(payload_root, 'usr', 'share', 'applications', f'{APP_NAME}.desktop')
    icon_target = os.path.join(payload_root, 'usr', 'share', 'pixmaps', f'{APP_NAME}.png')

    os.makedirs(app_dir, exist_ok=True)
    shutil.copy2(executable_path, installed_executable)
    os.chmod(installed_executable, 0o755)

    wrapper_content = f"""#!/bin/sh
exec "/opt/{APP_PACKAGE_ID}/{APP_NAME}" "$@"
"""
    write_text_file(wrapper_path, wrapper_content, executable=True)

    write_linux_desktop_file(desktop_source, desktop_target)

    os.makedirs(os.path.dirname(icon_target), exist_ok=True)
    shutil.copy2(icon_source, icon_target)

    return payload_root


def detect_platform():
    if sys.platform == 'win32':
        return 'windows'
    elif sys.platform == 'darwin':
        return 'macos'
    else:
        return 'linux'


def build_release_basename(platform_name=None):
    normalized_platform = str(platform_name or detect_platform()).strip().lower()
    return f'{APP_NAME}-{APP_VERSION_TAG}-{normalized_platform}'


def build_release_path(extension, *, platform_name=None, suffix=''):
    basename = build_release_basename(platform_name=platform_name)
    if suffix:
        basename = f'{basename}-{suffix}'
    return os.path.join(DIST_DIR, f'{basename}{extension}')


def copy_release_file(source_path, extension, *, platform_name=None, suffix=''):
    source_path = require_path(source_path, 'release source file')
    output_path = build_release_path(extension, platform_name=platform_name, suffix=suffix)
    if os.path.exists(output_path):
        os.remove(output_path)
    shutil.copy2(source_path, output_path)
    print(f'[build] Release asset prepared: {output_path}')
    return output_path


def run_pyinstaller():
    """使用跨平台 spec 调用 PyInstaller。"""
    env = os.environ.copy()
    env['APP_VERSION'] = APP_VERSION
    env['APP_VERSION_TAG'] = APP_VERSION_TAG
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--clean',
        '--noconfirm',
        '--distpath', DIST_DIR,
        '--workpath', BUILD_DIR,
        SPEC_FILE,
    ]
    print(f'[build] Running: {" ".join(cmd)}')
    subprocess.check_call(cmd, cwd=PROJECT_DIR, env=env)
    print(f'[build] PyInstaller finished. Output in {DIST_DIR}')


def create_dmg():
    """生成 macOS 的 .dmg 安装程序。"""
    app_path = os.path.join(DIST_DIR, f'{APP_NAME}.app')

    # 检测当前架构
    machine = platform.machine().lower()
    if machine in ('x86_64', 'amd64'):
        arch_suffix = 'intel'
    elif machine in ('arm64', 'aarch64'):
        arch_suffix = 'apple-silicon'
    else:
        arch_suffix = machine

    dmg_path = build_release_path('.dmg', platform_name='macos', suffix=arch_suffix)

    if not os.path.isdir(app_path):
        raise FileNotFoundError(f'[build] Missing app bundle: {app_path}')

    if os.path.exists(dmg_path):
        os.remove(dmg_path)

    cmd = [
        'hdiutil', 'create',
        '-volname', APP_NAME,
        '-srcfolder', app_path,
        '-ov',
        '-format', 'UDZO',
        dmg_path,
    ]
    print(f'[build] Creating DMG for {arch_suffix}: {dmg_path}')
    subprocess.check_call(cmd)
    print(f'[build] DMG created: {dmg_path}')

    # 同时创建不带架构后缀的通用文件名（向后兼容）
    generic_dmg_path = build_release_path('.dmg', platform_name='macos')
    if generic_dmg_path != dmg_path:
        shutil.copy2(dmg_path, generic_dmg_path)
        print(f'[build] Generic DMG created: {generic_dmg_path}')


def create_appimage():
    """生成 Linux 的 AppImage 安装程序。"""
    executable_path, desktop_source, icon_source = get_linux_paths()
    appimage_tool = require_command('appimagetool')

    appdir = os.path.join(BUILD_DIR, f'{APP_NAME}.AppDir')
    if os.path.isdir(appdir):
        shutil.rmtree(appdir)
    os.makedirs(os.path.join(appdir, 'usr', 'bin'), exist_ok=True)

    shutil.copy2(executable_path, os.path.join(appdir, 'usr', 'bin', APP_NAME))
    shutil.copy2(icon_source, os.path.join(appdir, f'{APP_NAME}.png'))
    write_linux_desktop_file(desktop_source, os.path.join(appdir, f'{APP_NAME}.desktop'))

    apprun_content = """#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/""" + APP_NAME + """ "$@"
"""
    apprun_path = os.path.join(appdir, 'AppRun')
    with open(apprun_path, 'w', encoding='utf-8') as f:
        f.write(apprun_content)
    os.chmod(apprun_path, 0o755)

    output_path = build_release_path('.AppImage', platform_name='linux')
    cmd = [appimage_tool, appdir, output_path]
    print(f'[build] Creating AppImage: {output_path}')
    subprocess.check_call(cmd)
    print(f'[build] AppImage created: {output_path}')


def create_deb_package():
    """生成 Linux 的 .deb 安装包。"""
    dpkg_deb = require_command('dpkg-deb')
    deb_arch, _rpm_arch = get_linux_architectures()
    payload_root = create_linux_payload()
    package_root = os.path.join(BUILD_DIR, 'linux-deb', APP_PACKAGE_ID)

    if os.path.isdir(package_root):
        shutil.rmtree(package_root)
    shutil.copytree(payload_root, package_root)

    control_content = f"""Package: {APP_PACKAGE_ID}
Version: {APP_VERSION}
Section: utils
Priority: optional
Architecture: {deb_arch}
Maintainer: {APP_MAINTAINER}
Homepage: {APP_HOMEPAGE}
Description: {APP_DESCRIPTION}
 AI smart paper workbench.
"""
    write_text_file(os.path.join(package_root, 'DEBIAN', 'control'), control_content)

    output_path = build_release_path('.deb', platform_name='linux', suffix=deb_arch)
    cmd = [dpkg_deb]
    if '--root-owner-group' in read_command_output([dpkg_deb, '--help']):
        cmd.append('--root-owner-group')
    cmd.extend(['--build', package_root, output_path])
    print(f'[build] Creating DEB: {output_path}')
    subprocess.check_call(cmd)
    print(f'[build] DEB created: {output_path}')


def create_rpm_package():
    """生成 Linux 的 .rpm 安装包。"""
    rpmbuild = require_command('rpmbuild')
    _deb_arch, rpm_arch = get_linux_architectures()
    payload_root = create_linux_payload()
    rpm_root = os.path.join(BUILD_DIR, 'linux-rpm')
    spec_dir = os.path.join(rpm_root, 'SPECS')

    if os.path.isdir(rpm_root):
        shutil.rmtree(rpm_root)

    for directory_name in ('BUILD', 'BUILDROOT', 'RPMS', 'SOURCES', 'SPECS', 'SRPMS'):
        os.makedirs(os.path.join(rpm_root, directory_name), exist_ok=True)

    spec_content = f"""%global debug_package %{{nil}}
%global __strip /bin/true
%global __objdump /bin/true
Name: {APP_PACKAGE_ID}
Version: {APP_VERSION}
Release: 1
Summary: AI smart paper workbench
License: MIT
URL: {APP_HOMEPAGE}
BuildArch: {rpm_arch}
AutoReqProv: no

%description
AI smart paper workbench.

%prep

%build

%install
rm -rf %{{buildroot}}
install -d %{{buildroot}}
cp -a "{payload_root}/." "%{{buildroot}}/"

%files
%attr(0755,root,root) /opt/{APP_PACKAGE_ID}/{APP_NAME}
%attr(0755,root,root) /usr/bin/{APP_NAME}
%attr(0644,root,root) /usr/share/applications/{APP_NAME}.desktop
%attr(0644,root,root) /usr/share/pixmaps/{APP_NAME}.png
"""
    spec_path = os.path.join(spec_dir, f'{APP_PACKAGE_ID}.spec')
    write_text_file(spec_path, spec_content)

    print('[build] Creating RPM package')
    subprocess.check_call([
        rpmbuild,
        '--define', f'_topdir {rpm_root}',
        '--define', '_build_name_fmt %{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}.rpm',
        '-bb',
        spec_path,
    ])

    built_rpm_root = os.path.join(rpm_root, 'RPMS')
    built_rpm_name = f'{APP_PACKAGE_ID}-{APP_VERSION}-1.{rpm_arch}.rpm'
    built_rpm_path = None
    for current_root, _dirnames, filenames in os.walk(built_rpm_root):
        if built_rpm_name in filenames:
            built_rpm_path = os.path.join(current_root, built_rpm_name)
            break
    if not built_rpm_path:
        raise FileNotFoundError(f'[build] RPM output not found in {built_rpm_root}')

    output_path = build_release_path('.rpm', platform_name='linux', suffix=rpm_arch)
    shutil.copy2(built_rpm_path, output_path)
    print(f'[build] RPM created: {output_path}')


def create_linux_installers():
    """生成 Linux 安装包。"""
    create_appimage()
    create_deb_package()
    create_rpm_package()


def create_inno_setup_installer():
    """使用 Inno Setup 生成 Windows 安装程序。"""
    iss_path = os.path.join(PROJECT_DIR, 'installers', 'windows_setup.iss')
    if not os.path.isfile(iss_path):
        raise FileNotFoundError('[build] Missing installer script: installers/windows_setup.iss')

    iscc = None
    for candidate in [
        shutil.which('ISCC'),
        r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        r'C:\Program Files\Inno Setup 6\ISCC.exe',
    ]:
        if candidate and os.path.isfile(candidate):
            iscc = candidate
            break

    if not iscc:
        raise FileNotFoundError('[build] Missing dependency: Inno Setup (ISCC)')

    cmd = [iscc, f'/DMyAppVersion={APP_VERSION}', iss_path]
    print('[build] Creating Windows installer with Inno Setup')
    subprocess.check_call(cmd)
    print('[build] Windows installer created')


def create_windows_release_executable():
    """生成带版本号和平台标识的 Windows 可执行文件副本。"""
    executable_path = os.path.join(DIST_DIR, f'{APP_NAME}.exe')
    return copy_release_file(executable_path, '.exe', platform_name='windows')


def main():
    parser = argparse.ArgumentParser(description=f'{APP_NAME} cross-platform build script')
    parser.add_argument('--installer', action='store_true', help='Also create platform installer')
    parser.add_argument('--clean', action='store_true', help='Clean build/dist directories first')
    args = parser.parse_args()

    platform = detect_platform()
    print(f'[build] Platform: {platform}')
    print(f'[build] App: {APP_NAME} {APP_VERSION_TAG}')

    if args.clean:
        for d in [DIST_DIR, BUILD_DIR]:
            if os.path.isdir(d):
                print(f'[build] Cleaning {d}')
                shutil.rmtree(d)

    run_pyinstaller()
    if platform == 'windows':
        create_windows_release_executable()

    if args.installer:
        if platform == 'windows':
            create_inno_setup_installer()
        elif platform == 'macos':
            create_dmg()
        elif platform == 'linux':
            create_linux_installers()

    print(f'[build] Done! Output in {DIST_DIR}')


if __name__ == '__main__':
    main()
