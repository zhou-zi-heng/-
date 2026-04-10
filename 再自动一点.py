import streamlit as st  
import streamlit.components.v1 as components  
from openai import OpenAI  
import io, base64, json, re, requests, uuid, copy  
from datetime import datetime  
from docx import Document  
  
# ==========================================  
# 1. 页面全局配置与前端美化  
# ==========================================  
st.set_page_config(page_title="ZenMux 创作者工作站", page_icon="🐙", layout="wide")  
st.markdown("""  
    <style>  
    .stButton>button { border-radius: 8px; font-weight: bold; transition: all 0.3s; }  
    .stChatInput { padding-bottom: 20px; }  
    button[title="View fullscreen"] {display: none;}  
    .css-1jc7ptx, .e1ewe7hr3, .viewerBadge_container__1QSob, .styles_viewerBadge__1yB5_ {display: none;}  
    </style>  
""", unsafe_allow_html=True)  
  
# ==========================================  
# 2. 数据状态管理 (变更追踪 + 云端安全)  
# ==========================================  
def _track():  
    st.session_state._unsaved = st.session_state.get("_unsaved", 0) + 1  
  
def save_profiles(): _track()  
def save_sops(): _track()  
def save_memory(): _track()  
def save_free_chats(): _track()  
  
# ==========================================  
# 3. 内置 SOP 模板库  
# ==========================================  
BUILTIN_TEMPLATES = {  
    "📖 悬疑推理小说": {  
        "memory_mode": "manual",  
        "system_prompt": "你是一名顶尖悬疑推理小说家，擅长构建精密逻辑链条和出人意料的反转。文风冷峻，节奏紧凑，善用细节伏笔。绝不输出废话。",  
        "negative_memory": [],  
        "steps": [  
            {"prompt": "为主题【{主题}】构思完整悬疑故事大纲：核心诡计、人物表、线索链、章节梗概。", "loop": 1, "reference": "", "enable_word_control": False, "target_words": 0, "word_tolerance": 5, "max_corrections": 2},  
            {"prompt": "根据大纲撰写第【{循环索引}】章正文。要求：伏笔自然、节奏紧凑、结尾留悬念。", "loop": 5, "reference": "", "enable_word_control": True, "target_words": 2000, "word_tolerance": 5, "max_corrections": 2},  
            {"prompt": "撰写最终章：真相揭晓，所有伏笔收束。结尾写'全文完'。", "loop": 1, "reference": "", "enable_word_control": True, "target_words": 3000, "word_tolerance": 10, "max_corrections": 2}  
        ],  
        "triggers": [{"type": "terminate", "keyword": "全文完", "action": ""}]  
    },  
    "💕 都市言情小说": {  
        "memory_mode": "manual",  
        "system_prompt": "你是细腻的都市言情小说家，善于捕捉情感细节和生活质感。对话自然，情感真挚，拒绝狗血。",  
        "negative_memory": [],  
        "steps": [  
            {"prompt": "为主题【{主题}】设计言情大纲：核心冲突、双主角设定、感情线节点。", "loop": 1, "reference": "", "enable_word_control": False, "target_words": 0, "word_tolerance": 5, "max_corrections": 2},  
            {"prompt": "撰写第【{循环索引}】章，注意情感推进和细节。", "loop": 8, "reference": "", "enable_word_control": True, "target_words": 2500, "word_tolerance": 5, "max_corrections": 2}  
        ],  
        "triggers": [{"type": "terminate", "keyword": "全文完", "action": ""}]  
    },  
    "🎬 短视频脚本批量": {  
        "memory_mode": "manual",  
        "system_prompt": "你是爆款短视频编剧，精通情绪钩子和节奏控制。每个脚本要有强开头、高密度中段、记忆点结尾。",  
        "negative_memory": [],  
        "steps": [  
            {"prompt": "为主题【{主题}】编写第【{循环索引}】条60秒短视频脚本：画面描述、旁白、字幕、BGM建议。", "loop": 5, "reference": "", "enable_word_control": True, "target_words": 300, "word_tolerance": 15, "max_corrections": 1}  
        ],  
        "triggers": []  
    }  
}  
  
def _default_step():  
    return {"prompt": "", "loop": 1, "reference": "", "enable_word_control": False, "target_words": 0, "word_tolerance": 5, "max_corrections": 2}  
  
def _ensure_step(s):  
    for k, v in _default_step().items():  
        s.setdefault(k, v)  
    return s  
  
def _ensure_chat(c):  
    c.setdefault("session_knowledge", [])  
    c.setdefault("system_prompt", "")  
    return c  
  
