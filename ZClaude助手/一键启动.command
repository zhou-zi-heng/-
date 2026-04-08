#!/bin/bash

# 强制将工作目录切换到当前脚本所在的目录
cd "$(dirname "$0")"

echo "========================================="
echo "       欢迎使用 ZenMux AI 智能助手 (Mac版)"
echo "========================================="
echo ""

# 1. 检查是否安装了 Python 3 (Mac 自带 python3 命令)
if ! command -v python3 &> /dev/null; then
    echo "❌ [错误] 未检测到 Python 3 环境！"
    echo "请前往 https://www.python.org/downloads/mac-osx/ 下载安装包并安装。"
    echo "按回车键退出..."
    read
    exit 1
fi

# 2. 检查并创建虚拟环境
if [ ! -d "venv" ]; then
    echo "⏳ [1/3] 首次运行，正在为您创建独立的运行环境，请耐心等待1-2分钟..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "❌ [错误] 创建虚拟环境失败！请检查文件夹读写权限。"
        echo "按回车键退出..."
        read
        exit 1
    fi
fi

# 3. 激活虚拟环境
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "❌ [错误] 激活虚拟环境失败！"
    echo "按回车键退出..."
    read
    exit 1
fi

# 4. 检查并安装依赖包
echo "📦 [2/3] 正在检查并安装必要组件 (如需下载可能需要一点时间)..."
python3 -m pip install --upgrade pip -q

# 自动判断：如果有 requirements.txt 就用它，否则直接安装你代码里需要的三个核心库
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    pip install streamlit openai python-docx
fi

if [ $? -ne 0 ]; then
    echo "❌ [错误] 安装依赖组件失败！请检查网络连接。"
    echo "按回车键退出..."
    read
    exit 1
fi

# 5. 启动 Streamlit 应用
echo ""
echo "🚀 [3/3] 启动成功！正在浏览器中打开..."
echo ""
echo "⚠️  注意：请不要关闭此黑框窗口！关闭此窗口会导致 AI 助手断开连接。"
echo ""

# 运行你的 Python 文件 (这里换成了你具体的代码文件名)
streamlit run api实验对话框导出文本优化.py

# 运行结束或手动停止，让窗口停住
echo "按回车键退出..."
read