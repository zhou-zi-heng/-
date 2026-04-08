import streamlit as st
from openai import OpenAI
import io
import json
import requests
from docx import Document

st.set_page_config(page_title="ZenMux Agentic 工作台", page_icon="🐙", layout="wide")

# ==========================================
# 1. 默认数据与初始化定义
# ==========================================
DEFAULT_PROFILES = [
    {
        "name": "ZenMux 官方",
        "base_url": "https://zenmux.ai/api/v1",
        "api_key": "",
        "model": "anthropic/claude-sonnet-4.6",
        "temperature": 0.7,
        "max_tokens": 4096,
        "top_p": 1.0,
        "frequency_penalty": 0.0,
        "global_system_prompt": "你是一个强大的 AI 助手。请直接回答问题，不要输出任何废话、套话和自我介绍。"
    }
]

DEFAULT_SOPS = {
    "【演示】长篇循环连载小说": {
        "steps": [
            {"prompt": "请根据主题：【{主题}】，构思一本小说的世界观和3个主要人物。不需要写正文。", "loop": 1},
            {"prompt": "请根据刚才的世界观，详细撰写第【{循环索引}】章的内容。要求字数充实，情节紧凑。", "loop": 3},
            {"prompt": "请给这部小说写一个大结局，并以“全文完”三个字作为文章的最后结尾。", "loop": 1}
        ],
        "triggers": [
            {"type": "terminate", "keyword": "全文完", "action": ""},
            {"type": "intervene", "keyword": "回合生成完毕", "action": "干得不错，请立刻继续下一阶段。"}
        ]
    }
}

# ==========================================
# 2. 全局状态初始化 (严谨的状态机)
# ==========================================
def init_state(key, default_val):
    if key not in st.session_state:
        st.session_state[key] = default_val

init_state("profiles", DEFAULT_PROFILES)
init_state("active_profile_idx", 0)
init_state("sops", DEFAULT_SOPS)
init_state("free_chat_msgs", [])

# 自动化引擎专属状态机
init_state("auto_engine", {
    "is_running": False,
    "is_finished": False,
    "messages": [],
    "sop_name": "",
    "topic": "",
    "file_content": "",
    "current_step_idx": 0,
    "current_loop_idx": 1,
    "pending_instruction": "", # 用于存放突发指令（续写或触发器干预）
    "last_finish_reason": ""
})

# ==========================================
# 3. 核心功能函数
# ==========================================
def get_client():
    profile = st.session_state.profiles[st.session_state.active_profile_idx]
    url = profile["base_url"].strip() or "https://api.openai.com/v1"
    key = profile["api_key"].strip()
    return OpenAI(base_url=url, api_key=key), profile

def fetch_models(base_url, api_key):
    try:
        url = (base_url.strip() or "https://api.openai.com/v1") + "/models"
        headers = {"Authorization": f"Bearer {api_key.strip()}"}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            models = [m["id"] for m in resp.json().get("data", [])]
            return sorted(models)
        return []
    except Exception as e:
        return []

def stream_generator(api_stream):
    st.session_state.auto_engine["last_finish_reason"] = "stop"
    for chunk in api_stream:
        if chunk.choices and chunk.choices[0].delta.content is not None:
            yield chunk.choices[0].delta.content
        if chunk.choices and chunk.choices[0].finish_reason is not None:
            st.session_state.auto_engine["last_finish_reason"] = chunk.choices[0].finish_reason

def generate_word_doc(messages, is_auto=False):
    doc = Document()
    doc.add_heading('AI 生成报告', 0)
    for msg in messages:
        if msg["role"] == "system" or not msg.get("selected", True): continue
        if msg["role"] == "user":
            if is_auto:
                doc.add_heading("📌 引擎执行指令", level=2)
            else:
                doc.add_heading("🧑‍💻 提问", level=2)
            doc.add_paragraph(msg["content"])
        else:
            if not is_auto: doc.add_heading("🤖 AI 回答", level=2)
            doc.add_paragraph(msg["content"])
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

# ==========================================
# 4. 侧边栏导航路由
# ==========================================
st.sidebar.title("🐙 导航中枢")
app_mode = st.sidebar.radio("选择功能模块", [
    "🤖 自动化流水线 (工作台)",
    "💬 自由对话 (手动区)", 
    "📝 SOP 与触发器设计", 
    "⚙️ API 渠道与引擎设置"
])

