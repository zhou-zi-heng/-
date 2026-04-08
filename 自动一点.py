import streamlit as st
from openai import OpenAI
import io
import json
from docx import Document

st.set_page_config(page_title="ZenMux 创作者自动化中枢", page_icon="🐙", layout="wide")

# ==========================================
# 1. 状态与默认数据初始化
# ==========================================
DEFAULT_PRESETS = {
    "【小红书】爆款种草图文": [
        "你是一名小红书千万级爆款操盘手。请仔细阅读我上传的参考资料，提取出最吸引人的3个卖点或痛点。不需要写正文，只列出这3个点即可。",
        "很好。现在基于这3个点，结合本次的主题：【{主题}】，为我撰写一篇小红书正文。要求：1. 采用网感极强的闺蜜语气；2. 大量使用 Emoji 🎈✨；3. 采用总分总结构，字数控制在400字左右。",
        "正文很棒。最后，请为这篇正文生成 5 个极具吸引力、带有悬念和冲突感的小红书标题（包含关键词），并在文末附上 8 个相关的热门 Tag。"
    ],
    "【公众号】深度干货长文": [
        "你是一名资深的微信公众号主编。请根据参考资料和主题：【{主题}】，构思一个具有深度洞察和情绪共鸣的文章大纲。要求包含：引言、3个核心论点（带有递进关系）、金句总结。",
        "大纲确认。请用极具逻辑性且通俗易懂的语言，撰写【引言】和【第一个核心论点】。要求字数在800字左右，适当加入排比句增强气势。",
        "请紧跟上文逻辑，继续撰写【第二个核心论点】和【第三个核心论点】。要求字数在1000字左右，通过具体的案例和对比来论证。",
        "最后，请撰写【总结升华段落】，要求能引发读者转发和留言共鸣。并为全文生成 3 个能引发点击欲望的公众号推文标题。"
    ]
}

if "api_key" not in st.session_state: st.session_state.api_key = ""
if "presets" not in st.session_state: st.session_state.presets = DEFAULT_PRESETS
if "messages" not in st.session_state: st.session_state.messages = []
if "file_content" not in st.session_state: st.session_state.file_content = ""

# 自动化控制状态
if "auto_active" not in st.session_state: st.session_state.auto_active = False
if "workflow_steps" not in st.session_state: st.session_state.workflow_steps = []
if "current_step_idx" not in st.session_state: st.session_state.current_step_idx = 0
if "is_interrupted" not in st.session_state: st.session_state.is_interrupted = False
if "last_finish_reason" not in st.session_state: st.session_state.last_finish_reason = ""
if "current_topic" not in st.session_state: st.session_state.current_topic = ""

# ==========================================
# 2. 辅助函数
# ==========================================
def generate_word_doc(messages):
    doc = Document()
    doc.add_heading('创作者自动化生成结果', 0)
    for msg in messages:
        if msg["role"] == "system" or not msg.get("selected", True): continue
        if msg["role"] == "user":
            doc.add_heading("📌 阶段执行指令", level=2)
            doc.add_paragraph(msg["content"])
        else:
            doc.add_paragraph(msg["content"])
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

def stream_generator(api_stream):
    st.session_state.last_finish_reason = "stop"
    for chunk in api_stream:
        if chunk.choices[0].delta.content is not None:
            yield chunk.choices[0].delta.content
        if chunk.choices[0].finish_reason is not None:
            st.session_state.last_finish_reason = chunk.choices[0].finish_reason

# ==========================================
# 3. 全局侧边栏
# ==========================================
with st.sidebar:
    st.header("⚙️ 引擎配置")
    st.session_state.api_key = st.text_input("🔑 API Key", type="password", value=st.session_state.api_key)
    model_name = st.selectbox("🧠 选择模型", ["anthropic/claude-haiku-4.5", "anthropic/claude-sonnet-4.6", "anthropic/claude-opus-4.6"])
    
    st.divider()
    if st.session_state.auto_active:
        st.warning(f"🔄 自动化正在运行中...\n(阶段 {st.session_state.current_step_idx + 1} / {len(st.session_state.workflow_steps)})")
        if st.button("⏹️ 强制中止自动化", use_container_width=True):
            st.session_state.auto_active = False
            st.rerun()

