import streamlit as st
from openai import OpenAI
import io
import json
import requests
from docx import Document

# ==========================================
# 页面全局设置与 CSS 美化
# ==========================================
st.set_page_config(page_title="ZenMux Agentic 工作台", page_icon="🐙", layout="wide")
st.markdown("""
    <style>
    /* 美化侧边栏导航按钮 */
    .stButton>button { border-radius: 8px; font-weight: bold; transition: all 0.3s; }
    /* 聊天框底边距微调 */
    .stChatInput { padding-bottom: 20px; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 1. 默认数据与状态初始化
# ==========================================
DEFAULT_PROFILES = [
    {
        "name": "ZenMux 官方",
        "base_url": "https://zenmux.ai/api/v1",
        "api_key": "",
        "model": "anthropic/claude-sonnet-4.6",
        "use_temperature": True, "temperature": 0.7,
        "use_max_tokens": True, "max_tokens": 4096,
        "use_top_p": False, "top_p": 1.0,  
        "use_frequency_penalty": False, "frequency_penalty": 0.0,
        "global_system_prompt": "你是一个强大的 AI 助手。请直接回答问题，不要输出废话。"
    }
]

DEFAULT_SOPS = {
    "【演示】长篇小说生成": {
        "steps": [
            {"prompt": "构思一本小说的世界观和3个主要人物。不要写正文。", "loop": 1, "reference": ""},
            {"prompt": "根据世界观，详细撰写第【{循环索引}】章的内容。", "loop": 3, "reference": ""}
        ],
        "triggers": [
            {"type": "terminate", "keyword": "全文完", "action": ""}
        ]
    }
}

def init_state(key, default_val):
    if key not in st.session_state:
        st.session_state[key] = default_val

init_state("profiles", DEFAULT_PROFILES)
init_state("active_profile_idx", 0)
init_state("sops", DEFAULT_SOPS)
init_state("free_chat_msgs", [])
init_state("current_page", "🤖 自动化流水线")

init_state("auto_engine", {
    "is_running": False, "is_finished": False, "messages": [],
    "sop_name": "", "topic": "", "global_file": "",
    "current_step_idx": 0, "current_loop_idx": 1,
    "pending_instruction": "", "last_finish_reason": ""
})

# ==========================================
# 2. 核心底层函数
# ==========================================
def get_client():
    profile = st.session_state.profiles[st.session_state.active_profile_idx]
    url = profile["base_url"].strip() or "https://api.openai.com/v1"
    key = profile["api_key"].strip()
    return OpenAI(base_url=url, api_key=key), profile

def build_api_kwargs(profile, api_msgs):
    """根据用户的勾选状态，动态构建 API 请求参数"""
    kwargs = {"model": profile["model"], "messages": api_msgs, "stream": True}
    if profile.get("use_temperature", True): kwargs["temperature"] = profile.get("temperature", 0.7)
    if profile.get("use_max_tokens", True): kwargs["max_tokens"] = profile.get("max_tokens", 4096)
    if profile.get("use_top_p", False): kwargs["top_p"] = profile.get("top_p", 1.0)
    if profile.get("use_frequency_penalty", False): kwargs["frequency_penalty"] = profile.get("frequency_penalty", 0.0)
    return kwargs

def fetch_models(base_url, api_key):
    try:
        url = (base_url.strip() or "https://api.openai.com/v1") + "/models"
        headers = {"Authorization": f"Bearer {api_key.strip()}"}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            return sorted([m["id"] for m in resp.json().get("data", [])])
    except: pass
    return []

def stream_generator(api_stream):
    """拦截流，获取结束原因"""
    st.session_state.auto_engine["last_finish_reason"] = "stop"
    for chunk in api_stream:
        if chunk.choices and chunk.choices[0].delta.content is not None:
            yield chunk.choices[0].delta.content
        if chunk.choices and chunk.choices[0].finish_reason is not None:
            st.session_state.auto_engine["last_finish_reason"] = chunk.choices[0].finish_reason

def generate_word_doc(messages, is_auto=False):
    doc = Document()
    doc.add_heading('AI 生成文档', 0)
    for msg in messages:
        if msg["role"] == "system" or not msg.get("selected", True): continue
        if msg["role"] == "user":
            doc.add_heading("📌 指令" if is_auto else "🧑‍💻 我", level=2)
            doc.add_paragraph(msg["content"])
        else:
            if not is_auto: doc.add_heading("🤖 AI", level=2)
            doc.add_paragraph(msg["content"])
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

# ==========================================
# 3. 全局侧边栏导航 (大型 App-like 按钮)
# ==========================================
with st.sidebar:
    col_img, col_txt = st.columns([1, 3])
    with col_img: st.image("https://api.iconify.design/fluent-emoji:octopus.svg?width=80", width=50)
    with col_txt: st.header("控制中枢")
    st.write("") 
    
    pages = ["🤖 自动化流水线", "💬 自由聊天", "📝 SOP预设中心", "⚙️ 引擎配置"]
    for p in pages:
        btn_type = "primary" if st.session_state.current_page == p else "secondary"
        if st.button(p, use_container_width=True, type=btn_type):
            st.session_state.current_page = p
            st.rerun()

    active_p = st.session_state.profiles[st.session_state.active_profile_idx]
    st.divider()
    st.caption(f"🟢 **当前引擎**: {active_p['name']}\n\n🧠 **当前模型**: {active_p['model']}")
    
    # 自由聊天专属操作移入侧边栏
    if st.session_state.current_page == "💬 自由聊天":
        st.divider()
        st.header("🛠️ 聊天操作区")
        if st.button("🗑️ 清空当前对话", use_container_width=True):
            st.session_state.free_chat_msgs = []
            st.rerun()
        if st.session_state.free_chat_msgs:
            txt_content = "".join([f"{'我' if m['role']=='user' else 'AI'}:\n{m['content']}\n\n{'-'*40}\n\n" for m in st.session_state.free_chat_msgs if m["role"]!="system"])
            st.download_button("📥 导出 TXT", txt_content, "聊天记录.txt", "text/plain", use_container_width=True)
            st.download_button("📥 导出 Word", generate_word_doc(st.session_state.free_chat_msgs, False), "聊天记录.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)

# ==========================================
# 模块 1: 引擎配置 (支持参数开关勾选)
# ==========================================
if st.session_state.current_page == "⚙️ 引擎配置":
    st.header("⚙️ 引擎高级配置中心")
    col_list, col_edit = st.columns([1, 2.5])
    
    with col_list:
        st.subheader("渠道预设库")
        profile_names = [p["name"] for p in st.session_state.profiles]
        selected_idx = st.radio("当前生效渠道", range(len(profile_names)), format_func=lambda x: profile_names[x], index=st.session_state.active_profile_idx)
        st.session_state.active_profile_idx = selected_idx
        
        if st.button("➕ 新增渠道", use_container_width=True):
            st.session_state.profiles.append(DEFAULT_PROFILES[0].copy())
            st.session_state.profiles[-1]["name"] = f"新渠道 {len(st.session_state.profiles)}"
            st.rerun()
            
        st.divider()
        st.download_button("💾 导出配置库", json.dumps(st.session_state.profiles, ensure_ascii=False, indent=2), "API渠道.json", "application/json")

    with col_edit:
        st.subheader("编辑渠道参数")
        p = st.session_state.profiles[selected_idx]
        
        p["name"] = st.text_input("标签名称", p["name"])
        c1, c2 = st.columns(2)
        with c1: p["base_url"] = st.text_input("Base URL (为空则默认官方)", p["base_url"])
        with c2: p["api_key"] = st.text_input("API Key (秘钥)", p["api_key"], type="password")
            
        c_model, c_btn = st.columns([3, 1])
        with c_model: p["model"] = st.text_input("模型名称 (Model ID)", p["model"])
        with c_btn:
            st.write(""); st.write("")
            if st.button("🔄 获取模型列表"):
                if p["api_key"]:
                    models = fetch_models(p["base_url"], p["api_key"])
                    if models: st.session_state.temp_models = models
        if "temp_models" in st.session_state:
            sel_m = st.selectbox("选择并覆盖模型", ["(不覆盖)"] + st.session_state.temp_models)
            if sel_m != "(不覆盖)": p["model"] = sel_m; del st.session_state.temp_models; st.rerun()
                
        st.markdown("#### 🎛️ 参数动态精调 (打勾生效)")
        st.caption("注：特定模型不支持某些参数组合（如 o1 模型可能报错），请取消相应勾选。")
        sl1, sl2 = st.columns(2)
        with sl1:
            if st.checkbox("🔥 Temperature (温度)", p.get("use_temperature", True), key="chk_temp"):
                p["use_temperature"] = True
                p["temperature"] = st.slider("值", 0.0, 2.0, p.get("temperature", 0.7), 0.1, key="v_temp", label_visibility="collapsed")
            else: p["use_temperature"] = False
            
            if st.checkbox("📏 Max Tokens (最大长度)", p.get("use_max_tokens", True), key="chk_max"):
                p["use_max_tokens"] = True
                p["max_tokens"] = st.slider("值", 512, 16384, p.get("max_tokens", 4096), 512, key="v_max", label_visibility="collapsed")
            else: p["use_max_tokens"] = False

        with sl2:
            if st.checkbox("🎲 Top P (核采样)", p.get("use_top_p", False), key="chk_top"):
                p["use_top_p"] = True
                p["top_p"] = st.slider("值", 0.0, 1.0, p.get("top_p", 1.0), 0.05, key="v_top", label_visibility="collapsed")
            else: p["use_top_p"] = False
            
            if st.checkbox("🚫 Frequency Penalty (防重复)", p.get("use_frequency_penalty", False), key="chk_freq"):
                p["use_frequency_penalty"] = True
                p["frequency_penalty"] = st.slider("值", -2.0, 2.0, p.get("frequency_penalty", 0.0), 0.1, key="v_freq", label_visibility="collapsed")
            else: p["use_frequency_penalty"] = False

        p["global_system_prompt"] = st.text_area("🌍 全局 System Prompt (影响所有对话)", p.get("global_system_prompt", ""))
        
        if len(st.session_state.profiles) > 1:
            if st.button("🗑️ 删除此渠道", type="primary"):
                st.session_state.profiles.pop(selected_idx)
                st.session_state.active_profile_idx = 0
                st.rerun()

# ==========================================
# 模块 2: 自由聊天 (沉浸式布局回归)
# ==========================================
elif st.session_state.current_page == "💬 自由聊天":
    st.title("💬 自由聊天区")
    st.caption("回归纯粹的对话体验。导出、清空等操作已移至左侧边栏。")
    
    # 渲染历史记录
    for msg in st.session_state.free_chat_msgs:
        if msg["role"] == "system": continue
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                with st.expander("📄 复制"): st.code(msg["content"], language="markdown")

    # 输入框在最底端
    if prompt := st.chat_input("输入你想探讨的内容..."):
        if not active_p["api_key"]: st.error("请先在「⚙️ 引擎配置」中填写秘钥！"); st.stop()
            
        st.session_state.free_chat_msgs.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        
        client, profile = get_client()
        api_msgs = []
        if profile.get("global_system_prompt"):
            api_msgs.append({"role": "system", "content": profile["global_system_prompt"]})
        api_msgs.extend([{"role": m["role"], "content": m["content"]} for m in st.session_state.free_chat_msgs])
        
        with st.chat_message("assistant"):
            try:
                kwargs = build_api_kwargs(profile, api_msgs)
                resp = client.chat.completions.create(**kwargs)
                full_resp = st.write_stream(resp)
                st.session_state.free_chat_msgs.append({"role": "assistant", "content": full_resp, "selected": True})
                st.rerun()
            except Exception as e:
                st.error(f"请求失败: {e}")

# ==========================================
# 模块 3: SOP 预设中心 (阶段专属参考文件)
# ==========================================
elif st.session_state.current_page == "📝 SOP预设中心":
    st.header("📝 SOP 工作流设计中心")
    col1, col2 = st.columns([1, 2.5])
    
    with col1:
        st.subheader("SOP 库")
        sop_names = list(st.session_state.sops.keys())
        selected_sop_name = st.radio("选择编辑对象", sop_names) if sop_names else None
        
        if st.button("➕ 创建新 SOP", use_container_width=True):
            name = f"未命名 SOP {len(sop_names)+1}"
            st.session_state.sops[name] = {"steps": [{"prompt": "输入指令...", "loop": 1, "reference": ""}], "triggers": []}
            st.rerun()
            
        st.divider()
        st.download_button("💾 导出矩阵库", json.dumps(st.session_state.sops, ensure_ascii=False, indent=2), "SOP矩阵.json", "application/json")

    with col2:
        if selected_sop_name:
            sop = st.session_state.sops[selected_sop_name]
            st.subheader(f"编辑: {selected_sop_name}")
            
            st.markdown("### 🧩 阶段与循环配置")
            new_steps = []
            for i, step in enumerate(sop["steps"]):
                with st.container(border=True):
                    st.markdown(f"**阶段 {i+1}**")
                    sc1, sc2 = st.columns([4, 1])
                    with sc1: p_val = st.text_area(f"指令内容", step["prompt"], height=60, key=f"p_{i}", label_visibility="collapsed")
                    with sc2: l_val = st.number_input(f"循环", min_value=1, value=step.get("loop", 1), key=f"l_{i}")
                    
                    # 阶段专属参考文件注入区
                    ref_text = step.get("reference", "")
                    with st.expander(f"📁 阶段专属参考资料 (状态: {'已挂载' if ref_text else '未挂载'})"):
                        up_f = st.file_uploader("上传 TXT/MD", key=f"uf_{i}")
                        if up_f: ref_text = up_f.getvalue().decode("utf-8")
                        ref_text = st.text_area("或粘贴文本", ref_text, height=100, key=f"rf_{i}")
                        
                    new_steps.append({"prompt": p_val, "loop": l_val, "reference": ref_text})
            sop["steps"] = new_steps
            
            ca, cb = st.columns(2)
            with ca:
                if st.button("➕ 增加阶段", use_container_width=True):
                    sop["steps"].append({"prompt": "", "loop": 1, "reference": ""}); st.rerun()
            with cb:
                if len(sop["steps"]) > 1 and st.button("➖ 移除末段", use_container_width=True):
                    sop["steps"].pop(); st.rerun()
                    
            st.markdown("### ⚡ 智能触发器 (全局监听)")
            new_triggers = []
            for i, t in enumerate(sop.get("triggers", [])):
                with st.container(border=True):
                    tc1, tc2, tc3 = st.columns([1, 1, 2])
                    with tc1: t_type = st.selectbox("规则", ["terminate", "intervene"], index=0 if t["type"]=="terminate" else 1, format_func=lambda x: "🛑 强制完结" if x=="terminate" else "💬 插嘴干预", key=f"tt_{i}")
                    with tc2: t_kwd = st.text_input("包含关键词", t["keyword"], key=f"tk_{i}")
                    with tc3: t_act = st.text_input("则发送指令", t.get("action", ""), disabled=(t_type=="terminate"), key=f"ta_{i}")
                    new_triggers.append({"type": t_type, "keyword": t_kwd, "action": t_act})
            sop["triggers"] = new_triggers
            if st.button("➕ 添加规则"): sop["triggers"].append({"type": "intervene", "keyword": "", "action": ""}); st.rerun()
            
            st.divider()
            if st.button("🗑️ 删除整个 SOP", type="primary"): del st.session_state.sops[selected_sop_name]; st.rerun()

# ==========================================
# 模块 4: 自动化引擎 (执行核心)
# ==========================================
elif st.session_state.current_page == "🤖 自动化流水线":
    engine = st.session_state.auto_engine
    col_ctrl, col_view = st.columns([1, 2.5])
    
    with col_ctrl:
        st.header("⚙️ 控制台")
        if engine["is_running"]:
            st.warning("⚠️ 引擎运转中...")
            st.progress(min(engine["current_step_idx"] / max(len(st.session_state.sops[engine["sop_name"]]["steps"]), 1), 1.0))
            if st.button("⏹️ 强制急停", type="primary", use_container_width=True): engine["is_running"] = False; st.rerun()
        else:
            sel_sop = st.selectbox("1. 挂载 SOP", list(st.session_state.sops.keys()))
            in_topic = st.text_input("2. 注入 {主题}", placeholder="例如：人工智能")
            up_file = st.file_uploader("3. 挂载全局参考库", type=['txt', 'md'])
            
            if st.button("🚀 点火启动", type="primary", use_container_width=True):
                if not active_p["api_key"]: st.error("缺 API Key！")
                elif not in_topic: st.error("缺主题！")
                else:
                    engine.update({
                        "is_running": True, "is_finished": False, "messages": [],
                        "sop_name": sel_sop, "topic": in_topic,
                        "global_file": up_file.getvalue().decode("utf-8") if up_file else "",
                        "current_step_idx": 0, "current_loop_idx": 1,
                        "pending_instruction": "", "last_finish_reason": ""
                    })
                    st.rerun()
                    
        st.divider()
        if engine["messages"] or engine["is_finished"]:
            st.markdown("### 📦 验收成果")
            sel_msgs = [m for m in engine["messages"] if m["role"] == "assistant" and m.get("selected", True)]
            final_text = "\n\n".join([m["content"] for m in sel_msgs])
            st.download_button("📥 导出拼接全文(TXT)", final_text, f"{engine['topic']}.txt", "text/plain", use_container_width=True)
            st.download_button("📥 导出完整过程(Word)", generate_word_doc(engine["messages"], True), f"{engine['topic']}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)
            if st.button("🧹 清理桌面", use_container_width=True): engine.update({"messages": [], "is_finished": False, "is_running": False}); st.rerun()

    with col_view:
        st.header("🖥️ 监视屏")
        for i, msg in enumerate(engine["messages"]):
            if msg["role"] == "system": continue
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg["role"] == "assistant":
                    msg["selected"] = st.checkbox("☑️ 选中参与导出", msg.get("selected", True), key=f"ac_{i}")

        if engine["is_running"]:
            client, profile = get_client()
            sop_data = st.session_state.sops[engine["sop_name"]]
            steps = sop_data["steps"]
            triggers = sop_data.get("triggers", [])
            curr_step_obj = steps[engine["current_step_idx"]]
            
            if engine["pending_instruction"]:
                current_prompt = engine["pending_instruction"]
                engine["pending_instruction"] = ""
            else:
                current_prompt = curr_step_obj["prompt"].replace("{主题}", engine["topic"]).replace("{循环索引}", str(engine["current_loop_idx"]))
            
            engine["messages"].append({"role": "user", "content": current_prompt, "selected": False})
            with st.chat_message("user"): st.markdown(f"*(⚡ 指令)*: {current_prompt}")
                
            api_msgs = []
            if profile.get("global_system_prompt"): api_msgs.append({"role": "system", "content": profile["global_system_prompt"]})
            if engine["global_file"]: api_msgs.append({"role": "system", "content": f"【全局参考资料】\n{engine['global_file']}"})
            
            # 注入当前阶段专属参考资料
            step_ref = curr_step_obj.get("reference", "")
            if step_ref: api_msgs.append({"role": "system", "content": f"【本阶段专属参考资料】\n{step_ref}"})
                
            api_msgs.extend([{"role": m["role"], "content": m["content"]} for m in engine["messages"]])
            
            with st.chat_message("assistant"):
                try:
                    kwargs = build_api_kwargs(profile, api_msgs)
                    resp = client.chat.completions.create(**kwargs)
                    full_resp = st.write_stream(stream_generator(resp))
                    engine["messages"].append({"role": "assistant", "content": full_resp, "selected": True})
                    
                    hit_trigger = False
                    if engine["last_finish_reason"] == "length":
                        engine["pending_instruction"] = "⚠️ 因长度截断，请紧接着上文继续输出。"
                        st.toast("长度预案启动", icon="⚠️"); hit_trigger = True
                        
                    if not hit_trigger:
                        for t in triggers:
                            if t["keyword"] and t["keyword"] in full_resp:
                                if t["type"] == "terminate":
                                    engine["is_running"] = False; engine["is_finished"] = True
                                    st.toast("🛑 完结规则生效", icon="🛑"); hit_trigger = True; break
                                elif t["type"] == "intervene":
                                    engine["pending_instruction"] = t["action"]
                                    st.toast("⚡ 干预规则生效", icon="⚡"); hit_trigger = True; break
                                    
                    if not hit_trigger:
                        if engine["current_loop_idx"] < curr_step_obj.get("loop", 1):
                            engine["current_loop_idx"] += 1
                        else:
                            engine["current_step_idx"] += 1; engine["current_loop_idx"] = 1
                        if engine["current_step_idx"] >= len(steps):
                            engine["is_running"] = False; engine["is_finished"] = True
                            st.toast("🎉 流水线完工！", icon="🎊")
                    st.rerun()
                except Exception as e:
                    st.error(f"引擎故障: {e}"); engine["is_running"] = False
