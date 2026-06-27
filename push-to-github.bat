@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ========================================
echo   GitHub 一键推送脚本
echo ========================================
echo.

REM 设置仓库地址
set REPO_URL=https://github.com/qingshanjiluo/zzhxmusic
set BRANCH=main

echo 仓库地址: %REPO_URL%
echo 分支: %BRANCH%
echo.

REM 检查 Git 是否安装
git --version > nul 2>&1
if errorlevel 1 (
    echo [错误] 未安装 Git
    pause
    exit /b 1
)

REM 检查是否已初始化 Git
if not exist .git (
    echo [信息] 初始化 Git 仓库...
    git init
)

REM 添加所有文件
echo [信息] 添加所有文件...
git add .

REM 检查是否有更改
set HAS_CHANGES=0
for /f "delims=" %%i in ('git status --porcelain') do set HAS_CHANGES=1

if !HAS_CHANGES!==0 (
    echo [信息] 没有需要提交的更改
) else (
    REM 提交更改
    echo [信息] 提交更改...
    set /p COMMIT_MSG="请输入提交信息 (默认: Update: 批量音乐下载工具): "
    if "!COMMIT_MSG!"=="" set COMMIT_MSG=Update: 批量音乐下载工具
    git commit -m "!COMMIT_MSG!"
    if errorlevel 1 (
        echo [错误] 提交失败
        pause
        exit /b 1
    )
    echo [成功] 提交完成
)

REM 添加远程仓库
if not exist .git\refs\remotes\origin (
    echo [信息] 添加远程仓库...
    git remote add origin %REPO_URL%
)

REM 先拉取远程更新（解决冲突）
echo [信息] 拉取远程更新...
git pull origin %BRANCH% --rebase

if errorlevel 1 (
    echo [警告] 拉取远程更新失败，尝试合并...
    git pull origin %BRANCH% --allow-unrelated-histories
    if errorlevel 1 (
        echo [错误] 合并失败，请手动解决冲突
        pause
        exit /b 1
    )
)

REM 推送到 GitHub
echo [信息] 推送到 GitHub...
git push -u origin %BRANCH%

if errorlevel 1 (
    echo.
    echo [错误] 推送失败！
    echo.
    echo 可能的原因:
    echo   1. 网络连接问题
    echo   2. 没有权限访问该仓库
    echo   3. 远程仓库存在冲突
    echo.
    echo 尝试强制推送? (y/n)
    set /p FORCE_PUSH=""
    if /i "!FORCE_PUSH!"=="y" (
        echo [信息] 强制推送...
        git push -u origin %BRANCH% --force
        if errorlevel 1 (
            echo [错误] 强制推送也失败了
            pause
            exit /b 1
        )
    ) else (
        echo [信息] 请手动解决冲突后再次运行此脚本
        pause
        exit /b 1
    )
)

echo.
echo ========================================
echo   ✅ 推送成功！
echo ========================================
echo.
echo 仓库地址: %REPO_URL%
echo.
pause