# ==========================================  
# 4. 核心底层辅助函数  
# ==========================================  
def render_copy_button(text):  
    b64 = base64.b64encode(text.encode("utf-8")).decode("utf-8")  
    uid = uuid.uuid4().hex[:8]  
    html = f"""<div style="display:flex;justify-content:flex-end;padding-right:10px;">  
    <button id="cb{uid}" onclick="(function(b){{navigator.clipboard.writeText(decodeURIComponent(escape(atob('{b64}')))).then(()=>{{b.innerText='✅ 已复制';b.style.color='#4CAF50';setTimeout(()=>{{b.innerText='📋 复制';b.style.color='#aaa';}},2000);}})}})(this)"  
    style="border:none;background:transparent;color:#aaa;cursor:pointer;font-size:12px;font-weight:bold;padding:5px 10px;border-radius:6px;">📋 复制</button></div>"""  
    components.html(html, height=30)  
  
def clean_novel_text(text):  
    text = re.sub(r'^\s*(好的|没问题|非常荣幸|收到|为你生成|以下是|这是为您|正文开始|下面是).*?[:：]\n*', '', text, flags=re.MULTILINE|re.IGNORECASE)  
    text = re.sub(r'^\s*第[零一二三四五六七八九十百千0-9]+[章回节卷].*?\n', '', text, flags=re.MULTILINE)  
    text = re.sub(r'```[a-zA-Z]*\n?', '', text)  
    text = re.sub(r'\n*(希望这|如果有需要|请告诉我|期待您的反馈).*$', '', text, flags=re.IGNORECASE)  
    text = re.sub(r'\n{3,}', '\n\n', text)  
    return text.strip()  
  
def count_words(text):  
    return len(re.findall(r'[\u4e00-\u9fff]', text)) + len(re.findall(r'[a-zA-Z]+', text))  
  
def generate_word_doc(messages, is_pure=False):  
    doc = Document()  
    doc.add_heading('AI 创作者工作站生成文档', 0)  
    for msg in messages:  
        if msg["role"] == "system" or not msg.get("selected", True): continue  
        if is_pure:  
            if msg["role"] == "assistant": doc.add_paragraph(clean_novel_text(msg["content"]))  
        else:  
            if msg["role"] == "user":  
                doc.add_heading("📌 指令", level=2); doc.add_paragraph(msg["content"])  
            elif msg["role"] == "assistant":  
                doc.add_heading("🤖 AI", level=2); doc.add_paragraph(msg["content"])  
    bio = io.BytesIO(); doc.save(bio); return bio.getvalue()  
  
def export_to_pretty_html(messages, title):  
    css = "body{font-family:'PingFang SC','Microsoft YaHei',sans-serif;line-height:1.8;color:#333;max-width:800px;margin:40px auto;padding:20px;background:#f9f9f9}.container{background:#fff;padding:40px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.05)}h1{text-align:center;color:#2c3e50;border-bottom:2px solid #eee;padding-bottom:20px}.chapter{margin-bottom:40px;white-space:pre-wrap}.meta{font-size:12px;color:#999;text-align:center;margin-bottom:50px}.footer{text-align:center;font-size:12px;color:#ccc;margin-top:60px;border-top:1px solid #eee;padding-top:20px}"  
    parts = "".join([f"<div class='chapter'>{clean_novel_text(m['content'])}</div>" for m in messages if m["role"]=="assistant" and m.get("selected", True)])  
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}</title><style>{css}</style></head><body><div class='container'><h1>{title}</h1><div class='meta'>ZenMux 创作者工作站 | {datetime.now().strftime('%Y-%m-%d')}</div>{parts}<div class='footer'>AI 全自动流水线驱动</div></div></body></html>".encode('utf-8')  
  
def fetch_models(base_url, api_key):  
    try:  
        url = (base_url.strip().rstrip('/') or "https://api.openai.com/v1") + "/models"  
        resp = requests.get(url, headers={"Authorization": f"Bearer {api_key.strip()}"}, timeout=8)  
        if resp.status_code == 200: return True, sorted([m["id"] for m in resp.json().get("data", [])])  
        else: return False, f"状态码 {resp.status_code}: {resp.text[:100]}"  
    except Exception as e: return False, str(e)  
  
def get_client():  
    p = st.session_state.profiles[st.session_state.active_profile_idx]  
    return OpenAI(base_url=p["base_url"].strip() or "https://api.openai.com/v1", api_key=p["api_key"].strip()), p  
  
def build_api_kwargs(profile, api_msgs):  
    kw = {"model": profile["model"], "messages": api_msgs, "stream": True}  
    if profile.get("use_temperature", True): kw["temperature"] = profile.get("temperature", 0.7)  
    if profile.get("use_max_tokens", True): kw["max_tokens"] = profile.get("max_tokens", 4096)  
    if profile.get("use_top_p", False): kw["top_p"] = profile.get("top_p", 1.0)  
    if profile.get("use_frequency_penalty", False): kw["frequency_penalty"] = profile.get("frequency_penalty", 0.0)  
    return kw  
  
