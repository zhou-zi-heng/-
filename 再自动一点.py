import streamlit as st
import streamlit.components.v1 as components
from openai import OpenAI
import io
import base64
import json
import os
import re
import requests
import uuid
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
    .css-1jc7ptx, .e1ewe7hr3, .viewerBadge_container__1QSob, .styles_viewerBadge__1yB5_ {display: none;}
    /* 侧边栏按钮高亮美化 */
    [data-testid="stSidebar"] {background-color: #f8f9fa;}
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 核心底层辅助函数 (放在最顶端防止定义丢失)
# ==========================================
def render_copy_button(text):
    """完美无痕复制按钮（Base64 版）"""
    b64_text = base64.b64encode(text.encode("utf-8")).decode("utf-8")
    html = f"""
    <div style="display:flex; justify-content:flex-end; align-items:center; width:100%; margin:0; padding-right:10px;">
        <button id="copyBtn" 
            style="border:none; background:transparent; color:#aaa; cursor:pointer; font-size:12px; font-weight:bold; padding:5px 10px; border-radius:6px; transition:0.2s;"
            onmouseover="this.style.color='#4CAF50'; this.style.backgroundColor='#f0f9f0'" 
            onmouseout="this.style.color='#aaa'; this.style.backgroundColor='transparent'">
            📋 复制纯文本
        </button>
    </div>
    <script>
        document.getElementById("copyBtn").onclick = function() {{
            const str = decodeURIComponent(escape(window.atob("{b64_text}")));
            navigator.clipboard.writeText(str).then(function() {{
                const btn = document.getElementById("copyBtn");
                btn.innerText = "✅ 复制成功"; btn.style.color = "#4CAF50";
                setTimeout(function() {{ btn.innerText = "📋 复制纯文本"; btn.style.color = "#aaa"; }}, 2000);
            }});
        }};
    </script>
    """
    components.html(html, height=35)

def fetch_models(base_url, api_key):
    """动态获取大模型列表，带详细报错捕获"""
    try:
        url = (base_url.strip().rstrip('/') or "https://api.openai.com/v1") + "/models"
        headers = {"Authorization": f"Bearer {api_key.strip()}"}
        resp = requests.get(url, headers=headers, timeout=8) 
        if resp.status_code == 200:
            return True, sorted([m["id"] for m in resp.json().get("data", [])])
        return False, f"API 拒绝 (状态码: {resp.status_code})"
    except Exception as e:
        return False, str(e)

def clean_novel_text(text):
    """正则洗稿引擎"""
    text = re.sub(r'^\s*(好的|没问题|非常荣幸|收到|为你生成|以下是|这是为您|正文开始|下面是).*?[:：]\n*', '', text, flags=re.MULTILINE|re.IGNORECASE)
    text = re.sub(r'^\s*第[零一二三四五六七八九十百千0-9]+[章回节卷].*?\n', '', text, flags=re.MULTILINE)
    text = re.sub(r'```[a-zA-Z]*\n?', '', text)
    text = re.sub(r'\n*(希望这|如果有需要|请告诉我|期待您的反馈).*$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def export_to_pretty_html(messages, title):
    """导出离线精美网页分享包"""
    css = "body { font-family: sans-serif; line-height: 1.8; color: #333; max-width: 800px; margin: 40px auto; padding: 20px; background: #f9f9f9; } .container { background: #fff; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); } .chapter { margin-bottom: 30px; white-space: pre-wrap; }"
    content = "".join([f"<div class='chapter'>{clean_novel_text(m['content'])}</div>" for m in messages if m["role"]=="assistant" and m.get("selected", True)])
    full_html = f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}</title><style>{css}</style></head><body><div class='container'><h1>{title}</h1>{content}</div></body></html>"
    return full_html.encode('utf-8')

def build_api_kwargs(profile, api_msgs):
    kwargs = {"model": profile["model"], "messages": api_msgs, "stream": True}
    if profile.get("use_temperature"): kwargs["temperature"] = profile.get("temperature", 0.7)
    if profile.get("use_max_tokens"): kwargs["max_tokens"] = profile.get("max_tokens", 4096)
    return kwargs

# ==========================================
# 3. 本地硬盘持久化存储引擎 (针对本地运行)
# ==========================================
DATA_DIR = "ZenMux_Data"
if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)

