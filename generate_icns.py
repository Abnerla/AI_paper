#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 logo.png 生成 macOS 所需的 logo.icns 文件。

"""

import os
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("错误：需要安装 Pillow 库")
    print("请运行：pip install pillow")
    sys.exit(1)


def generate_icns(png_path, icns_path):
    """
    从 PNG 文件生成 macOS ICNS 图标文件。

    Args:
        png_path: 源 PNG 文件路径
        icns_path: 目标 ICNS 文件路径
    """
    if not os.path.exists(png_path):
        print(f"错误：找不到源文件 {png_path}")
        sys.exit(1)

    print(f"正在从 {png_path} 生成 {icns_path}...")

    # 加载原始图像
    img = Image.open(png_path)

    # 确保图像为 RGBA 模式
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    # macOS ICNS 需要的尺寸（标准尺寸）
    sizes = [16, 32, 64, 128, 256, 512, 1024]

    # 创建临时目录存放不同尺寸的图标
    iconset_dir = icns_path.replace('.icns', '.iconset')
    os.makedirs(iconset_dir, exist_ok=True)

    try:
        # 生成各种尺寸的图标
        for size in sizes:
            # 标准分辨率
            resized = img.resize((size, size), Image.Resampling.LANCZOS)
            resized.save(os.path.join(iconset_dir, f'icon_{size}x{size}.png'))

            # Retina 分辨率（2x）
            if size <= 512:  # 1024x1024 不需要 2x 版本
                resized_2x = img.resize((size * 2, size * 2), Image.Resampling.LANCZOS)
                resized_2x.save(os.path.join(iconset_dir, f'icon_{size}x{size}@2x.png'))

        # 在 macOS 上使用 iconutil 生成 .icns
        if sys.platform == 'darwin':
            import subprocess
            result = subprocess.run(
                ['iconutil', '-c', 'icns', iconset_dir, '-o', icns_path],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print(f"✓ 成功生成 {icns_path}")
            else:
                print(f"错误：iconutil 执行失败")
                print(result.stderr)
                sys.exit(1)
        else:
            # 非 macOS 系统：使用 Pillow 直接保存为 ICNS
            # 注意：Pillow 的 ICNS 支持有限，建议在 macOS 上生成
            print("警告：当前不在 macOS 系统上，使用 Pillow 生成 ICNS（可能兼容性较差）")
            print("建议在 macOS 系统上运行此脚本以获得最佳兼容性")

            # 保存最大尺寸作为 ICNS
            img_1024 = img.resize((1024, 1024), Image.Resampling.LANCZOS)
            img_1024.save(icns_path, format='ICNS')
            print(f"✓ 已生成 {icns_path}（使用 Pillow）")

    finally:
        # 清理临时 iconset 目录
        import shutil
        if os.path.exists(iconset_dir):
            shutil.rmtree(iconset_dir)
            print(f"✓ 已清理临时目录 {iconset_dir}")


def main():
    # 获取脚本所在目录
    script_dir = Path(__file__).parent

    # 源 PNG 文件和目标 ICNS 文件路径
    png_path = script_dir / 'logo.png'
    icns_path = script_dir / 'logo.icns'

    generate_icns(str(png_path), str(icns_path))

    print("\n完成！")
    print(f"ICNS 文件已生成：{icns_path}")
    print(f"文件大小：{os.path.getsize(icns_path) / 1024:.1f} KB")


if __name__ == '__main__':
    main()