def stream_generator(api_stream):  
    st.session_state.auto_engine["last_finish_reason"] = "stop"  
    for chunk in api_stream:  
        if chunk.choices and chunk.choices[0].delta.content is not None:  
            yield chunk.choices[0].delta.content  
        if chunk.choices and chunk.choices[0].finish_reason is not None:  
            st.session_state.auto_engine["last_finish_reason"] = chunk.choices[0].finish_reason  
# ==========================================  
# 5. 状态初始化 (完整私有沙盒)  
# ==========================================  
if "initialized" not in st.session_state:  
    st.session_state.profiles = [{  
        "name": "默认引擎", "base_url": "", "api_key": "", "model": "anthropic/claude-sonnet-4.6",  
        "use_temperature": True, "temperature": 0.8, "use_max_tokens": True, "max_tokens": 4096,  
        "use_top_p": False, "top_p": 1.0, "use_frequency_penalty": False, "frequency_penalty": 0.0  
    }]  
    st.session_state.sops = {  
        "小说账号预设": {  
            "memory_mode": "manual",  
            "system_prompt": "你是一名悬疑小说家，文风冷峻，绝不输出废话。",  
            "negative_memory": [],  
            "steps": [_default_step() | {"prompt": "撰写第【{循环索引}】章", "loop": 2}],  
            "triggers": [{"type": "terminate", "keyword": "全文完", "action": ""}]  
        }  
    }  
    st.session_state.memory = {}  
    first_chat_id = str(uuid.uuid4())  
    st.session_state.free_chats = {first_chat_id: {"title": "新对话", "messages": [], "session_knowledge": [], "system_prompt": ""}}  
    st.session_state.active_profile_idx = 0  
    st.session_state.current_page = "🤖 自动化流水线"  
    st.session_state.current_chat_id = first_chat_id  
    st.session_state.auto_engine = {  
        "is_running": False, "is_paused": False, "is_finished": False, "messages": [],  
        "sop_name": "", "topic": "", "global_file": "",  
        "current_step_idx": 0, "current_loop_idx": 1,  
        "pending_instruction": "", "last_finish_reason": "",  
        "correction_count": 0, "word_count_log": [], "model_bias_history": []  
    }  
    st.session_state._unsaved = 0  
    st.session_state.initialized = True  
  