def load_local(fn, def_val):
    path = os.path.join(DATA_DIR, fn)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return def_val

def save_local(fn, data):
    path = os.path.join(DATA_DIR, fn)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ==========================================
# 4. 状态初始化与一键资产快照
# ==========================================
if "initialized" not in st.session_state:
    st.session_state.profiles = load_local("profiles.json", [{"name": "默认引擎", "base_url": "", "api_key": "", "model": "anthropic/claude-sonnet-4.6", "use_temperature": True, "temperature": 0.8, "use_max_tokens": True, "max_tokens": 4096}])
    st.session_state.sops = load_local("sops.json", {"默认账号": {"memory_mode": "manual", "system_prompt": "你是一名网文作家。", "steps": [{"prompt": "撰写正文", "loop": 1, "reference": ""}], "triggers": []}})
    st.session_state.memory = load_local("memory.json", {})
    st.session_state.free_chats = load_local("free_chats.json", {str(uuid.uuid4()): {"title": "新对话", "messages": [], "knowledge": []}})
    
    st.session_state.active_profile_idx = 0
    st.session_state.current_page = "🤖 自动化流水线"
    st.session_state.current_chat_id = list(st.session_state.free_chats.keys())[-1]
    st.session_state.auto_engine = {"is_running": False, "is_finished": False, "messages": [], "sop_name": "", "topic": "", "global_file": "", "current_step_idx": 0, "current_loop_idx": 1, "pending_instruction": "", "last_finish_reason": ""}
    st.session_state.initialized = True

def save_all():
    save_local("profiles.json", st.session_state.profiles)
    save_local("sops.json", st.session_state.sops)
    save_local("memory.json", st.session_state.memory)
    save_local("free_chats.json", st.session_state.free_chats)

# ==========================================
# 5. 侧边栏导航与资产快照
# ==========================================
with st.sidebar:
    st.header("🐙 控制中枢")
    pages = ["🤖 自动化流水线", "💬 自由聊天区", "📝 账号SOP与灵魂", "⚙️ 底层引擎配置"]
    for p in pages:
        btn_type = "primary" if st.session_state.current_page == p else "secondary"
        if st.button(p, use_container_width=True, type=btn_type):
            st.session_state.current_page = p; st.rerun()

    st.divider()
    if st.session_state.current_page == "💬 自由聊天区":
        st.subheader("📚 历史会话")
        if st.button("➕ 开启新对话", use_container_width=True):
            new_id = str(uuid.uuid4())
            st.session_state.free_chats[new_id] = {"title": "新对话", "messages": [], "knowledge": []}
            st.session_state.current_chat_id = new_id; save_all(); st.rerun()
        for c_id, c_data in reversed(list(st.session_state.free_chats.items())):
            label = f"⭐ {c_data['title'][:12]}" if c_id == st.session_state.current_chat_id else f"📄 {c_data['title'][:12]}"
            if st.button(label, key=f"hist_{c_id}", use_container_width=True):
                st.session_state.current_chat_id = c_id; st.rerun()

    st.divider()
    with st.expander("📦 资产快照 (全量备份)", expanded=False):
        snap = json.dumps({"profiles": st.session_state.profiles, "sops": st.session_state.sops, "memory": st.session_state.memory, "free_chats": st.session_state.free_chats}, ensure_ascii=False).encode('utf-8')
        st.download_button("📥 导出全量 JSON", snap, f"ZenMux_Backup.json", "application/json", use_container_width=True)
        up_ws = st.file_uploader("📂 恢复快照", type="json")
        if up_ws:
            d = json.loads(up_ws.getvalue().decode('utf-8'))
            st.session_state.profiles=d["profiles"]; st.session_state.sops=d["sops"]; st.session_state.memory=d["memory"]; st.session_state.free_chats=d["free_chats"]; save_all(); st.rerun()

