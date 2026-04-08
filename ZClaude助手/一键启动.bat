@echo off
:: 强制将工作目录切换到当前bat文件所在的目录（非常关键，防止路径错乱）
cd /d "%~dp0"

:: 设置编码为UTF-8，防止中文乱码
chcp 65001 >nul
title ZenMux AI 助手启动程序
color 0A

echo =========================================
echo       欢迎使用 ZenMux AI 智能助手
echo =========================================
echo.

:: 1. 检查是否安装了Python
python --version >nul 2>&1
if %errorlevel% neq 0 goto no_python

:: 2. 检查并创建虚拟环境
if not exist "venv" (
    echo [1/3] 首次运行，正在为您创建独立的运行环境，请耐心等待1-2分钟...
    python -m venv venv
    if %errorlevel% neq 0 goto venv_error
)

:: 3. 激活虚拟环境
call venv\Scripts\activate.bat
if %errorlevel% neq 0 goto activate_error

:: 4. 检查并安装依赖包
echo [2/3] 正在检查并安装必要组件 (如需下载可能需要一点时间)...
python -m pip install --upgrade pip -q
pip install -r requirements.txt
if %errorlevel% neq 0 goto pip_error

:: 5. 启动 Streamlit 应用
echo.
echo [3/3] 启动成功！正在浏览器中打开...
echo.
echo 注意：请不要关闭此黑框窗口！关闭此窗口会导致 AI 助手断开连接。
echo.

streamlit run app.py

:: 如果运行结束或手动停止，让窗口停住
pause
exit

:: ================= 错误处理区 =================
:no_python
color 0C
echo [错误] 未检测到 Python 环境！
echo 请先安装 Python (请前往 https://www.python.org/downloads/ 下载)
echo 安装时务必勾选底部的 "Add Python.exe to PATH" !!!
pause
exit

:venv_error
color 0C
echo [错误] 创建虚拟环境失败！
echo 请检查您是否有该文件夹的读写权限，或者尝试以管理员身份运行。
pause
exit

:activate_error
color 0C
echo [错误] 激活虚拟环境失败！
pause
exit

:pip_error
color 0C
echo [错误] 安装依赖组件失败！
echo 请检查您的网络连接，或者尝试关闭杀毒软件后重试。
pause
exit