# ==========================================  
# 6. 全局侧边栏导航  
# ==========================================  
with st.sidebar:  
    col_img, col_txt = st.columns([1, 3])  
    with col_img: st.image("https://api.iconify.design/fluent-emoji:octopus.svg?width=80", width=45)  
    with col_txt: st.header("控制中枢")  
  
    # 未备份提醒  
    if st.session_state.get("_unsaved", 0) > 3:  
        st.warning(f"⚠️ 有 {st.session_state._unsaved} 项未备份更改，建议导出快照！")  
  
    st.write("")  
    pages = ["🤖 自动化流水线", "💬 自由聊天区", "📝 账号SOP与灵魂", "⚙️ 底层引擎配置"]  
    for p in pages:  
        if st.button(p, use_container_width=True, type="primary" if st.session_state.current_page == p else "secondary"):  
            st.session_state.current_page = p; st.rerun()  
  
    active_p = st.session_state.profiles[st.session_state.active_profile_idx]  
    st.divider()  
    st.caption(f"🟢 **当前挂载**: {active_p['name']}\n🧠 **模型**: {active_p['model']}")  
  
    # 自由聊天区侧边栏扩展  
    if st.session_state.current_page == "💬 自由聊天区":  
        st.divider()  
        st.header("📚 历史对话")  
        if st.button("➕ 开启新对话", use_container_width=True, type="primary"):  
            nid = str(uuid.uuid4())  
            st.session_state.free_chats[nid] = {"title": "新对话", "messages": [], "session_knowledge": [], "system_prompt": ""}  
            st.session_state.current_chat_id = nid; save_free_chats(); st.rerun()  
  
        for c_id, c_data in reversed(list(st.session_state.free_chats.items())):  
            _ensure_chat(c_data)  
            c_title = c_data["title"][:12] + ("..." if len(c_data["title"]) > 12 else "")  
            lbl = f"⭐ {c_title}" if c_id == st.session_state.current_chat_id else f"📄 {c_title}"  
            if st.button(lbl, key=f"chat_{c_id}", use_container_width=True):  
                st.session_state.current_chat_id = c_id; st.rerun()  
  
        st.divider()  
        curr_msgs_sidebar = st.session_state.free_chats[st.session_state.current_chat_id]["messages"]  
        if curr_msgs_sidebar:  
            st.markdown("**📦 导出当前对话**")  
            exp_mode = st.radio("格式", ["完整记录", "纯享正文"], label_visibility="collapsed")  
            is_pure = (exp_mode == "纯享正文")  
            if is_pure:  
                txt_c = "\n\n".join([clean_novel_text(m['content']) for m in curr_msgs_sidebar if m['role'] == 'assistant'])  
            else:  
                txt_c = "".join([f"{'我' if m['role']=='user' else 'AI'}:\n{m['content']}\n\n{'-'*40}\n\n" for m in curr_msgs_sidebar])  
            c1, c2, c3 = st.columns(3)  
            with c1: st.download_button("📥 TXT", txt_c.encode('utf-8'), "对话.txt", "text/plain", use_container_width=True)  
            with c2: st.download_button("📥 Word", generate_word_doc(curr_msgs_sidebar, is_pure), "对话.docx", use_container_width=True)  
            with c3: st.download_button("🎨 HTML", export_to_pretty_html(curr_msgs_sidebar, st.session_state.free_chats[st.session_state.current_chat_id]["title"]), "对话.html", "text/html", use_container_width=True)  
  
        # 删除对话（二次确认）  
        if st.session_state.get("_confirm_del_chat"):  
            st.error("确认删除此对话？不可撤回！")  
            cc1, cc2 = st.columns(2)  
            if cc1.button("✅ 确认", key="yes_del_chat"):  
                if len(st.session_state.free_chats) > 1:  
                    del st.session_state.free_chats[st.session_state.current_chat_id]  
                else:  
                    st.session_state.free_chats[st.session_state.current_chat_id] = {"title": "新对话", "messages": [], "session_knowledge": [], "system_prompt": ""}  
                st.session_state.current_chat_id = list(st.session_state.free_chats.keys())[-1]  
                st.session_state._confirm_del_chat = False; save_free_chats(); st.rerun()  
            if cc2.button("❌ 取消", key="no_del_chat"):  
                st.session_state._confirm_del_chat = False; st.rerun()  
        else:  
            if st.button("🗑️ 删除对话", use_container_width=True):  
                st.session_state._confirm_del_chat = True; st.rerun()  
  
    # 全量资产导出恢复  
    st.divider()  
    with st.expander("📦 全量资产导出恢复舱", expanded=False):  
        st.caption("换电脑时一键导入导出所有数据（SOP、引擎、记忆、聊天）。")  
        full_data = json.dumps({  
            "profiles": st.session_state.profiles, "sops": st.session_state.sops,  
            "memory": st.session_state.memory, "free_chats": st.session_state.free_chats  
        }, ensure_ascii=False, indent=2).encode('utf-8')  
        if st.download_button("📥 导出全量快照包", full_data, f"ZenMux_Backup_{datetime.now().strftime('%m%d_%H%M')}.json", "application/json", use_container_width=True, type="primary"):  
            st.session_state._unsaved = 0  
  
        uploaded_ws = st.file_uploader("📂 导入快照 (覆盖当前)", type="json")  
        if uploaded_ws:  
            try:  
                data = json.loads(uploaded_ws.getvalue().decode('utf-8'))  
                st.session_state.profiles = data.get("profiles", st.session_state.profiles)  
                st.session_state.sops = data.get("sops", st.session_state.sops)  
                # 兼容旧SOP缺少新字段  
                for sop in st.session_state.sops.values():  
                    for s in sop.get("steps", []): _ensure_step(s)  
                st.session_state.memory = data.get("memory", st.session_state.memory)  
                st.session_state.free_chats = data.get("free_chats", st.session_state.free_chats)  
                # 兼容旧聊天缺少新字段  
                for ch in st.session_state.free_chats.values(): _ensure_chat(ch)  
                if not st.session_state.free_chats:  
                    nid = str(uuid.uuid4())  
                    st.session_state.free_chats = {nid: {"title": "新对话", "messages": [], "session_knowledge": [], "system_prompt": ""}}  
                st.session_state.active_profile_idx = 0  
                st.session_state.current_chat_id = list(st.session_state.free_chats.keys())[-1]  
                st.session_state._unsaved = 0  
                st.success("✅ 恢复成功！")  
                st.rerun()  
            except Exception as e: st.error(f"导入失败: {e}")  
