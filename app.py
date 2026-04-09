import streamlit as st
import streamlit.components.v1 as components
from openai import OpenAI
import io
import json
import os
import re
import requests
from datetime import datetime
from docx import Document

# ==========================================
# 1. 页面配置与前端美化 (UI 升级)
# ==========================================
st.set_page_config(page_title="ZenMux 创作者工作站", page_icon="🐙", layout="wide")
st.markdown("""
    <style>
    .stButton>button { border-radius: 8px; font-weight: bold; transition: all 0.3s; }
    .stChatInput { padding-bottom: 20px; }
    /* 隐藏原生烦人的全屏按钮等元素 */
    button[title="View fullscreen"] {display: none;}
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 本地数据库引擎 (持久化存储)
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
# 3. 核心辅助函数 (黑科技模块)
# ==========================================
def render_copy_button(text):
    """注入 Google AI Studio 风格的极简无感复制按钮"""
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
    """纯享版洗稿引擎：双层正则过滤机制"""
    # 1. 清除常见的 AI 寒暄与废话 (如: "好的，以下是为你生成的小说：")
    text = re.sub(r'^\s*(好的|没问题|非常荣幸|收到|为你生成|以下是|这是为您|正文开始|下面是).*?[:：]\n*', '', text, flags=re.MULTILINE|re.IGNORECASE)
    # 2. 清除类似 "第X章：XXX" 的章节标题
    text = re.sub(r'^\s*第[零一二三四五六七八九十百千0-9]+[章回节卷].*?\n', '', text, flags=re.MULTILINE)
    # 3. 清除 Markdown 的代码块包裹符
    text = re.sub(r'```[a-zA-Z]*\n?', '', text)
    # 4. 清除文末常见的废话总结
    text = re.sub(r'\n*(希望这|如果有需要|请告诉我|期待您的反馈).*$', '', text, flags=re.IGNORECASE)
    # 5. 清理多余的连续空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

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
# 4. 状态初始化 (从硬盘加载数据)
# ==========================================
if "initialized" not in st.session_state:
    st.session_state.profiles = load_data("profiles.json", [{
        "name": "默认主账号", "base_url": "", "api_key": "", "model": "anthropic/claude-sonnet-4.6",
        "use_temperature": True, "temperature": 0.8, "use_max_tokens": True, "max_tokens": 4096,
        "global_system_prompt": "你是一名网文作家。直接输出内容，不要有废话。"
    }])
    st.session_state.sops = load_data("sops.json", {
        "小说基础流水线": {
            "steps": [{"prompt": "撰写第【{循环索引}】章，包含环境描写。", "loop": 2, "reference": ""}],
            "triggers": [{"type": "terminate", "keyword": "全文完", "action": ""}]
        }
    })
    # memory.json 用于存储各个账号的历史生成记忆
    st.session_state.memory = load_data("memory.json", {}) 
    
    st.session_state.active_profile_idx = 0
    st.session_state.current_page = "🤖 自动化流水线"
    st.session_state.free_chat_msgs = []
    st.session_state.auto_engine = {
        "is_running": False, "is_finished": False, "messages": [],
        "sop_name": "", "topic": "", "global_file": "",
        "current_step_idx": 0, "current_loop_idx": 1,
        "pending_instruction": "", "last_finish_reason": ""
    }
    st.session_state.initialized = True

# 自动保存钩子函数
def save_profiles(): save_data("profiles.json", st.session_state.profiles)
def save_sops(): save_data("sops.json", st.session_state.sops)
def save_memory(): save_data("memory.json", st.session_state.memory)

# ==========================================
# 5. 全局侧边栏导航
# ==========================================
with st.sidebar:
    st.header("🐙 创作者中枢")
    st.write("") 
    pages = ["🤖 自动化流水线", "💬 自由聊天区", "📝 SOP与风格蒸馏", "⚙️ 账号与引擎配置"]
    for p in pages:
        btn_type = "primary" if st.session_state.current_page == p else "secondary"
        if st.button(p, use_container_width=True, type=btn_type):
            st.session_state.current_page = p
            st.rerun()

    active_p = st.session_state.profiles[st.session_state.active_profile_idx]
    st.divider()
    st.caption(f"🟢 **当前账号**: {active_p['name']}\n\n🧠 **模型**: {active_p['model']}")
    
    if st.session_state.current_page == "💬 自由聊天区":
        st.divider()
        st.header("🛠️ 聊天操作区")
        if st.button("🗑️ 清空对话", use_container_width=True):
            st.session_state.free_chat_msgs = []; st.rerun()

# ==========================================
# 模块 1: 自动化流水线 (引擎核心)
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
                if not active_p["api_key"]: st.error("请先在配置中填入 API Key！")
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
        # 结果验收面板 (解决重启丢失问题)
        if engine["messages"] or engine["is_finished"]:
            st.markdown("### 📦 验收成果")
            sel_msgs = [m for m in engine["messages"] if m["role"] == "assistant" and m.get("selected", True)]
            raw_text = "\n\n".join([m["content"] for m in sel_msgs])
            pure_text = clean_novel_text(raw_text)
            
            # --- 存储本地记忆 ---
            if engine["is_finished"]:
                st.success("✅ 任务已全自动完成！")
                if st.button("💾 将本次佳作存入该账号记忆库 (用于风格蒸馏)", use_container_width=True):
                    acc_name = active_p["name"]
                    if acc_name not in st.session_state.memory: st.session_state.memory[acc_name] = []
                    st.session_state.memory[acc_name].append({
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "topic": engine["topic"],
                        "content": pure_text[:2000] # 保存前2000字作为风格记忆足够了
                    })
                    save_memory()
                    st.toast("已成功存入本地数据库！", icon="💾")

            c1, c2 = st.columns(2)
            with c1: st.download_button("📥 标准全文 (TXT)", raw_text, f"{engine['topic']}_完整.txt", "text/plain", use_container_width=True)
            with c2: st.download_button("✨ 纯享正文 (TXT)", pure_text, f"{engine['topic']}_纯正文.txt", "text/plain", use_container_width=True, help="自动清洗废话和章节标题")
            
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

        # 引擎执行逻辑核心 (不再强制刷新清空数据)
        if engine["is_running"]:
            client, profile = get_client()
            sop_data = st.session_state.sops[engine["sop_name"]]
            steps = sop_data["steps"]
            triggers = sop_data.get("triggers", [])
            curr_step = steps[engine["current_step_idx"]]
            
            current_prompt = engine["pending_instruction"] or curr_step["prompt"].replace("{主题}", engine["topic"]).replace("{循环索引}", str(engine["current_loop_idx"]))
            engine["pending_instruction"] = ""
            
            engine["messages"].append({"role": "user", "content": current_prompt, "selected": False})
            with st.chat_message("user"): st.markdown(f"*(⚡ 指令)*: {current_prompt}")
                
            api_msgs = [{"role": "system", "content": profile.get("global_system_prompt", "")}]
            if engine["global_file"]: api_msgs.append({"role": "system", "content": f"【全局设定】\n{engine['global_file']}"})
            if curr_step.get("reference"): api_msgs.append({"role": "system", "content": f"【本阶段设定】\n{curr_step['reference']}"})
            api_msgs.extend([{"role": m["role"], "content": m["content"]} for m in engine["messages"]])
            
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
                                    engine["is_running"] = False; engine["is_finished"] = True
                                    hit_trigger = True; break
                                elif t["type"] == "intervene":
                                    engine["pending_instruction"] = t["action"]
                                    hit_trigger = True; break
                                    
                    if not hit_trigger:
                        if engine["current_loop_idx"] < curr_step.get("loop", 1):
                            engine["current_loop_idx"] += 1
                        else:
                            engine["current_step_idx"] += 1; engine["current_loop_idx"] = 1
                        if engine["current_step_idx"] >= len(steps):
                            engine["is_running"] = False; engine["is_finished"] = True
                            
                    st.rerun() # 状态已强锁定在 engine 中，安全刷新
                except Exception as e:
                    st.error(f"引擎故障: {e}"); engine["is_running"] = False

# ==========================================
# 模块 2: 自由聊天区 (沉浸式+JS复制)
# ==========================================
elif st.session_state.current_page == "💬 自由聊天区":
    st.title("💬 独立交流区")
    st.caption("与自动化流水线物理隔离。")
    
    for msg in st.session_state.free_chat_msgs:
        if msg["role"] == "system": continue
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                render_copy_button(msg["content"])

    if prompt := st.chat_input("探讨设定、查资料..."):
        if not active_p["api_key"]: st.error("缺 API Key！"); st.stop()
        st.session_state.free_chat_msgs.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        
        client, profile = get_client()
        api_msgs = [{"role": "system", "content": profile.get("global_system_prompt", "")}]
        api_msgs.extend([{"role": m["role"], "content": m["content"]} for m in st.session_state.free_chat_msgs])
        
        with st.chat_message("assistant"):
            try:
                resp = client.chat.completions.create(**build_api_kwargs(profile, api_msgs))
                full_resp = st.write_stream(resp)
                render_copy_button(full_resp)
                st.session_state.free_chat_msgs.append({"role": "assistant", "content": full_resp})
                st.rerun()
            except Exception as e:
                st.error(f"请求失败: {e}")

# ==========================================
# 模块 3: SOP 与风格蒸馏 (大招模块)
# ==========================================
elif st.session_state.current_page == "📝 SOP与风格蒸馏":
    tab_sop, tab_style = st.tabs(["🧩 编写 SOP 工作流", "🧠 AI 风格蒸馏引擎 (记忆提炼)"])
    
    with tab_sop:
        col1, col2 = st.columns([1, 2.5])
        with col1:
            st.subheader("SOP 库")
            s_name = st.radio("选择", list(st.session_state.sops.keys())) if st.session_state.sops else None
            if st.button("➕ 创建 SOP"):
                st.session_state.sops[f"新SOP {len(st.session_state.sops)}"] = {"steps": [{"prompt": "", "loop": 1}], "triggers": []}
                save_sops(); st.rerun()
                
        with col2:
            if s_name:
                sop = st.session_state.sops[s_name]
                st.subheader(f"编辑: {s_name}")
                new_steps = []
                for i, step in enumerate(sop["steps"]):
                    with st.container(border=True):
                        st.markdown(f"**阶段 {i+1}**")
                        c1, c2 = st.columns([4, 1])
                        with c1: p_val = st.text_area("指令", step["prompt"], height=60, key=f"p_{i}", label_visibility="collapsed")
                        with c2: l_val = st.number_input("循环", min_value=1, value=step.get("loop", 1), key=f"l_{i}")
                        ref = step.get("reference", "")
                        with st.expander("📁 挂载特定参考文本"): ref = st.text_area("粘贴资料", ref, key=f"r_{i}")
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
                save_sops()

    with tab_style:
        st.header("🧠 账号风格提取与蒸馏")
        st.markdown("通过分析当前账号过往生成的优秀作品，**自动反思并提炼出系统提示词 (Prompt)**。让AI越写越像你想要的风格。")
        
        acc_mem = st.session_state.memory.get(active_p["name"], [])
        if not acc_mem:
            st.info(f"当前账号【{active_p['name']}】的记忆库为空。请先去自动化工作台生成并保存优秀作品。")
        else:
            st.success(f"当前账号记忆库已积累 {len(acc_mem)} 篇作品。")
            with st.expander("🔍 预览记忆库"):
                for idx, item in enumerate(acc_mem):
                    st.write(f"**[{item['time']}] {item['topic']}**")
                    st.caption(item['content'][:100] + "...")
            
            if st.button("🔥 立即执行风格蒸馏", type="primary", use_container_width=True):
                if not active_p["api_key"]: st.error("缺 API Key！"); st.stop()
                client, profile = get_client()
                # 把记忆库里的文章喂给模型
                combined_texts = "\n\n---\n\n".join([m['content'] for m in acc_mem[-3:]]) # 取最近3篇
                distill_prompt = f"""你是一名顶级的提示词工程师和文学分析师。请深度分析以下几篇小说的写作风格（关注文风、遣词造句、环境描写、人物塑造和情绪基调）。
请总结出一段严谨的【系统提示词 System Prompt】。未来的AI只要使用你的这段提示词，就能完美复刻这种风格进行创作。
注意：你的回复只能包含这段提示词的纯文本，不要有任何如"好的"等废话，直接输出 Prompt！
以下是样本材料：
{combined_texts}"""

                with st.spinner("正在深度分析文风并提炼灵魂提示词..."):
                    try:
                        resp = client.chat.completions.create(model=profile["model"], messages=[{"role": "user", "content": distill_prompt}])
                        distilled_prompt = resp.choices[0].message.content.strip()
                        
                        # 自动更新并保存到账号预设中
                        active_p["global_system_prompt"] = distilled_prompt
                        save_profiles()
                        
                        st.success("🎉 蒸馏成功！该账号的【全局系统提示词】已被永久强化更新！")
                        st.info(f"**提炼出的专属灵魂提示词:**\n\n{distilled_prompt}")
                    except Exception as e:
                        st.error(f"蒸馏失败: {e}")

# ==========================================
# 模块 4: 账号与引擎配置
# ==========================================
elif st.session_state.current_page == "⚙️ 账号与引擎配置":
    st.header("⚙️ 多账号与底层引擎管理")
    col_list, col_edit = st.columns([1, 2.5])
    
    with col_list:
        st.subheader("账号(渠道)库")
        p_names = [p["name"] for p in st.session_state.profiles]
        idx = st.radio("切换账号", range(len(p_names)), format_func=lambda x: p_names[x], index=st.session_state.active_profile_idx)
        st.session_state.active_profile_idx = idx
        if st.button("➕ 新增账号", use_container_width=True):
            st.session_state.profiles.append(DEFAULT_PROFILES[0].copy())
            st.session_state.profiles[-1]["name"] = f"新账号 {len(p_names)+1}"
            save_profiles(); st.rerun()

    with col_edit:
        st.subheader("账号底层参数")
        p = st.session_state.profiles[idx]
        
        p["name"] = st.text_input("账号/渠道名称", p["name"])
        c1, c2 = st.columns(2)
        with c1: p["base_url"] = st.text_input("Base URL", p["base_url"])
        with c2: p["api_key"] = st.text_input("API Key", p["api_key"], type="password")
        p["model"] = st.text_input("模型 (Model ID)", p["model"])
                
        st.markdown("#### 🎛️ 参数动态开关 (部分模型不兼容可关)")
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

        p["global_system_prompt"] = st.text_area("🌍 专属人设 Prompt (可被风格蒸馏自动修改)", p.get("global_system_prompt", ""), height=150)
        
        save_profiles() # 实时保存修改