# 获取当前激活的配置名称显示在侧边栏底部
active_p = st.session_state.profiles[st.session_state.active_profile_idx]
st.sidebar.divider()
st.sidebar.caption(f"🟢 当前引擎: **{active_p['name']}**\n\n🧠 默认模型: {active_p['model']}")

# ==========================================
# 模块 1: API 渠道与引擎设置
# ==========================================
if app_mode == "⚙️ API 渠道与引擎设置":
    st.header("⚙️ 引擎高级配置中心")
    
    col_list, col_edit = st.columns([1, 2.5])
    with col_list:
        st.subheader("渠道预设库")
        profile_names = [p["name"] for p in st.session_state.profiles]
        selected_idx = st.radio("当前生效渠道", range(len(profile_names)), format_func=lambda x: profile_names[x], index=st.session_state.active_profile_idx)
        st.session_state.active_profile_idx = selected_idx
        
        if st.button("➕ 新增渠道预设", use_container_width=True):
            st.session_state.profiles.append(DEFAULT_PROFILES[0].copy())
            st.session_state.profiles[-1]["name"] = f"新渠道 {len(st.session_state.profiles)}"
            st.rerun()
            
        st.divider()
        profile_json = json.dumps(st.session_state.profiles, ensure_ascii=False, indent=2)
        st.download_button("💾 导出渠道配置库", profile_json, "API渠道备份.json", "application/json")
        uploaded_json = st.file_uploader("📂 导入渠道配置", type=["json"])
        if uploaded_json:
            try:
                st.session_state.profiles = json.loads(uploaded_json.getvalue().decode("utf-8"))
                st.session_state.active_profile_idx = 0
                st.success("导入成功！")
                st.rerun()
            except:
                st.error("文件格式错误")

    with col_edit:
        st.subheader("编辑渠道参数")
        p = st.session_state.profiles[selected_idx]
        
        p["name"] = st.text_input("标签名称", p["name"])
        c1, c2 = st.columns(2)
        with c1:
            p["base_url"] = st.text_input("Base URL (接口地址)", p["base_url"], help="留空则默认为 OpenAI 官方地址。如 Grok 填 https://api.x.ai/v1")
        with c2:
            p["api_key"] = st.text_input("API Key (秘钥)", p["api_key"], type="password")
            
        c_model, c_btn = st.columns([3, 1])
        with c_model:
            p["model"] = st.text_input("模型名称 (Model ID)", p["model"])
        with c_btn:
            st.write("") 
            st.write("")
            if st.button("🔄 自动获取模型", help="尝试从上述 BaseURL 抓取模型列表"):
                if p["api_key"]:
                    models = fetch_models(p["base_url"], p["api_key"])
                    if models:
                        st.session_state.temp_models = models
                        st.success(f"成功获取 {len(models)} 个模型")
                    else:
                        st.error("获取失败，请检查 URL 和 Key")
                else:
                    st.warning("请先填写 API Key")
        
        # 如果刚才抓取了模型，显示下拉框辅助填充
        if "temp_models" in st.session_state and st.session_state.temp_models:
            sel_m = st.selectbox("选择抓取到的模型填入", ["(不覆盖)"] + st.session_state.temp_models)
            if sel_m != "(不覆盖)":
                p["model"] = sel_m
                del st.session_state.temp_models
                st.rerun()
                
        st.markdown("#### 🎛️ 生成超参数精调")
        sl1, sl2 = st.columns(2)
        with sl1:
            p["temperature"] = st.slider("Temperature (温度)", 0.0, 2.0, p.get("temperature", 0.7), 0.1, help="越高越具创造力，越低越严谨。")
            p["max_tokens"] = st.slider("Max Tokens (最大长度)", 512, 16384, p.get("max_tokens", 4096), 512)
        with sl2:
            p["top_p"] = st.slider("Top P", 0.0, 1.0, p.get("top_p", 1.0), 0.05)
            p["frequency_penalty"] = st.slider("Frequency Penalty (频率惩罚)", -2.0, 2.0, p.get("frequency_penalty", 0.0), 0.1)

        p["global_system_prompt"] = st.text_area("🌍 全局 System Prompt (影响所有对话和流水线)", p.get("global_system_prompt", ""))
        
        if len(st.session_state.profiles) > 1:
            if st.button("🗑️ 删除此渠道", type="primary"):
                st.session_state.profiles.pop(selected_idx)
                st.session_state.active_profile_idx = 0
                st.rerun()