# ==========================================  
# 模块 1: 自动化流水线  
# ==========================================  
if st.session_state.current_page == "🤖 自动化流水线":  
    engine = st.session_state.auto_engine  
    col_ctrl, col_view = st.columns([1, 2.5])  
  
    with col_ctrl:  
        st.header("⚙️ 调度控制台")  
  
        # === 运行中状态 ===  
        if engine["is_running"]:  
            if engine.get("is_paused"):  
                # ---- 已暂停 ----  
                st.info("⏸️ 引擎已暂停，可注入修正指令")  
                pause_input = st.text_area("💬 修正指令（留空则直接继续）", "", placeholder="例如：接下来减少对话，多写心理描写", height=80)  
                cp1, cp2 = st.columns(2)  
                if cp1.button("▶️ 继续执行", type="primary", use_container_width=True):  
                    if pause_input.strip(): engine["pending_instruction"] = pause_input.strip()  
                    engine["is_paused"] = False; st.rerun()  
                if cp2.button("⏹️ 彻底停止", use_container_width=True):  
                    engine["is_running"] = False; engine["is_paused"] = False; st.rerun()  
            else:  
                # ---- 运转中 ----  
                st.warning("⚠️ 引擎高速运转中...")  
                sop_steps_count = max(len(st.session_state.sops.get(engine["sop_name"], {"steps": []})["steps"]), 1)  
                st.progress(min(engine["current_step_idx"] / sop_steps_count, 1.0))  
                st.caption(f"阶段 {engine['current_step_idx']+1}/{sop_steps_count} | 循环 {engine['current_loop_idx']} | 矫正第{engine['correction_count']}轮")  
  
                # 实时字数统计  
                ai_msgs = [m for m in engine["messages"] if m["role"] == "assistant" and m.get("selected", True)]  
                if ai_msgs:  
                    total_wc = sum(count_words(m["content"]) for m in ai_msgs)  
                    st.metric("📊 已生成总字数", f"{total_wc:,}")  
  
                cp1, cp2 = st.columns(2)  
                if cp1.button("⏸️ 暂停", use_container_width=True):  
                    engine["is_paused"] = True; st.rerun()  
                if cp2.button("⏹️ 强制急停", type="primary", use_container_width=True):  
                    engine["is_running"] = False; st.rerun()  
  
        # === 待机状态 ===  
        else:  
            if not st.session_state.sops:  
                st.warning("请先去配置一个 SOP。"); st.stop()  
            sel_sop = st.selectbox("1. 挂载执行 SOP (账号人设)", list(st.session_state.sops.keys()))  
            in_topic = st.text_input("2. 注入 {主题}", placeholder="例如：赛博朋克修仙传")  
            up_file = st.file_uploader("3. 挂载全局设定集 (可选)", type=['txt', 'md'])  
  
            if st.button("🚀 点火启动", type="primary", use_container_width=True):  
                if not active_p["api_key"]: st.error("引擎未配置 API Key！")  
                elif not in_topic: st.error("请填入主题！")  
                else:  
                    engine.update({  
                        "is_running": True, "is_paused": False, "is_finished": False, "messages": [],  
                        "sop_name": sel_sop, "topic": in_topic,  
                        "global_file": up_file.getvalue().decode("utf-8") if up_file else "",  
                        "current_step_idx": 0, "current_loop_idx": 1,  
                        "pending_instruction": "", "last_finish_reason": "",  
                        "correction_count": 0, "word_count_log": [], "model_bias_history": []  
                    })  
                    st.rerun()  
  
        # === 成果验收区 ===  
        st.divider()  
        if engine["messages"]:  
            st.markdown("### 📦 成果验收与记忆管理")  
            sel_msgs = [m for m in engine["messages"] if m["role"] == "assistant" and m.get("selected", True)]  
            raw_text = "\n\n".join([m["content"] for m in sel_msgs])  
            pure_text = clean_novel_text(raw_text)  
            total_export_wc = count_words(pure_text)  
            st.info(f"📊 选中导出内容：**{total_export_wc:,}** 字 | **{len(sel_msgs)}** 段")  
  
            if not engine["is_running"]:  
                sop_data = st.session_state.sops.get(engine["sop_name"], {})  
                mem_mode = sop_data.get("memory_mode", "manual")  
  
                if mem_mode == "manual":  
                    st.caption("🧠 记忆模式：手动提取蒸馏")  
                    if st.button("💾 存入该账号记忆保险库", type="primary", use_container_width=True):  
                        sn = engine["sop_name"]  
                        if sn not in st.session_state.memory: st.session_state.memory[sn] = []  
                        st.session_state.memory[sn].append({  
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),  
                            "topic": engine["topic"], "content": pure_text[:2500]  
                        })  
                        save_memory(); st.toast("已安全落盘！", icon="💾")  
                else:  
                    st.caption("🌱 记忆模式：动态活体进化")  
                    feedback = st.text_input("💬 避坑反馈：", placeholder="例如：不准写废话")  
                    if st.button("提交反馈写入潜意识", use_container_width=True):  
                        if feedback.strip():  
                            sop_data.setdefault("negative_memory", []).append(feedback)  
                            save_sops()  
                            if len(sop_data["negative_memory"]) >= 3:  
                                with st.spinner("融合新规则中..."):  
                                    try:  
                                        client, profile = get_client()  
                                        fusion_p = f"原人设：{sop_data['system_prompt']}。避坑反馈：{'; '.join(sop_data['negative_memory'])}。请深度融合进原人设，输出纯文本新 System Prompt。"  
                                        resp = client.chat.completions.create(model=profile["model"], messages=[{"role": "user", "content": fusion_p}])  
                                        sop_data["system_prompt"] = resp.choices[0].message.content.strip()  
                                        sop_data["negative_memory"] = []; save_sops()  
                                        st.success("人设已进化！")  
                                    except Exception as e: st.error(f"融合失败: {e}")  
                            else: st.toast("反馈已记录！", icon="✅")  
  
            # 导出按钮  
            c1, c2, c3 = st.columns(3)  
            with c1: st.download_button("📥 全文TXT", raw_text.encode('utf-8'), f"{engine['topic']}_完整.txt", use_container_width=True)  
            with c2: st.download_button("✨ 纯享TXT", pure_text.encode('utf-8'), f"{engine['topic']}_纯正文.txt", use_container_width=True)  
            with c3: st.download_button("🎨 精美HTML", export_to_pretty_html(engine["messages"], engine["topic"]), f"{engine['topic']}.html", "text/html", use_container_width=True)  
  
            # 字数统计报告  
            if engine["word_count_log"]:  
                with st.expander("📊 字数精控报告", expanded=False):  
                    total_actual = sum(w["actual"] for w in engine["word_count_log"])  
                    total_target = sum(w["target"] for w in engine["word_count_log"])  
                    avg_dev = sum(abs(w["actual"]-w["target"])/max(w["target"],1) for w in engine["word_count_log"]) / len(engine["word_count_log"])  
                    st.markdown(f"**合计**: {total_actual:,} / 目标 {total_target:,} | **平均偏差**: {avg_dev:.1%}")  
                    header = "| 章节 | 目标 | 实际 | 偏差 | 矫正 |\n|---|---|---|---|---|\n"  
                    rows = ""  
                    for w in engine["word_count_log"]:  
                        dev = (w["actual"] - w["target"]) / max(w["target"], 1)  
                        emoji = "✅" if abs(dev) <= 0.05 else "⚠️"  
                        rows += f"| 阶段{w['step']+1}-第{w['loop']}轮 | {w['target']} | {w['actual']} | {dev:+.1%} {emoji} | {w['corrections']}次 |\n"  
                    st.markdown(header + rows)  
  
            # 清理工作台（二次确认）  
            if st.session_state.get("_confirm_clear"):  
                st.error("确认清理？所有生成内容将丢失！")  
                cc1, cc2 = st.columns(2)  
                if cc1.button("✅ 确认清理", key="yes_clear"):  
                    engine.update({"messages": [], "is_finished": False, "is_running": False, "word_count_log": [], "model_bias_history": []})  
                    st.session_state._confirm_clear = False; st.rerun()  
                if cc2.button("❌ 取消", key="no_clear"):  
                    st.session_state._confirm_clear = False; st.rerun()  
            else:  
                if st.button("🧹 清理工作台", use_container_width=True):  
                    st.session_state._confirm_clear = True; st.rerun()  
  
    # === 监视大屏 ===  
    with col_view:  
        st.header("🖥️ 监视大屏")  
        with st.container(height=750, border=True):  
            for i, msg in enumerate(engine["messages"]):  
                if msg["role"] == "system": continue  
                with st.chat_message(msg["role"]):  
                    st.markdown(msg["content"])  
                    if msg["role"] == "assistant":  
                        render_copy_button(msg["content"])  
                        wc = count_words(msg["content"])  
                        ws = msg.get("_word_status", "")  
                        if ws: st.caption(ws)  
                        else: st.caption(f"📊 {wc} 字")  
                        msg["selected"] = st.checkbox("☑️ 选中导出", msg.get("selected", True), key=f"ac_{i}")  
  
            # === 核心执行引擎 ===  
            if engine["is_running"] and not engine.get("is_paused", False):  
                client, profile = get_client()  
                sop_data = st.session_state.sops[engine["sop_name"]]  
                steps = sop_data["steps"]  
                for s in steps: _ensure_step(s)  
                triggers = sop_data.get("triggers", [])  
                curr_step = steps[engine["current_step_idx"]]  
  
                # 构建当前提示词  
                current_prompt = engine["pending_instruction"] or curr_step["prompt"].replace("{主题}", engine["topic"]).replace("{循环索引}", str(engine["current_loop_idx"]))  
                engine["pending_instruction"] = ""  
  
                # 字数精控：预注入字数要求  
                wc_enabled = curr_step.get("enable_word_control", False) and curr_step.get("target_words", 0) > 0  
                word_injection = ""  
                if wc_enabled and engine["correction_count"] == 0:  
                    target = curr_step["target_words"]  
                    # 自动学习补偿  
                    if len(engine["model_bias_history"]) >= 2:  
                        bias = sum(engine["model_bias_history"][-5:]) / len(engine["model_bias_history"][-5:])  
                        if abs(bias - 1.0) > 0.05:  
                            target = int(curr_step["target_words"] / bias)  
                    word_injection = f"\n\n【本章字数要求：严格控制在 {target} 字左右】"  
  
                silence = "\n\n【系统强制指令：不要重复上文，不准说"好的"，不准带章节标题，直接从正文第一个字开始！】"  
                final_prompt = current_prompt + word_injection + silence  
  
                engine["messages"].append({"role": "user", "content": current_prompt, "selected": False})  
                with st.chat_message("user"): st.markdown(f"*(⚡ 指令)*: {current_prompt}")  
  
                # 构建 API 消息包（知识置顶：固定头部最大化缓存命中）  
                api_msgs = []  
                sys_prompt = sop_data.get("system_prompt", "").strip()  
                if sys_prompt: api_msgs.append({"role": "system", "content": sys_prompt})  
                if sop_data.get("memory_mode") == "dynamic" and sop_data.get("negative_memory"):  
                    api_msgs.append({"role": "system", "content": f"【避坑铁律】：{'; '.join(sop_data['negative_memory'])}"})  
                if engine["global_file"]:  
                    api_msgs.append({"role": "system", "content": f"【全局设定】\n{engine['global_file']}"})  
                if curr_step.get("reference"):  
                    api_msgs.append({"role": "system", "content": f"【本阶段设定】\n{curr_step['reference']}"})  
  
                for idx, m in enumerate(engine["messages"]):  
                    if idx == len(engine["messages"]) - 1 and m["role"] == "user":  
                        api_msgs.append({"role": "user", "content": final_prompt})  
                    else:  
                        api_msgs.append({"role": m["role"], "content": m["content"]})  
  
                with st.chat_message("assistant"):  
                    try:  
                        resp = client.chat.completions.create(**build_api_kwargs(profile, api_msgs))  
                        full_resp = st.write_stream(stream_generator(resp))  
                        render_copy_button(full_resp)  
  
                        wc_actual = count_words(full_resp)  
                        msg_data = {"role": "assistant", "content": full_resp, "selected": True, "_word_status": f"📊 {wc_actual} 字"}  
                        engine["messages"].append(msg_data)  
  
                        hit_trigger = False  
  
                        # === 字数精控闸门 ===  
                        if wc_enabled:  
                            target = curr_step["target_words"]  
                            tol = curr_step.get("word_tolerance", 5) / 100.0  
                            deviation = (wc_actual - target) / max(target, 1)  
  
                            if abs(deviation) > tol:  
                                if engine["correction_count"] < curr_step.get("max_corrections", 2):  
                                    engine["correction_count"] += 1  
                                    msg_data["selected"] = False  
                                    msg_data["_word_status"] = f"⚠️ {wc_actual}字 (偏差{deviation:+.1%}，矫正第{engine['correction_count']}轮)"  
                                    if deviation > 0:  
                                        engine["pending_instruction"] = f"【字数矫正】你刚才写了约{wc_actual}字，超出目标{target}字。请精简至{target}字以内，保持情节完整，删减冗余。"  
                                    else:  
                                        engine["pending_instruction"] = f"【字数矫正】你刚才只写了约{wc_actual}字，不足目标{target}字。请扩写至{target}字左右，增加场景和细节描写。"  
                                    hit_trigger = True  
                                else:  
                                    msg_data["_word_status"] = f"⚠️ {wc_actual}字 (偏差{deviation:+.1%}，已达最大矫正次数)"  
                            else:  
                                msg_data["_word_status"] = f"✅ {wc_actual}字 (目标{target}字)"  
  
                        # === length 中断续写 ===  
                        if not hit_trigger and engine["last_finish_reason"] == "length":  
                            engine["pending_instruction"] = "⚠️ 因字数限制中断，请紧接上文最后一个字继续。"  
                            hit_trigger = True  
  
                        # === 触发器检测 ===  
                        if not hit_trigger:  
                            for t in triggers:  
                                if t["keyword"] and t["keyword"] in full_resp:  
                                    if t["type"] == "terminate":  
                                        engine["is_running"] = False; engine["is_finished"] = True; hit_trigger = True; break  
                                    elif t["type"] == "intervene":  
                                        engine["pending_instruction"] = t["action"]; hit_trigger = True; break  
  
                        # === 正常推进 ===  
                        if not hit_trigger:  
                            # 记录字数日志  
                            if wc_enabled:  
                                engine["word_count_log"].append({  
                                    "step": engine["current_step_idx"], "loop": engine["current_loop_idx"],  
                                    "target": curr_step["target_words"], "actual": wc_actual,  
                                    "corrections": engine["correction_count"]  
                                })  
                                engine["model_bias_history"].append(wc_actual / max(curr_step["target_words"], 1))  
                            engine["correction_count"] = 0  
  
                            if engine["current_loop_idx"] < curr_step.get("loop", 1):  
                                engine["current_loop_idx"] += 1  
                            else:  
                                engine["current_step_idx"] += 1; engine["current_loop_idx"] = 1  
                            if engine["current_step_idx"] >= len(steps):  
                                engine["is_running"] = False; engine["is_finished"] = True  
                        st.rerun()  
                    except Exception as e:  
                        st.error(f"引擎故障: {e}"); engine["is_running"] = False  
