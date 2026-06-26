#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打包脚本 - 使用 PyInstaller 将 zzhxmusic-desktop 打包为 EXE
"""

import os
import sys
import shutil
from pathlib import Path


def clean_build_dirs():
    """清理构建目录"""
    dirs_to_clean = ['build', 'dist', '__pycache__']
    for dir_name in dirs_to_clean:
        dir_path = Path(dir_name)
        if dir_path.exists():
            shutil.rmtree(dir_path)
            print(f"已清理: {dir_path}")
    
    # 清理 .spec 文件
    for spec_file in Path('.').glob('*.spec'):
        spec_file.unlink()
        print(f"已清理: {spec_file}")


def build_exe():
    """构建 EXE"""
    print("=" * 50)
    print("开始构建 zzhxmusic-desktop EXE")
    print("=" * 50)
    
    # 检查 PyInstaller 是否安装
    try:
        import PyInstaller
    except ImportError:
        print("错误: 未安装 PyInstaller")
        print("请运行: pip install pyinstaller")
        sys.exit(1)
    
    # 清理旧构建
    clean_build_dirs()
    
    # 构建命令
    # --onefile: 打包成单个 EXE
    # --windowed: 不显示控制台窗口
    # --name: 输出文件名
    # --icon: 图标文件（如果有）
    # --add-data: 添加额外数据文件
    
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--windowed',
        '--name', 'zzhxmusic',
        '--clean',
        '--noconfirm',
        'src/main.py'
    ]
    
    # 添加图标（如果存在）
    icon_path = Path('resources/icon.ico')
    if icon_path.exists():
        cmd.extend(['--icon', str(icon_path)])
    
    # 添加隐藏导入
    cmd.extend([
        '--hidden-import', 'PyQt6',
        '--hidden-import', 'musicdl',
        '--hidden-import', 'requests',
    ])
    
    print("\n执行命令:")
    print(' '.join(cmd))
    print("\n开始打包，这可能需要几分钟...")
    
    # 执行打包
    import subprocess
    result = subprocess.run(cmd, capture_output=False)
    
    if result.returncode == 0:
        print("\n" + "=" * 50)
        print("✅ 打包成功!")
        print("=" * 50)
        print(f"\nEXE 文件位置: {Path('dist/zzhxmusic.exe').absolute()}")
        
        # 显示文件大小
        exe_path = Path('dist/zzhxmusic.exe')
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"文件大小: {size_mb:.2f} MB")
    else:
        print("\n❌ 打包失败，请检查错误信息")
        sys.exit(1)


def create_build_bat():
    """创建 Windows 批处理构建脚本"""
    bat_content = """@echo off
chcp 65001 > nul
echo ========================================
echo zzhxmusic-desktop 构建脚本
echo ========================================
echo.

REM 检查 Python
python --version > nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到 Python
    pause
    exit /b 1
)

REM 安装依赖
echo 安装依赖...
pip install -r requirements.txt
pip install pyinstaller

REM 执行打包
echo.
echo 开始打包...
python build_exe.py

if errorlevel 1 (
    echo.
    echo 打包失败！
    pause
    exit /b 1
)

echo.
echo 打包完成！EXE 文件位于 dist\zzhxmusic.exe
echo.
pause
"""
    
    with open('build.bat', 'w', encoding='gbk') as f:
        f.write(bat_content)
    print("已创建: build.bat")


def create_build_ps1():
    """创建 PowerShell 构建脚本"""
    ps_content = """# zzhxmusic-desktop 构建脚本 (PowerShell)
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "zzhxmusic-desktop 构建脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查 Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "错误: 未找到 Python" -ForegroundColor Red
    Read-Host "按 Enter 退出"
    exit 1
}

# 安装依赖
Write-Host ""
Write-Host "安装依赖..." -ForegroundColor Yellow
pip install -r requirements.txt
pip install pyinstaller

# 执行打包
Write-Host ""
Write-Host "开始打包..." -ForegroundColor Yellow
python build_exe.py

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "打包完成！EXE 文件位于 dist\zzhxmusic.exe" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "打包失败！" -ForegroundColor Red
}

Read-Host "按 Enter 退出"
"""
    
    with open('build.ps1', 'w', encoding='utf-8') as f:
        f.write(ps_content)
    print("已创建: build.ps1")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='zzhxmusic-desktop 打包工具')
    parser.add_argument('--clean', action='store_true', help='仅清理构建目录')
    parser.add_argument('--scripts', action='store_true', help='生成构建脚本 (build.bat, build.ps1)')
    
    args = parser.parse_args()
    
    if args.clean:
        clean_build_dirs()
        print("清理完成")
        return
    
    if args.scripts:
        create_build_bat()
        create_build_ps1()
        print("构建脚本已生成")
        return
    
    # 默认执行打包
    build_exe()


if __name__ == '__main__':
    main()