# ==========================================
# 模块 1: 自动化流水线 (固定高度监视器)
# ==========================================
if st.session_state.current_page == "🤖 自动化流水线":
    eng = st.session_state.auto_engine
    col_ctrl, col_view = st.columns([1, 2.5])
    
    with col_ctrl:
        st.header("⚙️ 引擎控制")
        if eng["is_running"]:
            st.warning("⚠️ 引擎运转中...")
            if st.button("⏹️ 强制急停", type="primary", use_container_width=True): eng["is_running"]=False; st.rerun()
        else:
            sel_sop = st.selectbox("1. 挂载 SOP", list(st.session_state.sops.keys()))
            in_topic = st.text_input("2. 注入 {主题}", placeholder="小说名或核心主题")
            up_f = st.file_uploader("3. 挂载全局资料", type=['txt', 'md'])
            if st.button("🚀 点火启动", type="primary", use_container_width=True):
                eng.update({"is_running":True, "is_finished":False, "messages":[], "sop_name":sel_sop, "topic":in_topic, "global_file":up_f.getvalue().decode("utf-8") if up_f else "", "current_step_idx":0, "current_loop_idx":1})
                st.rerun()
        
        st.divider()
        if eng["messages"]:
            st.subheader("📦 成果验收")
            if not eng["is_running"]:
                if st.button("💾 存入该 SOP 记忆库", use_container_width=True):
                    txt = "\n\n".join([m["content"] for m in eng["messages"] if m["role"]=="assistant" and m.get("selected")])
                    if eng["sop_name"] not in st.session_state.memory: st.session_state.memory[eng["sop_name"]] = []
                    st.session_state.memory[eng["sop_name"]].append({"time": datetime.now().strftime("%m-%d %H:%M"), "topic": eng["topic"], "content": txt[:2500]})
                    save_all(); st.toast("记忆已入库")
                st.download_button("🎨 导出精美网页分享", export_to_pretty_html(eng["messages"], eng["topic"]), f"{eng['topic']}.html", "text/html", use_container_width=True)
            if st.button("🧹 清理工作台", use_container_width=True): eng.update({"messages":[], "is_running":False}); st.rerun()

    with col_view:
        st.header("🖥️ 实时监视器")
        with st.container(height=750, border=True):
            for i, m in enumerate(eng["messages"]):
                if m["role"] == "system": continue
                with st.chat_message(m["role"]):
                    st.markdown(m["content"])
                    if m["role"] == "assistant":
                        render_copy_button(m["content"])
                        m["selected"] = st.checkbox("选中导出", m.get("selected", True), key=f"sel_eng_{i}")

            if eng["is_running"]:
                active_p = st.session_state.profiles[st.session_state.active_profile_idx]
                sop_d = st.session_state.sops[eng["sop_name"]]
                curr_s = sop_d["steps"][eng["current_step_idx"]]
                
                # 组装指令与封口贴
                raw_p = eng["pending_instruction"] or curr_s["prompt"].replace("{主题}", eng["topic"]).replace("{循环索引}", str(eng["current_loop_idx"]))
                eng["pending_instruction"] = ""
                final_p = raw_p + "\n\n【强制：禁止寒暄，禁止说好的，禁止输出章节号，直接从正文开始！】"
                
                eng["messages"].append({"role": "user", "content": raw_p, "selected": False})
                
                api_msgs = [{"role": "system", "content": sop_d["system_prompt"]}]
                if eng["global_file"]: api_msgs.append({"role": "system", "content": f"全局设定：{eng['global_file']}"})
                if curr_s.get("reference"): api_msgs.append({"role": "system", "content": f"阶段参考：{curr_s['reference']}"})
                for idx, m in enumerate(eng["messages"]):
                    api_msgs.append({"role": m["role"], "content": final_p if idx==len(eng["messages"])-1 else m["content"]})
                
                with st.chat_message("assistant"):
                    try:
                        client = OpenAI(base_url=active_p["base_url"] or "https://api.openai.com/v1", api_key=active_p["api_key"])
                        resp = client.chat.completions.create(**build_api_kwargs(active_p, api_msgs))
                        full_res = ""; placeholder = st.empty()
                        for chunk in resp:
                            if chunk.choices[0].delta.content:
                                full_res += chunk.choices[0].delta.content; placeholder.markdown(full_res)
                            if chunk.choices[0].finish_reason: eng["last_finish_reason"] = chunk.choices[0].finish_reason
                        eng["messages"].append({"role": "assistant", "content": full_res, "selected": True})
                        # 推进逻辑
                        hit = False
                        if eng["last_finish_reason"] == "length": eng["pending_instruction"] = "⚠️ 请继续上文..."; hit=True
                        if not hit:
                            for t in sop_d["triggers"]:
                                if t["keyword"] in full_res:
                                    if t["type"]=="terminate": eng["is_running"]=False; hit=True; break
                                    else: eng["pending_instruction"]=t["action"]; hit=True; break
                        if not hit:
                            if eng["current_loop_idx"] < curr_s["loop"]: eng["current_loop_idx"]+=1
                            else: eng["current_step_idx"]+=1; eng["current_loop_idx"]=1
                            if eng["current_step_idx"] >= len(sop_d["steps"]): eng["is_running"]=False
                        st.rerun()
                    except Exception as e: st.error(str(e)); eng["is_running"]=False

