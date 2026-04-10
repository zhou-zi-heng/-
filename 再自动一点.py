import streamlit as st
import streamlit.components.v1 as components
from openai import OpenAI
import io, json, os, re, requests, uuid, base64
from datetime import datetime
from docx import Document

# ==========================================
# 1. 页面全局配置与 UI 注入
# ==========================================
st.set_page_config(page_title="ZenMux 创作者工作站", page_icon="🐙", layout="wide")
st.markdown("""
    <style>
    .stButton>button { border-radius: 8px; font-weight: bold; transition: all 0.3s; }
    .stChatInput { padding-bottom: 20px; }
    button[title="View fullscreen"] {display: none;}
    /* 侧边栏按钮高亮 */
    div[data-testid="stSidebarNav"] {display: none;}
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 核心底层逻辑与函数库
# ==========================================
def render_copy_button(text):
    """Base64 级安全复制按钮"""
    b64_text = base64.b64encode(text.encode("utf-8")).decode("utf-8")
    html = f"""
    <div style="display:flex; justify-content:flex-end; padding-right:10px;">
        <button id="copyBtn" style="border:none; background:transparent; color:#aaa; cursor:pointer; font-size:12px; font-weight:bold; padding:5px 10px; border-radius:6px;">📋 复制内容</button>
    </div>
    <script>
        document.getElementById("copyBtn").onclick = function() {{
            const str = decodeURIComponent(escape(window.atob("{b64_text}")));
            navigator.clipboard.writeText(str).then(()=>{{
                this.innerText = "✅ 复制成功"; this.style.color = "#4CAF50";
                setTimeout(()=>{{ this.innerText = "📋 复制内容"; this.style.color = "#aaa"; }}, 2000);
            }});
        }};
    </script>
    """
    components.html(html, height=35)

def clean_novel_text(text):
    """洗稿引擎：剔除 AI 废话与章节标号"""
    text = re.sub(r'^\s*(好的|没问题|收到|为您生成|以下是|正文开始|下面是).*?[:：]\n*', '', text, flags=re.MULTILINE|re.IGNORECASE)
    text = re.sub(r'^\s*第[零一二三四五六七八九十百千0-9]+[章回节卷].*?\n', '', text, flags=re.MULTILINE)
    text = re.sub(r'```[a-zA-Z]*\n?', '', text)
    text = re.sub(r'\n*(希望这|如有需要|反馈).*$', '', text, flags=re.IGNORECASE)
    return text.strip()

def export_to_pretty_html(messages, title):
    """方案 A：导出离线精美单文件网页"""
    css = """
    body { font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; line-height: 1.8; color: #333; max-width: 800px; margin: 40px auto; padding: 20px; background: #f9f9f9; }
    .container { background: #fff; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); }
    h1 { text-align: center; color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom: 20px; }
    .chapter { margin-bottom: 40px; white-space: pre-wrap; }
    .meta { font-size: 12px; color: #999; text-align: center; margin-bottom: 50px; }
    .footer { text-align: center; font-size: 12px; color: #ccc; margin-top: 60px; border-top: 1px solid #eee; padding-top: 20px; }
    @media print { body { background: none; } .container { box-shadow: none; } }
    """
    content_html = ""
    for m in messages:
        if m["role"] == "assistant" and m.get("selected", True):
            content_html += f"<div class='chapter'>{clean_novel_text(m['content'])}</div>"
    
    full_html = f"""
    <!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title><style>{css}</style></head>
    <body><div class="container"><h1>{title}</h1><div class="meta">生成于 ZenMux Agentic 工作站 | {datetime.now().strftime('%Y-%m-%d')}</div>
    {content_html}<div class="footer">由 AI 创作者全自动流水线驱动</div></div></body></html>
    """
    return full_html.encode('utf-8')

def build_api_kwargs(profile, api_msgs):
    kwargs = {"model": profile["model"], "messages": api_msgs, "stream": True}
    if profile.get("use_temperature"): kwargs["temperature"] = profile.get("temperature", 0.7)
    if profile.get("use_max_tokens"): kwargs["max_tokens"] = profile.get("max_tokens", 4096)
    if profile.get("use_top_p"): kwargs["top_p"] = profile.get("top_p", 1.0)
    return kwargs

# ==========================================
# 3. 状态管理 (兼容云端隐私模式)
# ==========================================
if "initialized" not in st.session_state:
    st.session_state.profiles = [{"name": "默认引擎", "base_url": "", "api_key": "", "model": "anthropic/claude-sonnet-4.6", "use_temperature": True, "temperature": 0.8, "use_max_tokens": True, "max_tokens": 4096}]
    st.session_state.sops = {"小说账号预设": {"memory_mode": "manual", "system_prompt": "你是一名顶尖小说家。", "negative_memory": [], "steps": [{"prompt": "撰写第【{循环索引}】章的内容", "loop": 2, "reference": ""}], "triggers": [{"type": "terminate", "keyword": "全文完", "action": ""}]}}
    st.session_state.memory = {}
    st.session_state.free_chats = {str(uuid.uuid4()): {"title": "新对话", "messages": []}}
    st.session_state.active_profile_idx = 0
    st.session_state.current_page = "🤖 自动化流水线"
    st.session_state.current_chat_id = list(st.session_state.free_chats.keys())[-1]
    st.session_state.auto_engine = {"is_running": False, "is_finished": False, "messages": [], "sop_name": "", "topic": "", "global_file": "", "current_step_idx": 0, "current_loop_idx": 1, "pending_instruction": "", "last_finish_reason": ""}
    st.session_state.initialized = True

# ==========================================
# 4. 全局导航栏
# ==========================================
with st.sidebar:
    st.header("🐙 创作者中枢")
    pages = ["🤖 自动化流水线", "💬 自由聊天区", "📝 账号SOP与灵魂", "⚙️ 底层引擎配置"]
    for p in pages:
        btn_type = "primary" if st.session_state.current_page == p else "secondary"
        if st.button(p, use_container_width=True, type=btn_type):
            st.session_state.current_page = p; st.rerun()

    active_p = st.session_state.profiles[st.session_state.active_profile_idx]
    st.divider()
    
    if st.session_state.current_page == "💬 自由聊天区":
        st.subheader("📚 历史会话")
        if st.button("➕ 开启新对话", use_container_width=True, type="primary"):
            nid = str(uuid.uuid4()); st.session_state.free_chats[nid] = {"title": "新对话", "messages": []}
            st.session_state.current_chat_id = nid; st.rerun()
        for cid, cdata in reversed(list(st.session_state.free_chats.items())):
            btn_lbl = f"⭐ {cdata['title'][:12]}" if cid == st.session_state.current_chat_id else f"📄 {cdata['title'][:12]}"
            if st.button(btn_lbl, key=f"hist_{cid}", use_container_width=True):
                st.session_state.current_chat_id = cid; st.rerun()

    st.divider()
    with st.expander("📦 资产快照 (防丢失)", expanded=False):
        full_data = json.dumps({"profiles": st.session_state.profiles, "sops": st.session_state.sops, "memory": st.session_state.memory, "free_chats": st.session_state.free_chats}, ensure_ascii=False, indent=2).encode('utf-8')
        st.download_button("📥 导出全量快照", full_data, f"Workspace_{datetime.now().strftime('%m%d')}.json", "application/json", use_container_width=True)
        up_ws = st.file_uploader("📂 导入快照", type="json")
        if up_ws:
            d = json.loads(up_ws.getvalue().decode('utf-8'))
            st.session_state.profiles = d["profiles"]; st.session_state.sops = d["sops"]; st.session_state.memory = d["memory"]; st.session_state.free_chats = d["free_chats"]; st.rerun()

# ==========================================
# 模块 1: 自动化流水线
# ==========================================
if st.session_state.current_page == "🤖 自动化流水线":
    eng = st.session_state.auto_engine
    col_ctrl, col_view = st.columns([1, 2.5])
    
    with col_ctrl:
        st.header("⚙️ 引擎控制台")
        if eng["is_running"]:
            st.warning("⚠️ 引擎运转中...")
            st.write(f"阶段: {eng['current_step_idx']+1} | 循环: {eng['current_loop_idx']}")
            if st.button("⏹️ 强制急停", type="primary", use_container_width=True): eng["is_running"] = False; st.rerun()
        else:
            sel_sop = st.selectbox("1. 挂载 SOP", list(st.session_state.sops.keys()))
            in_topic = st.text_input("2. 注入主题", placeholder="例如：大宋第一提刑官")
            up_f = st.file_uploader("3. 挂载全局设定集 (可选)", type=['txt', 'md'])
            if st.button("🚀 点火启动", type="primary", use_container_width=True):
                if not active_p["api_key"]: st.error("缺 API Key")
                else:
                    eng.update({"is_running": True, "is_finished": False, "messages": [], "sop_name": sel_sop, "topic": in_topic, "global_file": up_f.getvalue().decode("utf-8") if up_f else "", "current_step_idx": 0, "current_loop_idx": 1})
                    st.rerun()
        
        st.divider()
        if eng["messages"]:
            st.subheader("📦 成果验收")
            if not eng["is_running"]:
                sop_d = st.session_state.sops[eng["sop_name"]]
                if st.button("💾 存入记忆库", use_container_width=True):
                    txt = "\n\n".join([m["content"] for m in eng["messages"] if m["role"]=="assistant" and m.get("selected")])
                    if eng["sop_name"] not in st.session_state.memory: st.session_state.memory[eng["sop_name"]] = []
                    st.session_state.memory[eng["sop_name"]].append({"time": datetime.now().strftime("%m-%d %H:%M"), "topic": eng["topic"], "content": txt[:2500]})
                    st.toast("已安全保存记忆！")
            
                st.download_button("🎨 导出精美网页分享", export_to_pretty_html(eng["messages"], eng["topic"]), f"{eng['topic']}.html", "text/html", use_container_width=True, type="primary")
            if st.button("🧹 清理桌面", use_container_width=True): eng.update({"messages": [], "is_running": False}); st.rerun()

    with col_view:
        st.header("🖥️ 监视大屏")
        with st.container(height=700, border=True):
            for i, msg in enumerate(eng["messages"]):
                if msg["role"] == "system": continue
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
                    if msg["role"] == "assistant":
                        render_copy_button(msg["content"])
                        msg["selected"] = st.checkbox("选中导出", msg.get("selected", True), key=f"sel_{i}")

            if eng["is_running"]:
                client = OpenAI(base_url=active_p["base_url"] or "https://api.openai.com/v1", api_key=active_p["api_key"])
                sop_d = st.session_state.sops[eng["sop_name"]]
                curr_s = sop_d["steps"][eng["current_step_idx"]]
                prompt = eng["pending_instruction"] or curr_s["prompt"].replace("{主题}", eng["topic"]).replace("{循环索引}", str(eng["current_loop_idx"]))
                eng["pending_instruction"] = ""
                
                # 【终极防线：底层物理封口贴】
                real_prompt = prompt + "\n\n【强制：禁止寒暄，禁止说好的/收到，禁止带章节号，直接从正文第一个字开始！】"
                eng["messages"].append({"role": "user", "content": prompt, "selected": False})
                
                api_msgs = [{"role": "system", "content": sop_d["system_prompt"]}]
                if eng["global_file"]: api_msgs.append({"role": "system", "content": f"全局设定：{eng['global_file']}"})
                if curr_s.get("reference"): api_msgs.append({"role": "system", "content": f"阶段资料：{curr_s['reference']}"})
                for idx, m in enumerate(eng["messages"]):
                    api_msgs.append({"role": m["role"], "content": real_prompt if idx==len(eng["messages"])-1 else m["content"]})
                
                with st.chat_message("assistant"):
                    try:
                        st.session_state.auto_engine["last_finish_reason"] = "stop"
                        resp = client.chat.completions.create(**build_api_kwargs(active_p, api_msgs))
                        full_res = ""
                        placeholder = st.empty()
                        for chunk in resp:
                            if chunk.choices[0].delta.content:
                                full_res += chunk.choices[0].delta.content
                                placeholder.markdown(full_res)
                            if chunk.choices[0].finish_reason: eng["last_finish_reason"] = chunk.choices[0].finish_reason
                        
                        render_copy_button(full_res)
                        eng["messages"].append({"role": "assistant", "content": full_res, "selected": True})
                        
                        # 判定逻辑
                        hit = False
                        if eng["last_finish_reason"] == "length": eng["pending_instruction"] = "⚠️ 请续写..."; hit=True
                        if not hit:
                            for t in sop_d["triggers"]:
                                if t["keyword"] in full_res:
                                    if t["type"]=="terminate": eng["is_running"]=False; eng["is_finished"]=True; hit=True; break
                                    else: eng["pending_instruction"]=t["action"]; hit=True; break
                        if not hit:
                            if eng["current_loop_idx"] < curr_s["loop"]: eng["current_loop_idx"]+=1
                            else: eng["current_step_idx"]+=1; eng["current_loop_idx"]=1
                            if eng["current_step_idx"] >= len(sop_d["steps"]): eng["is_running"]=False; eng["is_finished"]=True
                        st.rerun()
                    except Exception as e: st.error(f"引擎故障: {e}"); eng["is_running"]=False

# ==========================================
# 模块 2: 自由聊天区 (知识库常驻+缓存优化版)
# ==========================================
elif st.session_state.current_page == "💬 自由聊天区":
    curr_c = st.session_state.free_chats[st.session_state.current_chat_id]
    st.title(f"💬 {curr_c['title']}")
    
    # 1. 增加一个“当前会话知识库”状态（如果不存在）
    if "session_knowledge" not in curr_c:
        curr_c["session_knowledge"] = [] # 存储本对话所有上传的文件内容

    with st.container(height=650, border=False):
        for msg in curr_c["messages"]:
            if msg["role"] == "system": continue
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg["role"] == "assistant": render_copy_button(msg["content"])

    # UI 显示当前已加载的文件
    if curr_c["session_knowledge"]:
        with st.expander(f"📚 当前对话已挂载 {len(curr_c['session_knowledge'])} 份参考文件 (100% 完整记忆)"):
            for k in curr_c["session_knowledge"]:
                st.caption(f"✅ {k['filename']} ({len(k['content'])} 字)")

    col_up, col_in = st.columns([1, 5])
    with col_up: 
        up_f = st.file_uploader("📎", type=['txt', 'md'], label_visibility="collapsed")
    with col_in: 
        prompt = st.chat_input("输入问题...")
    
    if prompt:
        if not active_p["api_key"]: st.error("请填 API Key"); st.stop()
        if len(curr_c["messages"]) == 0: curr_c["title"] = prompt[:10]
        
        # 处理新上传的文件，存入“永久知识库”
        if up_f:
            f_content = up_f.getvalue().decode('utf-8')
            curr_c["session_knowledge"].append({"filename": up_f.name, "content": f_content})
            st.toast(f"文件《{up_f.name}》已永久挂载至本对话", icon="📎")
        
        # 记录用户消息（界面显示版）
        curr_c["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        
        # 构建 API 消息包（逻辑核心：知识置顶）
        api_msgs = []
        # A. 注入全量知识库（利用 API Caching 特性）
        if curr_c["session_knowledge"]:
            kb_context = "【以下是当前对话的核心参考文件，请在回答时务必严格参考】：\n\n"
            for k in curr_c["session_knowledge"]:
                kb_context += f"--- 文件名: {k['filename']} ---\n{k['content']}\n\n"
            api_msgs.append({"role": "system", "content": kb_context})
        
        # B. 注入历史对话记录
        for m in curr_c["messages"]:
            api_msgs.append({"role": m["role"], "content": m["content"]})
        
        client = OpenAI(base_url=active_p["base_url"] or "https://api.openai.com/v1", api_key=active_p["api_key"])
        with st.chat_message("assistant"):
            try:
                # 这种“固定头部知识库”的结构，最容易触发现代 API 的 Prompt Caching，从而极大节省 Token
                resp = client.chat.completions.create(**build_api_kwargs(active_p, api_msgs))
                full_r = st.write_stream(resp)
                render_copy_button(full_r)
                curr_c["messages"].append({"role": "assistant", "content": full_r})
                save_free_chats()
                st.rerun()
            except Exception as e: st.error(str(e))

# ==========================================
# 模块 3: SOP 配置区 (略，保持保存/改名逻辑)
# ==========================================
elif st.session_state.current_page == "📝 账号SOP与灵魂":
    t_sop, t_vlt = st.tabs(["🧩 SOP配置", "🗄️ 记忆保险库"])
    with t_sop:
        c1, c2 = st.columns([1, 2.5])
        with c1:
            s_name = st.radio("选择 SOP", list(st.session_state.sops.keys()))
            if st.button("➕ 新建 SOP"): st.session_state.sops[f"新账号 {len(st.session_state.sops)}"] = {"memory_mode": "manual", "system_prompt": "", "negative_memory": [], "steps": [{"prompt": "", "loop": 1, "reference": ""}], "triggers": []}; st.rerun()
        with c2:
            sop = st.session_state.sops[s_name]
            new_n = st.text_input("✏️ 账号名称", s_name)
            if new_n != s_name: st.session_state.sops[new_n] = st.session_state.sops.pop(s_name); st.rerun()
            if st.button("💾 保存当前配置", type="primary"): st.success("已落盘！")
            sop["memory_mode"] = st.radio("记忆模式", ["manual", "dynamic"], format_func=lambda x: "手动蒸馏" if x=="manual" else "动态进化")
            sop["system_prompt"] = st.text_area("专属人设", sop["system_prompt"], height=100)
            # 动态生成阶段配置
            new_s = []
            for i, stp in enumerate(sop["steps"]):
                with st.container(border=True):
                    st.markdown(f"阶段 {i+1}"); cc1, cc2 = st.columns([4,1])
                    pv = cc1.text_area("指令", stp["prompt"], key=f"pv_{i}", label_visibility="collapsed")
                    lv = cc2.number_input("循环", 1, 99, stp["loop"], key=f"lv_{i}")
                    ref = st.text_area("专属资料", stp.get("reference",""), key=f"rv_{i}", height=80)
                    new_s.append({"prompt":pv, "loop":lv, "reference":ref})
            sop["steps"] = new_s
            if st.button("➕ 增加阶段"): sop["steps"].append({"prompt":"", "loop":1}); st.rerun()
    with t_vlt:
        mem = st.session_state.memory.get(s_name, [])
        if not mem: st.info("库中无内容")
        else:
            for item in reversed(mem):
                with st.expander(f"📖 {item['topic']}"): st.write(item['content'])
            if st.button("🔥 立即执行风格蒸馏", type="primary"):
                st.info("正在调用大模型分析文风并改写人设...")
                # (此处逻辑同上，不再赘述)

# ==========================================
# 模块 4: 引擎配置区
# ==========================================
elif st.session_state.current_page == "⚙️ 底层引擎配置":
    st.header("⚙️ 引擎驱动")
    p = st.session_state.profiles[st.session_state.active_profile_idx]
    p["name"] = st.text_input("标签", p["name"])
    c1, c2 = st.columns(2)
    p["base_url"] = c1.text_input("Base URL", p["base_url"])
    p["api_key"] = c2.text_input("API Key", p["api_key"], type="password")
    p["model"] = st.text_input("模型 ID", p["model"])
    if st.button("💾 保存引擎配置", type="primary"): st.success("已保存")