# ==========================================
# 模块 2: 自由对话 (独立手动区)
# ==========================================
elif app_mode == "💬 自由对话 (手动区)":
    st.header("💬 自由聊天区 (完全隔离)")
    st.caption(f"正在使用渠道: {active_p['name']} | 模型: {active_p['model']}")
    
    col_chat, col_tools = st.columns([3, 1])
    
    with col_tools:
        if st.button("🗑️ 清空当前对话", use_container_width=True):
            st.session_state.free_chat_msgs = []
            st.rerun()
        if st.session_state.free_chat_msgs:
            st.download_button("📥 导出 Word", generate_word_doc(st.session_state.free_chat_msgs, False), "手动对话记录.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)
            
    with col_chat:
        for i, msg in enumerate(st.session_state.free_chat_msgs):
            if msg["role"] == "system": continue
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg["role"] == "assistant":
                    with st.expander("📄 复制文本"):
                        st.code(msg["content"], language="markdown")

        if prompt := st.chat_input("输入内容，随时与 AI 探讨..."):
            if not active_p["api_key"]:
                st.error("请先在「⚙️ API 渠道与引擎设置」中配置秘钥！")
                st.stop()
                
            st.session_state.free_chat_msgs.append({"role": "user", "content": prompt, "selected": True})
            with st.chat_message("user"): st.markdown(prompt)
            
            client, profile = get_client()
            api_msgs = []
            if profile.get("global_system_prompt"):
                api_msgs.append({"role": "system", "content": profile["global_system_prompt"]})
            api_msgs.extend([{"role": m["role"], "content": m["content"]} for m in st.session_state.free_chat_msgs])
            
            with st.chat_message("assistant"):
                try:
                    resp = client.chat.completions.create(
                        model=profile["model"], messages=api_msgs, stream=True,
                        temperature=profile["temperature"], max_tokens=profile["max_tokens"],
                        top_p=profile["top_p"], frequency_penalty=profile["frequency_penalty"]
                    )
                    full_resp = st.write_stream(resp)
                    st.session_state.free_chat_msgs.append({"role": "assistant", "content": full_resp, "selected": True})
                    st.rerun()
                except Exception as e:
                    st.error(f"请求失败: {e}")

# ==========================================
# 模块 3: SOP 与触发器设计
# ==========================================
elif app_mode == "📝 SOP 与触发器设计":
    st.header("📝 SOP 工作流设计中心")
    
    col1, col2 = st.columns([1, 2.5])
    
    with col1:
        st.subheader("SOP 库")
        sop_names = list(st.session_state.sops.keys())
        selected_sop_name = st.radio("选择要编辑的 SOP", sop_names) if sop_names else None
        
        st.divider()
        new_sop_name = st.text_input("新建 SOP 名称")
        if st.button("➕ 创建新 SOP", use_container_width=True) and new_sop_name:
            if new_sop_name not in st.session_state.sops:
                st.session_state.sops[new_sop_name] = {"steps": [{"prompt": "输入指令...", "loop": 1}], "triggers": []}
                st.rerun()
                
        st.divider()
        sop_json = json.dumps(st.session_state.sops, ensure_ascii=False, indent=2)
        st.download_button("💾 导出 SOP 矩阵库", sop_json, "SOP矩阵库备份.json", "application/json")
        up_sop = st.file_uploader("📂 导入 SOP", type=["json"])
        if up_sop:
            try:
                st.session_state.sops = json.loads(up_sop.getvalue().decode("utf-8"))
                st.success("导入成功")
                st.rerun()
            except:
                st.error("格式错误")

    with col2:
        if selected_sop_name:
            sop = st.session_state.sops[selected_sop_name]
            st.subheader(f"编辑: {selected_sop_name}")
            
            # --- 阶段编辑 ---
            st.markdown("### 🧩 阶段与循环配置")
            st.info("可用变量：`{主题}` 代表输入主题，`{循环索引}` 代表当前正在第几次循环 (如1,2,3)。")
            
            new_steps = []
            for i, step in enumerate(sop["steps"]):
                with st.container(border=True):
                    st.markdown(f"**阶段 {i+1}**")
                    sc1, sc2 = st.columns([4, 1])
                    with sc1:
                        p_val = st.text_area(f"指令内容 {i}", value=step["prompt"], height=80, label_visibility="collapsed")
                    with sc2:
                        l_val = st.number_input(f"循环次数", min_value=1, max_value=99, value=step.get("loop", 1), key=f"loop_{i}")
                    new_steps.append({"prompt": p_val, "loop": l_val})
                    
            sop["steps"] = new_steps
            
            ca, cb = st.columns(2)
            with ca:
                if st.button("➕ 增加阶段", use_container_width=True):
                    sop["steps"].append({"prompt": "", "loop": 1})
                    st.rerun()
            with cb:
                if len(sop["steps"]) > 1 and st.button("➖ 移除末尾阶段", use_container_width=True):
                    sop["steps"].pop()
                    st.rerun()
                    
            # --- 触发器编辑 ---
            st.markdown("### ⚡ 智能触发器 (监听网络)")
            st.caption("AI 回答完毕后，系统会扫描全文是否包含设定关键词。命中则立刻执行动作。")
            
            new_triggers = []
            for i, t in enumerate(sop.get("triggers", [])):
                with st.container(border=True):
                    tc1, tc2, tc3 = st.columns([1, 1, 2])
                    with tc1:
                        t_type = st.selectbox("规则类型", ["terminate", "intervene"], index=0 if t["type"]=="terminate" else 1, format_func=lambda x: "🛑 强制完结" if x=="terminate" else "💬 插嘴干预", key=f"tt_{i}")
                    with tc2:
                        t_kwd = st.text_input("如果包含关键词", value=t["keyword"], key=f"tk_{i}")
                    with tc3:
                        t_act = st.text_input("则自动发送指令 (完结型无需填)", value=t.get("action", ""), disabled=(t_type=="terminate"), key=f"ta_{i}")
                    new_triggers.append({"type": t_type, "keyword": t_kwd, "action": t_act})
            sop["triggers"] = new_triggers
            
            if st.button("➕ 添加监听规则"):
                sop["triggers"].append({"type": "intervene", "keyword": "", "action": ""})
                st.rerun()
                
            st.divider()
            if st.button("🗑️ 删除整个 SOP", type="primary"):
                del st.session_state.sops[selected_sop_name]
                st.rerun()

# ==========================================
# 模块 4: 自动化流水线工作台 (引擎核心)
# ==========================================
elif app_mode == "🤖 自动化流水线 (工作台)":
    engine = st.session_state.auto_engine
    
    col_ctrl, col_view = st.columns([1, 2.5])
    
    with col_ctrl:
        st.header("⚙️ 引擎控制台")
        
        if engine["is_running"]:
            st.warning("⚠️ 自动化流水线正在高速运转中...")
            st.progress(min(engine["current_step_idx"] / max(len(st.session_state.sops[engine["sop_name"]]["steps"]), 1), 1.0))
            st.write(f"当前阶段: {engine['current_step_idx']+1} | 循环: {engine['current_loop_idx']}")
            if st.button("⏹️ 强制急停", type="primary", use_container_width=True):
                engine["is_running"] = False
                st.rerun()
        else:
            sel_sop = st.selectbox("1. 挂载 SOP 预设", list(st.session_state.sops.keys()))
            in_topic = st.text_input("2. 注入 {主题} 变量", placeholder="例如：人工智能的未来")
            up_file = st.file_uploader("3. 挂载参考库 (可选)", type=['txt', 'md'])
            
            if st.button("🚀 点火启动", type="primary", use_container_width=True):
                if not active_p["api_key"]: st.error("请先配置 API Key！")
                elif not in_topic: st.error("请注入主题！")
                else:
                    engine.update({
                        "is_running": True, "is_finished": False, "messages": [],
                        "sop_name": sel_sop, "topic": in_topic,
                        "file_content": up_file.getvalue().decode("utf-8") if up_file else "",
                        "current_step_idx": 0, "current_loop_idx": 1,
                        "pending_instruction": "", "last_finish_reason": ""
                    })
                    st.rerun()
                    
        # 导出面板
        st.divider()
        if engine["messages"] or engine["is_finished"]:
            st.markdown("### 📦 成果验收")
            selected_msgs = [m for m in engine["messages"] if m["role"] == "assistant" and m.get("selected", True)]
            st.success(f"已捕获 {len(selected_msgs)} 个有效内容块。")
            
            final_text = "\n\n".join([m["content"] for m in selected_msgs])
            st.download_button("📥 导出拼接全文 (TXT)", final_text, f"{engine['topic'] or '成果'}.txt", "text/plain", use_container_width=True)
            st.download_button("📥 导出过程文档 (Word)", generate_word_doc(engine["messages"], True), f"{engine['topic'] or '流水线'}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)
            
            if st.button("🧹 清理工作区"):
                engine.update({"messages": [], "is_finished": False, "is_running": False})
                st.rerun()

    with col_view:
        st.header("🖥️ 监视大屏")
        
        # 渲染历史
        for i, msg in enumerate(engine["messages"]):
            if msg["role"] == "system": continue
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg["role"] == "assistant":
                    msg["selected"] = st.checkbox("☑️ 选中参与导出", value=msg.get("selected", True), key=f"ac_{i}")

        # ==================================
        # 🤖 引擎自动执行逻辑核心 (RPA 循环)
        # ==================================
        if engine["is_running"]:
            client, profile = get_client()
            sop_data = st.session_state.sops[engine["sop_name"]]
            steps = sop_data["steps"]
            triggers = sop_data.get("triggers", [])
            
            # 1. 决定本次发送的指令
            if engine["pending_instruction"]:
                current_prompt = engine["pending_instruction"]
                engine["pending_instruction"] = "" # 消耗掉突发指令
            else:
                raw_prompt = steps[engine["current_step_idx"]]["prompt"]
                current_prompt = raw_prompt.replace("{主题}", engine["topic"]).replace("{循环索引}", str(engine["current_loop_idx"]))
            
            # 2. 指令上屏展示
            engine["messages"].append({"role": "user", "content": current_prompt, "selected": False})
            with st.chat_message("user"):
                st.markdown(f"*(⚡ 引擎动作)*: {current_prompt}")
                
            # 3. 构建 API 请求
            api_msgs = []
            if profile.get("global_system_prompt"):
                api_msgs.append({"role": "system", "content": profile["global_system_prompt"]})
            if engine["file_content"]:
                api_msgs.append({"role": "system", "content": f"核心资料库：\n{engine['file_content']}"})
            api_msgs.extend([{"role": m["role"], "content": m["content"]} for m in engine["messages"]])
            
            # 4. 请求模型与拦截
            with st.chat_message("assistant"):
                try:
                    resp = client.chat.completions.create(
                        model=profile["model"], messages=api_msgs, stream=True,
                        temperature=profile["temperature"], max_tokens=profile["max_tokens"],
                        top_p=profile["top_p"], frequency_penalty=profile["frequency_penalty"]
                    )
                    full_resp = st.write_stream(stream_generator(resp))
                    engine["messages"].append({"role": "assistant", "content": full_resp, "selected": True})
                    
                    # 5. 回复后判定逻辑 (状态机跃迁)
                    hit_trigger = False
                    
                    # 5.1 检查是否字数截断
                    if engine["last_finish_reason"] == "length":
                        engine["pending_instruction"] = "⚠️ 注意：因长度限制截断，请紧接着上文最后一个字继续输出，不要重复前文。"
                        st.toast("自动触发长度续写预案！", icon="⚠️")
                        hit_trigger = True
                        
                    # 5.2 扫描全局触发器
                    if not hit_trigger:
                        for t in triggers:
                            if t["keyword"] and t["keyword"] in full_resp:
                                if t["type"] == "terminate":
                                    engine["is_running"] = False
                                    engine["is_finished"] = True
                                    st.toast("🛑 触发 [强制完结] 规则，引擎停止！", icon="🛑")
                                    hit_trigger = True
                                    break
                                elif t["type"] == "intervene":
                                    engine["pending_instruction"] = t["action"]
                                    st.toast(f"⚡ 命中规则 [{t['keyword']}]，触发自动干预！", icon="⚡")
                                    hit_trigger = True
                                    break
                                    
                    # 5.3 正常推进阶段与循环
                    if not hit_trigger:
                        curr_step_obj = steps[engine["current_step_idx"]]
                        # 如果当前阶段的循环还没走完，循环索引+1
                        if engine["current_loop_idx"] < curr_step_obj.get("loop", 1):
                            engine["current_loop_idx"] += 1
                        # 否则进入下一个阶段，循环重置为 1
                        else:
                            engine["current_step_idx"] += 1
                            engine["current_loop_idx"] = 1
                            
                        # 检查是否全部跑完
                        if engine["current_step_idx"] >= len(steps):
                            engine["is_running"] = False
                            engine["is_finished"] = True
                            st.toast("🎉 流水线任务完美收工！", icon="🎊")
                            
                    # 强制刷新 UI 进行下一轮循环
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"引擎发生严重故障: {e}")
                    engine["is_running"] = False