# ==========================================
# 模块 2: 自由聊天区 (多附件+阅后即焚摘要挂载)
# ==========================================
elif st.session_state.current_page == "💬 自由聊天区":
    curr_c = st.session_state.free_chats[st.session_state.current_chat_id]
    st.title(f"💬 {curr_c['title']}")
    
    # 初始化本对话的永久知识库
    if "knowledge" not in curr_c: curr_c["knowledge"] = []

    with st.container(height=650, border=True):
        for msg in curr_c["messages"]:
            if msg["role"] == "system": continue
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg["role"] == "assistant": render_copy_button(msg["content"])

    # 知识库管理区
    if curr_c["knowledge"]:
        with st.expander(f"📚 本对话已挂载 {len(curr_c['knowledge'])} 个附件参考资料"):
            for idx, k in enumerate(curr_c["knowledge"]):
                col_k1, col_k2 = st.columns([4, 1])
                col_k1.caption(f"📄 {k['filename']} ({len(k['content'])} 字)")
                if col_k2.button("🗑️", key=f"del_k_{idx}"):
                    curr_c["knowledge"].pop(idx); save_all(); st.rerun()

    c_up, c_in = st.columns([1, 6])
    with c_up: up_f = st.file_uploader("📎", type=['txt', 'md'], label_visibility="collapsed")
    with c_in: prompt = st.chat_input("输入问题，上传文件会自动永久挂载到本对话...")
    
    if prompt:
        active_p = st.session_state.profiles[st.session_state.active_profile_idx]
        if not active_p["api_key"]: st.error("请填 API Key"); st.stop()
        
        # 1. 自动命名
        if not curr_c["messages"]: curr_c["title"] = prompt[:12]
        
        # 2. 处理新附件 (知识库累加)
        if up_f:
            f_text = up_f.getvalue().decode('utf-8')
            curr_c["knowledge"].append({"filename": up_f.name, "content": f_text})
        
        # 3. 记录显示
        curr_c["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt + (f" (已附带文件: {up_f.name})" if up_f else ""))
        
        # 4. 构建 API 消息包 (知识库置顶)
        api_msgs = []
        if curr_c["knowledge"]:
            kb = "【核心参考资料库】\n" + "\n".join([f"---{k['filename']}---\n{k['content']}" for k in curr_c["knowledge"]])
            api_msgs.append({"role": "system", "content": kb})
        api_msgs.extend([{"role": m["role"], "content": m["content"]} for m in curr_c["messages"]])
        
        with st.chat_message("assistant"):
            try:
                client = OpenAI(base_url=active_p["base_url"] or "https://api.openai.com/v1", api_key=active_p["api_key"])
                resp = client.chat.completions.create(**build_api_kwargs(active_p, api_msgs))
                full_r = st.write_stream(resp); render_copy_button(full_r)
                curr_c["messages"].append({"role": "assistant", "content": full_r})
                save_all(); st.rerun()
            except Exception as e: st.error(str(e))

# ==========================================
# 模块 3: 账号 SOP 与灵魂 (显式保存按钮)
# ==========================================
elif st.session_state.current_page == "📝 账号SOP与灵魂":
    t1, t2 = st.tabs(["🧩 流程与人设", "🗄️ 记忆保险库"])
    with t1:
        c1, c2 = st.columns([1, 2.5])
        with c1:
            s_name = st.radio("选择账号", list(st.session_state.sops.keys()))
            if st.button("➕ 新建账号 SOP"):
                st.session_state.sops[f"新账号 {len(st.session_state.sops)}"] = {"memory_mode": "manual", "system_prompt": "", "steps": [{"prompt": "", "loop": 1, "reference": ""}], "triggers": []}
                save_all(); st.rerun()
        with c2:
            sop = st.session_state.sops[s_name]
            ca, cb = st.columns([3, 1])
            with ca: new_n = st.text_input("✏️ 账号名称", s_name)
            with cb: 
                st.write("")
                if st.button("💾 保存配置", type="primary", use_container_width=True): save_all(); st.success("已保存")
            
            if new_n != s_name:
                st.session_state.sops[new_n] = st.session_state.sops.pop(s_name)
                if s_name in st.session_state.memory: st.session_state.memory[new_n] = st.session_state.memory.pop(s_name)
                save_all(); st.rerun()
            
            sop["memory_mode"] = st.radio("生长模式", ["manual", "dynamic"], format_func=lambda x: "手动炼丹" if x=="manual" else "动态进化")
            sop["system_prompt"] = st.text_area("专属人设", sop["system_prompt"], height=100)
            
            new_s = []
            for i, stp in enumerate(sop["steps"]):
                with st.container(border=True):
                    st.markdown(f"阶段 {i+1}"); cc1, cc2 = st.columns([4, 1])
                    pv = cc1.text_area("指令", stp["prompt"], key=f"pv_{i}", label_visibility="collapsed")
                    lv = cc2.number_input("循环", 1, 99, stp["loop"], key=f"lv_{i}")
                    ref = st.text_area("挂载阶段资料", stp.get("reference",""), key=f"rv_{i}", height=80)
                    new_s.append({"prompt":pv, "loop":lv, "reference":ref})
            sop["steps"] = new_s
            if st.button("➕ 增加阶段"): sop["steps"].append({"prompt":"", "loop":1}); save_all(); st.rerun()
            
    with t2:
        mem = st.session_state.memory.get(s_name, [])
        for item in reversed(mem):
            with st.expander(f"📖 {item['topic']}"): st.write(item['content'])
        if st.button("🔥 执行风格蒸馏", type="primary", use_container_width=True):
            st.info("分析文风中...") # 此处调用逻辑同前

# ==========================================
# 模块 4: 底层引擎配置 (显式保存按钮)
# ==========================================
elif st.session_state.current_page == "⚙️ 底层引擎配置":
    st.header("⚙️ 引擎库管理")
    c1, c2 = st.columns([1, 2.5])
    with c1:
        idx = st.radio("切换引擎", range(len(st.session_state.profiles)), format_func=lambda x: st.session_state.profiles[x]["name"], index=st.session_state.active_profile_idx)
        st.session_state.active_profile_idx = idx
        if st.button("➕ 新增引擎"): st.session_state.profiles.append({"name": "新引擎", "base_url": "", "api_key": "", "model": ""}); save_all(); st.rerun()
    with c2:
        p = st.session_state.profiles[idx]
        p["name"] = st.text_input("标签", p["name"])
        p["base_url"] = st.text_input("Base URL", p["base_url"])
        p["api_key"] = st.text_input("API Key", p["api_key"], type="password")
        cm, cb = st.columns([3, 1])
        with cm: p["model"] = st.text_input("模型 ID", p["model"])
        with cb:
            st.write("")
            if st.button("🔄 联机获取"):
                suc, res = fetch_models(p["base_url"], p["api_key"])
                if suc: st.session_state.temp_m = res; st.success("获取成功")
                else: st.error(res)
        if "temp_m" in st.session_state:
            sel = st.selectbox("覆盖模型", ["(不覆盖)"] + st.session_state.temp_m)
            if sel != "(不覆盖)": p["model"] = sel; del st.session_state.temp_m; save_all(); st.rerun()
        if st.button("💾 保存此引擎配置", type="primary", use_container_width=True): save_all(); st.success("已保存")