# ==========================================
# 4. 主界面：三大标签页分离工作流
# ==========================================
tab_work, tab_preset, tab_export = st.tabs(["🚀 创作工作台", "📝 账号SOP预设中心", "📦 成果与导出"])

# ------------------------------------------
# TAB 2: SOP 预设中心 (放在前面便于逻辑理解)
# ------------------------------------------
with tab_preset:
    st.markdown("### 🛠️ 定制你的账号运营 SOP (标准作业程序)")
    st.info("💡 你可以在指令中使用 `{主题}` 作为占位符，在工作台启动时会自动替换为你输入的具体内容。")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("现有 SOP 列表")
        selected_preset_edit = st.radio("选择要编辑的 SOP", list(st.session_state.presets.keys()))
        
        st.divider()
        new_preset_name = st.text_input("新建 SOP 名称 (如: 抖音带货文案)")
        if st.button("➕ 创建新 SOP", use_container_width=True):
            if new_preset_name and new_preset_name not in st.session_state.presets:
                st.session_state.presets[new_preset_name] = ["在这里填写第一阶段指令..."]
                st.rerun()
                
        # 导入导出配置
        st.divider()
        preset_json = json.dumps(st.session_state.presets, ensure_ascii=False, indent=2)
        st.download_button("💾 备份所有 SOP 配置", preset_json, "矩阵号SOP预设备份.json", "application/json")
        uploaded_json = st.file_uploader("📂 恢复/导入 SOP 配置", type=["json"])
        if uploaded_json:
            try:
                st.session_state.presets = json.loads(uploaded_json.getvalue().decode("utf-8"))
                st.success("导入成功！请刷新页面。")
            except:
                st.error("配置格式错误！")

    with col2:
        if selected_preset_edit:
            st.subheader(f"编辑: {selected_preset_edit}")
            current_steps = st.session_state.presets[selected_preset_edit]
            
            # 动态生成每个步骤的输入框
            updated_steps = []
            for i, step in enumerate(current_steps):
                st.markdown(f"**阶段 {i+1} 指令**")
                new_step = st.text_area(f"阶段 {i+1}", value=step, height=100, label_visibility="collapsed", key=f"step_{selected_preset_edit}_{i}")
                updated_steps.append(new_step)
                
            col_add, col_del = st.columns(2)
            with col_add:
                if st.button("➕ 增加一个阶段", use_container_width=True):
                    st.session_state.presets[selected_preset_edit].append("请继续补充指令...")
                    st.rerun()
            with col_del:
                if len(current_steps) > 1 and st.button("➖ 移除最后一个阶段", use_container_width=True):
                    st.session_state.presets[selected_preset_edit].pop()
                    st.rerun()
            
            # 保存修改
            st.session_state.presets[selected_preset_edit] = updated_steps
            
            st.divider()
            if st.button("🗑️ 删除此 SOP", type="primary"):
                del st.session_state.presets[selected_preset_edit]
                st.rerun()

