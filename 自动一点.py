import streamlit as st
import streamlit.components.v1 as components
from openai import OpenAI
import io
import json
import os
import re
import requests
import uuid
from datetime import datetime
from docx import Document

# ==========================================
# 1. 页面配置与前端美化
# ==========================================
st.set_page_config(page_title="ZenMux 创作者工作站", page_icon="🐙", layout="wide")
st.markdown("""
    <style>
    .stButton>button { border-radius: 8px; font-weight: bold; transition: all 0.3s; }
    .stChatInput { padding-bottom: 20px; }
    button[title="View fullscreen"] {display: none;}
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 本地数据库引擎
# ==========================================
DATA_DIR = "ZenMux_Data"
os.makedirs(DATA_DIR, exist_ok=True)

def load_data(filename, default_val):
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception: pass
    return default_val

def save_data(filename, data):
    filepath = os.path.join(DATA_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ==========================================
# 3. 核心辅助函数
# ==========================================
def render_copy_button(text):
    safe_text = json.dumps(text)
    html = f"""
    <body style="margin:0; padding:0; overflow:hidden; display:flex; justify-content:flex-end;">
        <button onclick="navigator.clipboard.writeText({safe_text}).then(()=>{{this.innerText='✅ 已复制'; setTimeout(()=>this.innerText='📋 复制内容',2000)}})" 
        style="border:none; background:none; color:#777; cursor:pointer; font-size:12px; font-weight:bold; padding:2px;">
        📋 复制内容</button>
    </body>
    """
    components.html(html, height=24)

def clean_novel_text(text):
    """正则洗稿引擎"""
    text = re.sub(r'^\s*(好的|没问题|非常荣幸|收到|为你生成|以下是|这是为您|正文开始|下面是).*?[:：]\n*', '', text, flags=re.MULTILINE|re.IGNORECASE)
    text = re.sub(r'^\s*第[零一二三四五六七八九十百千0-9]+[章回节卷].*?\n', '', text, flags=re.MULTILINE)
    text = re.sub(r'```[a-zA-Z]*\n?', '', text)
    text = re.sub(r'\n*(希望这|如果有需要|请告诉我|期待您的反馈).*$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def generate_word_doc(messages, is_pure=False):
    """Word 生成器，支持完整版和纯享版"""
    doc = Document()
    doc.add_heading('内容文档', 0)
    for msg in messages:
        if msg["role"] == "system" or not msg.get("selected", True): continue
        if is_pure:
            # 纯享版：只导出 AI 回答，且清洗废话，不加小标题
            if msg["role"] == "assistant":
                doc.add_paragraph(clean_novel_text(msg["content"]))
        else:
            # 完整版：保留对话和小标题
            if msg["role"] == "user":
                doc.add_heading("📌 指令 / 我", level=2)
                doc.add_paragraph(msg["content"])
            else:
                doc.add_heading("🤖 AI", level=2)
                doc.add_paragraph(msg["content"])
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

def get_client():
    profile = st.session_state.profiles[st.session_state.active_profile_idx]
    url = profile["base_url"].strip() or "https://api.openai.com/v1"
    key = profile["api_key"].strip()
    return OpenAI(base_url=url, api_key=key), profile

def build_api_kwargs(profile, api_msgs):
    kwargs = {"model": profile["model"], "messages": api_msgs, "stream": True}
    if profile.get("use_temperature", True): kwargs["temperature"] = profile.get("temperature", 0.7)
    if profile.get("use_max_tokens", True): kwargs["max_tokens"] = profile.get("max_tokens", 4096)
    if profile.get("use_top_p", False): kwargs["top_p"] = profile.get("top_p", 1.0)
    if profile.get("use_frequency_penalty", False): kwargs["frequency_penalty"] = profile.get("frequency_penalty", 0.0)
    return kwargs

def stream_generator(api_stream):
    st.session_state.auto_engine["last_finish_reason"] = "stop"
    for chunk in api_stream:
        if chunk.choices and chunk.choices[0].delta.content is not None:
            yield chunk.choices[0].delta.content
        if chunk.choices and chunk.choices[0].finish_reason is not None:
            st.session_state.auto_engine["last_finish_reason"] = chunk.choices[0].finish_reason

# ==========================================
# 4. 状态初始化
# ==========================================
if "initialized" not in st.session_state:
    st.session_state.profiles = load_data("profiles.json", [{
        "name": "默认引擎", "base_url": "", "api_key": "", "model": "anthropic/claude-sonnet-4.6",
        "use_temperature": True, "temperature": 0.8, "use_max_tokens": True, "max_tokens": 4096
    }])
    st.session_state.sops = load_data("sops.json", {
        "悬疑小说账号": {
            "memory_mode": "manual", # manual(手动蒸馏) 或 dynamic(动态进化)
            "system_prompt": "你是一名悬疑小说家，文风冷峻，绝不输出废话。",
            "negative_memory": [], # 存放用户的避坑反馈
            "steps": [{"prompt": "撰写第【{循环索引}】章", "loop": 2, "reference": ""}],
            "triggers": [{"type": "terminate", "keyword": "全文完", "action": ""}]
        }
    })
    st.session_state.memory = load_data("memory.json", {}) 
    
    # 自由聊天室持久化数据：{ chat_id: { title: "...", messages: [...] } }
    st.session_state.free_chats = load_data("free_chats.json", {})
    if not st.session_state.free_chats:
        new_id = str(uuid.uuid4())
        st.session_state.free_chats[new_id] = {"title": "新对话", "messages": []}
        st.session_state.current_chat_id = new_id
    else:
        st.session_state.current_chat_id = list(st.session_state.free_chats.keys())[-1]
    
    st.session_state.active_profile_idx = 0
    st.session_state.current_page = "🤖 自动化流水线"
    st.session_state.auto_engine = {
        "is_running": False, "is_finished": False, "messages": [],
        "sop_name": "", "topic": "", "global_file": "",
        "current_step_idx": 0, "current_loop_idx": 1,
        "pending_instruction": "", "last_finish_reason": ""
    }
    st.session_state.initialized = True

def save_profiles(): save_data("profiles.json", st.session_state.profiles)
def save_sops(): save_data("sops.json", st.session_state.sops)
def save_memory(): save_data("memory.json", st.session_state.memory)
def save_free_chats(): save_data("free_chats.json", st.session_state.free_chats)

# ==========================================
# 5. 全局侧边栏导航
# ==========================================
with st.sidebar:
    st.header("🐙 创作者中枢")
    st.write("") 
    pages = ["🤖 自动化流水线", "💬 自由聊天区", "📝 账号SOP与灵魂", "⚙️ 底层引擎配置"]
    for p in pages:
        btn_type = "primary" if st.session_state.current_page == p else "secondary"
        if st.button(p, use_container_width=True, type=btn_type):
            st.session_state.current_page = p
            st.rerun()

    active_p = st.session_state.profiles[st.session_state.active_profile_idx]
    st.divider()
    st.caption(f"🟢 **挂载引擎**: {active_p['name']}\n🧠 **模型**: {active_p['model']}")
    
    # --- 自由聊天专属历史管理与导出区 ---
    if st.session_state.current_page == "💬 自由聊天区":
        st.divider()
        st.header("📚 历史对话记录")
        if st.button("➕ 开启新对话", use_container_width=True, type="primary"):
            new_id = str(uuid.uuid4())
            st.session_state.free_chats[new_id] = {"title": "新对话", "messages": []}
            st.session_state.current_chat_id = new_id
            save_free_chats(); st.rerun()
            
        for c_id, c_data in reversed(list(st.session_state.free_chats.items())):
            c_title = c_data["title"][:15] + "..." if len(c_data["title"])>15 else c_data["title"]
            btn_lbl = f"⭐ {c_title}" if c_id == st.session_state.current_chat_id else f"📄 {c_title}"
            if st.button(btn_lbl, key=f"chat_{c_id}", use_container_width=True):
                st.session_state.current_chat_id = c_id; st.rerun()
                
        st.divider()
        st.header("📦 导出当前对话")
        current_msgs = st.session_state.free_chats[st.session_state.current_chat_id]["messages"]
        if current_msgs:
            exp_mode = st.radio("导出格式选择", ["完整版 (保留对话)", "纯享版 (仅清洗后正文)"])
            is_pure = (exp_mode == "纯享版 (仅清洗后正文)")
            
            if is_pure:
                txt_content = "\n\n".join([clean_novel_text(m['content']) for m in current_msgs if m['role']=='assistant'])
            else:
                txt_content = "".join([f"{'我' if m['role']=='user' else 'AI'}:\n{m['content']}\n\n{'-'*40}\n\n" for m in current_msgs])
                
            c1, c2 = st.columns(2)
            with c1: st.download_button("📥 TXT", txt_content.encode('utf-8'), "聊天记录.txt", "text/plain")
            with c2: st.download_button("📥 Word", generate_word_doc(current_msgs, is_pure=is_pure), "聊天记录.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

        if st.button("🗑️ 删除此对话", use_container_width=True):
            if len(st.session_state.free_chats) > 1:
                del st.session_state.free_chats[st.session_state.current_chat_id]
                st.session_state.current_chat_id = list(st.session_state.free_chats.keys())[-1]
            else:
                st.session_state.free_chats[st.session_state.current_chat_id] = {"title": "新对话", "messages": []}
            save_free_chats(); st.rerun()

# ==========================================
# 模块 1: 自动化流水线
# ==========================================
if st.session_state.current_page == "🤖 自动化流水线":
    engine = st.session_state.auto_engine
    col_ctrl, col_view = st.columns([1, 2.5])
    
    with col_ctrl:
        st.header("⚙️ 控制台")
        if engine["is_running"]:
            st.warning("⚠️ 引擎高速运转中...")
            total_steps = max(len(st.session_state.sops[engine["sop_name"]]["steps"]), 1)
            st.progress(min(engine["current_step_idx"] / total_steps, 1.0))
            if st.button("⏹️ 强制急停", type="primary", use_container_width=True): 
                engine["is_running"] = False; st.rerun()
        else:
            sel_sop = st.selectbox("1. 选择执行 SOP", list(st.session_state.sops.keys()))
            in_topic = st.text_input("2. 注入 {主题}", placeholder="例如：赛博朋克修仙传")
            up_file = st.file_uploader("3. 挂载全局设定集 (可选)", type=['txt', 'md'])
            
            if st.button("🚀 点火启动", type="primary", use_container_width=True):
                if not active_p["api_key"]: st.error("引擎未配置 API Key！")
                elif not in_topic: st.error("请填入主题！")
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
        
        # 📦 成果验收与双轨制记忆系统
        if engine["messages"]:
            st.markdown("### 📦 验收成果")
            sel_msgs = [m for m in engine["messages"] if m["role"] == "assistant" and m.get("selected", True)]
            raw_text = "\n\n".join([m["content"] for m in sel_msgs])
            pure_text = clean_novel_text(raw_text)
            
            if not engine["is_running"]:
                sop_data = st.session_state.sops[engine["sop_name"]]
                mem_mode = sop_data.get("memory_mode", "manual")
                
                # --- 双轨记忆逻辑分发 ---
                if mem_mode == "manual":
                    st.info("🧠 当前为【手动蒸馏模式】")
                    if st.button("💾 将本次佳作存入记忆库", type="primary", use_container_width=True):
                        sop_name = engine["sop_name"]
                        if sop_name not in st.session_state.memory: st.session_state.memory[sop_name] = []
                        st.session_state.memory[sop_name].append({
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "topic": engine["topic"], "content": pure_text[:2500]
                        })
                        save_memory(); st.toast("已存入硬盘！", icon="💾")
                else:
                    st.success("🌱 当前为【动态进化模式】")
                    st.caption("AI 表现不好？直接在下方骂它，系统会自动记忆并纠正。")
                    feedback = st.text_input("💬 对本次生成的避坑要求/反馈：", placeholder="例如：以后不准废话，动作描写再利落点")
                    if st.button("提交反馈并写入潜意识", use_container_width=True):
                        if feedback.strip():
                            if "negative_memory" not in sop_data: sop_data["negative_memory"] = []
                            sop_data["negative_memory"].append(feedback)
                            save_sops()
                            
                            # 静默融合逻辑：满3条自动提炼
                            if len(sop_data["negative_memory"]) >= 3:
                                with st.spinner("系统正在后台反思并融合新规则..."):
                                    try:
                                        client, profile = get_client()
                                        fusion_prompt = f"""你是一个人设调优专家。原人设：{sop_data['system_prompt']}。
用户近期提出了以下避坑反馈：{'; '.join(sop_data['negative_memory'])}。
请将这些反馈深度融合进原人设中，形成一段更完美、绝对服从用户要求的新 System Prompt。只输出纯文本。"""
                                        resp = client.chat.completions.create(model=profile["model"], messages=[{"role": "user", "content": fusion_prompt}])
                                        sop_data["system_prompt"] = resp.choices[0].message.content.strip()
                                        sop_data["negative_memory"] = [] # 清空已消化的记忆
                                        save_sops()
                                        st.success("反馈已吸收！人设已自动进化！")
                                    except Exception as e: st.error(f"融合失败: {e}")
                            else:
                                st.toast("反馈已记录，下一次生成立即生效！", icon="✅")

            c1, c2 = st.columns(2)
            with c1: st.download_button("📥 标准全文", raw_text.encode('utf-8'), f"{engine['topic']}_完整.txt", "text/plain", use_container_width=True)
            with c2: st.download_button("✨ 纯正文", pure_text.encode('utf-8'), f"{engine['topic']}_纯正文.txt", "text/plain", use_container_width=True)
            
            if st.button("🧹 清理工作台", use_container_width=True): 
                engine.update({"messages": [], "is_finished": False, "is_running": False}); st.rerun()

    with col_view:
        st.header("🖥️ 监视大屏")
        for i, msg in enumerate(engine["messages"]):
            if msg["role"] == "system": continue
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg["role"] == "assistant":
                    render_copy_button(msg["content"])
                    msg["selected"] = st.checkbox("☑️ 选中导出", msg.get("selected", True), key=f"ac_{i}")

        if engine["is_running"]:
            client, profile = get_client()
            sop_data = st.session_state.sops[engine["sop_name"]]
            steps = sop_data["steps"]
            triggers = sop_data.get("triggers", [])
            curr_step = steps[engine["current_step_idx"]]
            
            current_prompt = engine["pending_instruction"] or curr_step["prompt"].replace("{主题}", engine["topic"]).replace("{循环索引}", str(engine["current_loop_idx"]))
            engine["pending_instruction"] = ""
            
            # 【防线1：系统级物理封口贴】直接焊接在用户指令后，斩断废话根源
            silence_constraint = "\n\n【系统级强制约束：绝对不要重复要求，不要说“好的”、“为你生成”，绝对不要带有章节标题（如“第一章”），直接且只输出正文段落！】"
            final_prompt_to_api = current_prompt + silence_constraint
            
            engine["messages"].append({"role": "user", "content": current_prompt, "selected": False}) # UI上不显示封口贴
            with st.chat_message("user"): st.markdown(f"*(⚡ 指令)*: {current_prompt}")
                
            api_msgs = []
            sys_prompt = sop_data.get("system_prompt", "").strip()
            if sys_prompt: api_msgs.append({"role": "system", "content": sys_prompt})
            
            # 动态记忆实时注入
            if sop_data.get("memory_mode", "manual") == "dynamic" and sop_data.get("negative_memory"):
                api_msgs.append({"role": "system", "content": f"【避坑铁律】：{'; '.join(sop_data['negative_memory'])}"})
            
            if engine["global_file"]: api_msgs.append({"role": "system", "content": f"【全局设定】\n{engine['global_file']}"})
            if curr_step.get("reference"): api_msgs.append({"role": "system", "content": f"【本阶段设定】\n{curr_step['reference']}"})
            
            # 组装历史，替换用户最后一条指令为带有封口贴的版本
            for idx, m in enumerate(engine["messages"]):
                if idx == len(engine["messages"]) - 1 and m["role"] == "user":
                    api_msgs.append({"role": "user", "content": final_prompt_to_api})
                else:
                    api_msgs.append({"role": m["role"], "content": m["content"]})
            
            with st.chat_message("assistant"):
                try:
                    resp = client.chat.completions.create(**build_api_kwargs(profile, api_msgs))
                    full_resp = st.write_stream(stream_generator(resp))
                    render_copy_button(full_resp)
                    engine["messages"].append({"role": "assistant", "content": full_resp, "selected": True})
                    
                    hit_trigger = False
                    if engine["last_finish_reason"] == "length":
                        engine["pending_instruction"] = "⚠️ 请紧接着上文最后一个字继续输出，不要重复前文。"
                        hit_trigger = True
                    if not hit_trigger:
                        for t in triggers:
                            if t["keyword"] and t["keyword"] in full_resp:
                                if t["type"] == "terminate":
                                    engine["is_running"] = False; engine["is_finished"] = True; hit_trigger = True; break
                                elif t["type"] == "intervene":
                                    engine["pending_instruction"] = t["action"]; hit_trigger = True; break
                                    
                    if not hit_trigger:
                        if engine["current_loop_idx"] < curr_step.get("loop", 1): engine["current_loop_idx"] += 1
                        else: engine["current_step_idx"] += 1; engine["current_loop_idx"] = 1
                        if engine["current_step_idx"] >= len(steps): engine["is_running"] = False; engine["is_finished"] = True
                            
                    st.rerun() 
                except Exception as e:
                    st.error(f"引擎故障: {e}"); engine["is_running"] = False

# ==========================================
# 模块 2: 自由聊天区
# ==========================================
elif st.session_state.current_page == "💬 自由聊天区":
    curr_chat = st.session_state.free_chats[st.session_state.current_chat_id]
    st.title(f"💬 {curr_chat['title']}")
    
    for msg in curr_chat["messages"]:
        if msg["role"] == "system": continue
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant": render_copy_button(msg["content"])

    if prompt := st.chat_input("探讨设定、查资料..."):
        if not active_p["api_key"]: st.error("缺 API Key！"); st.stop()
        
        # 智能命名对话
        if len(curr_chat["messages"]) == 0:
            curr_chat["title"] = prompt[:10]
            
        curr_chat["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        
        client, profile = get_client()
        api_msgs = [{"role": m["role"], "content": m["content"]} for m in curr_chat["messages"]]
        
        with st.chat_message("assistant"):
            try:
                resp = client.chat.completions.create(**build_api_kwargs(profile, api_msgs))
                full_resp = st.write_stream(resp)
                render_copy_button(full_resp)
                curr_chat["messages"].append({"role": "assistant", "content": full_resp})
                save_free_chats() # 每聊一句落盘一次
                st.rerun()
            except Exception as e: st.error(f"请求失败: {e}")

# ==========================================
# 模块 3: 账号SOP与灵魂
# ==========================================
elif st.session_state.current_page == "📝 账号SOP与灵魂":
    tab_sop, tab_style = st.tabs(["🧩 SOP配置与人设", "🧠 账号风格提取与蒸馏"])
    
    with tab_sop:
        col1, col2 = st.columns([1, 2.5])
        with col1:
            st.subheader("账号/SOP 库")
            s_name = st.radio("选择编辑对象", list(st.session_state.sops.keys())) if st.session_state.sops else None
            if st.button("➕ 创建新账号 SOP"):
                st.session_state.sops[f"新账号 {len(st.session_state.sops)}"] = {
                    "memory_mode": "manual", "system_prompt": "", "negative_memory": [],
                    "steps": [{"prompt": "", "loop": 1}], "triggers": []
                }
                save_sops(); st.rerun()
            st.divider()
            sop_json = json.dumps(st.session_state.sops, ensure_ascii=False, indent=2).encode('utf-8')
            st.download_button("💾 导出 SOP 库", sop_json, "SOP库.json", "application/json")

        with col2:
            if s_name:
                sop = st.session_state.sops[s_name]
                
                ca, cb = st.columns([3, 1])
                with ca: new_name = st.text_input("✏️ 账号 SOP 名称", s_name)
                with cb:
                    st.write("")
                    if st.button("💾 手动保存配置", type="primary", use_container_width=True):
                        save_sops(); st.success("配置已落盘保存！")

                if new_name != s_name and new_name.strip():
                    st.session_state.sops[new_name] = st.session_state.sops.pop(s_name)
                    if s_name in st.session_state.memory:
                        st.session_state.memory[new_name] = st.session_state.memory.pop(s_name)
                        save_memory()
                    save_sops(); st.rerun()
                
                # --- 双轨制记忆核心开关 ---
                st.markdown("### 🧠 记忆生长模式")
                mode_opts = {"manual": "保守派：手动总结蒸馏 (稳定可控)", "dynamic": "激进派：自动活体进化 (越训越聪明)"}
                sop["memory_mode"] = st.radio("选择该账号的成长路线", ["manual", "dynamic"], format_func=lambda x: mode_opts[x], index=0 if sop.get("memory_mode", "manual")=="manual" else 1)
                
                if sop["memory_mode"] == "dynamic" and sop.get("negative_memory"):
                    with st.expander("👀 查看当前尚未融合的避坑反馈", expanded=True):
                        for nm in sop["negative_memory"]: st.markdown(f"- {nm}")
                        if st.button("清空避坑库"): sop["negative_memory"] = []; save_sops(); st.rerun()
                
                st.markdown("### 🎭 账号专属人设 (System Prompt)")
                sop["system_prompt"] = st.text_area("核心指令", sop.get("system_prompt", ""), height=100)
                
                st.markdown("### 🧩 执行阶段配置")
                new_steps = []
                for i, step in enumerate(sop["steps"]):
                    with st.container(border=True):
                        st.markdown(f"**阶段 {i+1}**")
                        c1, c2 = st.columns([4, 1])
                        with c1: p_val = st.text_area("指令", step["prompt"], height=60, key=f"p_{i}", label_visibility="collapsed")
                        with c2: l_val = st.number_input("循环", min_value=1, value=step.get("loop", 1), key=f"l_{i}")
                        ref = step.get("reference", "")
                        with st.expander("📁 挂载阶段参考资料"): ref = st.text_area("粘贴资料", ref, key=f"r_{i}")
                        new_steps.append({"prompt": p_val, "loop": l_val, "reference": ref})
                sop["steps"] = new_steps
                
                c_a, c_b = st.columns(2)
                with c_a: 
                    if st.button("➕ 加阶段"): sop["steps"].append({"prompt":"", "loop":1}); save_sops(); st.rerun()
                with c_b:
                    if len(sop["steps"])>1 and st.button("➖ 删阶段"): sop["steps"].pop(); save_sops(); st.rerun()
                
                st.markdown("### ⚡ 监听触发器")
                new_triggers = []
                for i, t in enumerate(sop.get("triggers", [])):
                    with st.container(border=True):
                        t1, t2, t3 = st.columns([1, 1, 2])
                        with t1: typ = st.selectbox("规则", ["terminate", "intervene"], index=0 if t["type"]=="terminate" else 1, key=f"t_{i}")
                        with t2: kwd = st.text_input("关键词", t["keyword"], key=f"k_{i}")
                        with t3: act = st.text_input("动作(强制完结不填)", t.get("action", ""), disabled=(typ=="terminate"), key=f"a_{i}")
                        new_triggers.append({"type": typ, "keyword": kwd, "action": act})
                sop["triggers"] = new_triggers
                if st.button("➕ 加规则"): sop["triggers"].append({"type":"intervene", "keyword":"", "action":""}); save_sops(); st.rerun()
                
                st.divider()
                if st.button("🗑️ 删除此 SOP", type="primary"): 
                    del st.session_state.sops[s_name]
                    if s_name in st.session_state.memory: del st.session_state.memory[s_name]
                    save_sops(); save_memory(); st.rerun()

    with tab_style:
        st.header("🧠 账号风格提取与蒸馏 (适用于手动模式)")
        st.markdown("通过分析 SOP 记忆库中的优秀作品，自动提炼灵魂提示词，注入该 SOP 的专属人设中。")
        
        acc_mem = st.session_state.memory.get(s_name, [])
        if not acc_mem:
            st.info(f"【{s_name}】的记忆库为空。请先在工作台生成并保存佳作。")
        else:
            st.success(f"记忆库已积累 {len(acc_mem)} 篇作品。")
            with st.expander("🔍 预览记忆库"):
                for item in acc_mem:
                    st.write(f"**[{item['time']}] {item['topic']}**")
                    st.caption(item['content'][:100] + "...")
            
            if st.button("🔥 立即执行风格蒸馏", type="primary", use_container_width=True):
                if not active_p["api_key"]: st.error("缺 API Key！"); st.stop()
                client, profile = get_client()
                combined_texts = "\n\n---\n\n".join([m['content'] for m in acc_mem[-3:]])
                distill_prompt = f"""分析以下几篇小说的风格，总结出一段严谨的【System Prompt】以便未来复刻此文风。只需输出纯文本的 Prompt，无废话。
样本：\n{combined_texts}"""

                with st.spinner("正在提炼灵魂提示词..."):
                    try:
                        resp = client.chat.completions.create(model=profile["model"], messages=[{"role": "user", "content": distill_prompt}])
                        distilled_prompt = resp.choices[0].message.content.strip()
                        st.session_state.sops[s_name]["system_prompt"] = distilled_prompt
                        save_sops()
                        st.success("🎉 蒸馏成功！该 SOP 的【专属人设】已被永久强化更新！")
                        st.info(f"**提炼出的专属灵魂提示词:**\n\n{distilled_prompt}")
                    except Exception as e: st.error(f"蒸馏失败: {e}")

# ==========================================
# 模块 4: 底层引擎配置
# ==========================================
elif st.session_state.current_page == "⚙️ 底层引擎配置":
    st.header("⚙️ 底层引擎管理")
    col_list, col_edit = st.columns([1, 2.5])
    
    with col_list:
        st.subheader("引擎库")
        p_names = [p["name"] for p in st.session_state.profiles]
        idx = st.radio("切换引擎", range(len(p_names)), format_func=lambda x: p_names[x], index=st.session_state.active_profile_idx)
        st.session_state.active_profile_idx = idx
        if st.button("➕ 新增引擎"):
            new_profile = {
                "name": f"新引擎 {len(p_names)+1}", "base_url": "", "api_key": "", "model": "anthropic/claude-sonnet-4.6",
                "use_temperature": True, "temperature": 0.8, "use_max_tokens": True, "max_tokens": 4096
            }
            st.session_state.profiles.append(new_profile)
            save_profiles(); st.rerun()

    with col_edit:
        st.subheader("底层参数设置")
        p = st.session_state.profiles[idx]
        
        ca, cb = st.columns([3, 1])
        with ca: p["name"] = st.text_input("引擎标签名称", p["name"])
        with cb:
            st.write("")
            if st.button("💾 保存引擎配置", type="primary", use_container_width=True): save_profiles(); st.success("已保存！")

        c1, c2 = st.columns(2)
        with c1: p["base_url"] = st.text_input("Base URL", p["base_url"])
        with c2: p["api_key"] = st.text_input("API Key", p["api_key"], type="password")
        
        cm, cb = st.columns([3, 1])
        with cm: p["model"] = st.text_input("模型 (Model ID)", p["model"])
        with cb:
            st.write("")
            if st.button("🔄 获取模型列表"):
                if p["api_key"]:
                    models = fetch_models(p["base_url"], p["api_key"])
                    if models: st.session_state.temp_models = models
        if "temp_models" in st.session_state:
            sel_m = st.selectbox("覆盖模型", ["(不覆盖)"] + st.session_state.temp_models)
            if sel_m != "(不覆盖)": p["model"] = sel_m; del st.session_state.temp_models; save_profiles(); st.rerun()
                
        st.markdown("#### 🎛️ 运行时超参数")
        sl1, sl2 = st.columns(2)
        with sl1:
            p["use_temperature"] = st.checkbox("🔥 Temperature", p.get("use_temperature", True))
            if p["use_temperature"]: p["temperature"] = st.slider("值", 0.0, 2.0, p.get("temperature", 0.8), 0.1, label_visibility="collapsed")
            p["use_max_tokens"] = st.checkbox("📏 Max Tokens", p.get("use_max_tokens", True))
            if p["use_max_tokens"]: p["max_tokens"] = st.slider("值", 512, 16384, p.get("max_tokens", 4096), 512, label_visibility="collapsed")
        with sl2:
            p["use_top_p"] = st.checkbox("🎲 Top P", p.get("use_top_p", False))
            if p["use_top_p"]: p["top_p"] = st.slider("值", 0.0, 1.0, p.get("top_p", 1.0), 0.05, label_visibility="collapsed")
            p["use_frequency_penalty"] = st.checkbox("🚫 Frequency Penalty", p.get("use_frequency_penalty", False))
            if p["use_frequency_penalty"]: p["frequency_penalty"] = st.slider("值", -2.0, 2.0, p.get("frequency_penalty", 0.0), 0.1, label_visibility="collapsed")

        save_profiles() # 实时静默落盘