# ==========================================  
# 模块 2: 自由聊天区 (知识库常驻 + Prompt Caching)  
# ==========================================  
elif st.session_state.current_page == "💬 自由聊天区":  
    curr_chat = _ensure_chat(st.session_state.free_chats[st.session_state.current_chat_id])  
    st.title(f"💬 {curr_chat['title']}")  
  
    # === 对话设置区 ===  
    with st.expander("⚙️ 对话设置（人设 / 知识库）", expanded=bool(curr_chat["session_knowledge"] or curr_chat["system_prompt"])):  
        # 人设  
        sop_choice = st.selectbox("💡 快速挂载已有 SOP 人设", ["(自定义)"] + list(st.session_state.sops.keys()))  
        if sop_choice != "(自定义)":  
            prefill = st.session_state.sops[sop_choice].get("system_prompt", "")  
        else:  
            prefill = curr_chat.get("system_prompt", "")  
        curr_chat["system_prompt"] = st.text_area("🎭 System Prompt (可选)", prefill, height=80, placeholder="给 AI 设定角色和规则")  
  
        # 文件上传  
        up_f = st.file_uploader("📎 上传参考文件（常驻本对话，触发 API 缓存）", type=['txt', 'md'], key=f"kb_{st.session_state.current_chat_id}")  
        if up_f:  
            content = up_f.getvalue().decode('utf-8')  
            if not any(k["filename"] == up_f.name for k in curr_chat["session_knowledge"]):  
                curr_chat["session_knowledge"].append({"filename": up_f.name, "content": content})  
                st.toast(f"✅ 已挂载: {up_f.name}", icon="📎"); st.rerun()  
  
        # 展示已挂载文件  
        if curr_chat["session_knowledge"]:  
            st.markdown("**已挂载文件：**")  
            for ki, k in enumerate(curr_chat["session_knowledge"]):  
                kc1, kc2 = st.columns([4, 1])  
                kc1.caption(f"📄 {k['filename']} ({len(k['content']):,} 字)")  
                if kc2.button("❌", key=f"rm_kb_{ki}"):  
                    curr_chat["session_knowledge"].pop(ki); st.rerun()  
  
    # === 聊天消息展示 ===  
    with st.container(height=600, border=False):  
        editing_idx = st.session_state.get("_editing_chat_idx")  
  
        for i, msg in enumerate(curr_chat["messages"]):  
            if msg["role"] == "system": continue  
  
            with st.chat_message(msg["role"]):  
                # 编辑模式  
                if msg["role"] == "user" and editing_idx == i:  
                    new_text = st.text_area("✏️ 编辑消息", msg["content"], key=f"edit_area_{i}", height=100)  
                    ec1, ec2 = st.columns(2)  
                    if ec1.button("✅ 确认并重新发送", key=f"edit_ok_{i}", type="primary"):  
                        msg["content"] = new_text  
                        curr_chat["messages"] = curr_chat["messages"][:i + 1]  
                        st.session_state._editing_chat_idx = None  
                        st.session_state._auto_resend_chat = True  
                        save_free_chats(); st.rerun()  
                    if ec2.button("❌ 取消编辑", key=f"edit_cancel_{i}"):  
                        st.session_state._editing_chat_idx = None; st.rerun()  
                else:  
                    st.markdown(msg["content"])  
  
                    if msg["role"] == "user" and editing_idx is None:  
                        if st.button("✏️ 编辑", key=f"edit_btn_{i}"):  
                            st.session_state._editing_chat_idx = i; st.rerun()  
  
                    if msg["role"] == "assistant":  
                        render_copy_button(msg["content"])  
                        st.caption(f"📊 {count_words(msg['content'])} 字")  
                        if st.button("🔄 重新生成", key=f"regen_{i}"):  
                            curr_chat["messages"] = curr_chat["messages"][:i]  
                            st.session_