# ------------------------------------------
# TAB 1: 创作工作台
# ------------------------------------------
with tab_work:
    col_input, col_chat = st.columns([1, 2.5])
    
    with col_input:
        st.markdown("### ⚙️ 启动参数")
        selected_run_preset = st.selectbox("1. 选择运营账号 SOP", list(st.session_state.presets.keys()))
        input_topic = st.text_input("2. 本次创作主题 (将替换指令中的 {主题})", placeholder="例如：春季敏感肌护肤指南")
        
        uploaded_file = st.file_uploader("3. 投喂参考物料 (可选 TXT/MD)", type=['txt', 'md'])
        if uploaded_file is not None:
            st.session_state.file_content = uploaded_file.getvalue().decode("utf-8")
            st.success("物料已载入")
        else:
            st.session_state.file_content = ""

        if st.button("🚀 启动自动化引擎", type="primary", use_container_width=True):
            if not st.session_state.api_key:
                st.error("请在左侧配置 API Key！")
            elif not input_topic:
                st.error("请输入本次创作主题！")
            else:
                st.session_state.messages = []
                st.session_state.current_topic = input_topic
                # 获取预设指令并替换变量
                raw_steps = st.session_state.presets[selected_run_preset]
                st.session_state.workflow_steps = [step.replace("{主题}", input_topic) for step in raw_steps]
                st.session_state.current_step_idx = 0
                st.session_state.is_interrupted = False
                st.session_state.auto_active = True
                st.rerun()

    with col_chat:
        st.markdown("### 🖥️ 自动化生成监视器")
        
        if not st.session_state.messages and not st.session_state.auto_active:
            st.info("👈 请在左侧配置参数并点击「启动自动化引擎」，或者直接在下方输入框手动聊天。")
            
        client = OpenAI(base_url="https://zenmux.ai/api/v1", api_key=st.session_state.api_key) if st.session_state.api_key else None

        # 渲染历史
        for i, message in enumerate(st.session_state.messages):
            if message["role"] == "system": continue
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                if message["role"] == "assistant":
                    message["selected"] = st.checkbox("☑️ 采纳此段内容进入最终导出", value=message.get("selected", True), key=f"chk_work_{i}")

        # --- 🤖 自动化引擎核心流转逻辑 ---
        if st.session_state.auto_active and client:
            if st.session_state.is_interrupted:
                current_prompt = "⚠️ 注意：刚才的回答因字数上限被截断。请直接接着你上一句话的最后一个字继续输出，不要任何寒暄，不要重复上文。"
            else:
                current_prompt = st.session_state.workflow_steps[st.session_state.current_step_idx]

            # 系统自动发言
            st.session_state.messages.append({"role": "user", "content": current_prompt, "selected": False})
            with st.chat_message("user"):
                st.markdown(f"*(🤖 流水线指令 {st.session_state.current_step_idx + 1})*: {current_prompt}")

            api_messages = []
            if st.session_state.file_content:
                api_messages.append({"role": "system", "content": f"你的背景资料库：\n{st.session_state.file_content}"})
            api_messages.extend([{"role": m["role"], "content": m["content"]} for m in st.session_state.messages])

            with st.chat_message("assistant"):
                try:
                    stream = client.chat.completions.create(model=model_name, messages=api_messages, stream=True)
                    response = st.write_stream(stream_generator(stream))
                    st.session_state.messages.append({"role": "assistant", "content": response, "selected": True})
                    
                    if st.session_state.last_finish_reason == "length":
                        st.session_state.is_interrupted = True
                        st.toast("字数耗尽，自动触发续写补全...", icon="⚠️")
                    else:
                        st.session_state.is_interrupted = False
                        st.session_state.current_step_idx += 1
                        
                        if st.session_state.current_step_idx >= len(st.session_state.workflow_steps):
                            st.session_state.auto_active = False
                            st.toast("🎉 本次运营内容全部生成完毕！请前往「成果与导出」下载。", icon="🎊")
                    st.rerun()
                except Exception as e:
                    st.error(f"引擎中断: {e}")
                    st.session_state.auto_active = False

        # 手动干预输入
        elif prompt := st.chat_input("也可随时打字手动补充指令..."):
            if not client: st.stop()
            st.session_state.messages.append({"role": "user", "content": prompt, "selected": False})
            st.rerun()

# ------------------------------------------
# TAB 3: 成果与导出
# ------------------------------------------
with tab_export:
    st.markdown("### 📦 内容成果打包")
    if not st.session_state.messages:
        st.info("目前还没有生成任何内容。")
    else:
        selected_msgs = [m for m in st.session_state.messages if m["role"] == "assistant" and m.get("selected", True)]
        st.success(f"✅ 自动流水线已执行完毕。已筛选出 {len(selected_msgs)} 个合格的内容段落。")
        
        st.markdown("#### 预览最终拼接内容：")
        final_text = ""
        for m in selected_msgs:
            final_text += m["content"] + "\n\n"
            
        with st.container(border=True):
            st.markdown(final_text)
            
        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("📥 下载为纯文本 (TXT)", final_text, f"{st.session_state.current_topic or '生成内容'}.txt", "text/plain", use_container_width=True)
        with c2:
            st.download_button("📥 下载为排版文档 (Word)", generate_word_doc(st.session_state.messages), f"{st.session_state.current_topic or '生成内容'}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)
