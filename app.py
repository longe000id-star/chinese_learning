import json
import base64
import io
import re
import os
import streamlit as st
import groq

# ========== 新增：参考资料抓取所需库（可根据需要安装）==========
# 为了演示，我们使用 requests + BeautifulSoup 进行简单的静态抓取
# 实际生产环境中可能需要 Selenium 或 Playwright 来应对动态页面
import requests
from bs4 import BeautifulSoup

# ---------- 将背景图片转换为 Base64 嵌入 CSS ----------
def get_base64_of_image(image_path):
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except FileNotFoundError:
        return None

bg_base64 = get_base64_of_image("background.jpg")
if bg_base64 is None:
    st.warning("Background image not found. Using solid light background.")
    bg_css = "background-color: #f0f0f0;"
else:
    bg_css = f"background-image: url('data:image/jpeg;base64,{bg_base64}');"

# Page config
st.set_page_config(layout="wide", page_title="Chinese Learning Assistant")

# ---------- 加载所有 Level 数据 ----------
@st.cache_data
def load_level_data():
    levels = {}
    for i in range(1, 4):
        try:
            with open(f"level{i}.json", "r", encoding="utf-8") as f:
                levels[f"Level {i}"] = json.load(f)
        except FileNotFoundError:
            st.error(f"level{i}.json not found. Please ensure all level files exist.")
            st.stop()
    return levels

levels_data = load_level_data()

# ---------- Groq 客户端 ----------
client = groq.Client(api_key=os.environ.get("GROQ_API_KEY") or st.secrets["GROQ_API_KEY"])

# ---------- 加载 Kokoro TTS ----------
@st.cache_resource
def load_kokoro():
    try:
        from kokoro_onnx import Kokoro
        # 指向通过 LFS 上传的模型文件
        model_path = "kokoro-chinese/model_static.onnx"
        voices_path = "kokoro-chinese/voices"
        if os.path.exists(model_path) and os.path.exists(voices_path):
            return Kokoro(model_path, voices_path)
        return None
    except Exception:
        return None

# ---------- 语音转文字（Whisper）----------
def transcribe_audio(audio_bytes):
    try:
        transcription = client.audio.transcriptions.create(
            file=("audio.wav", audio_bytes, "audio/wav"),
            model="whisper-large-v3",
        )
        return transcription.text
    except Exception as e:
        return f"[转录失败: {e}]"

# ---------- 判断文本是否含中文 ----------
def has_chinese(text):
    return bool(re.search(r'[\u4e00-\u9fff]', text))

# ---------- 文字转语音 ----------
def text_to_speech(text):
    kokoro = load_kokoro()
    if kokoro is not None:
        try:
            import soundfile as sf
            # 使用保留的中文音色 zf_001 和英文音色 af_sol
            voice = "zf_001" if has_chinese(text) else "af_sol"
            samples, sample_rate = kokoro.create(text, voice=voice, speed=1.0)
            buf = io.BytesIO()
            sf.write(buf, samples, sample_rate, format="WAV")
            buf.seek(0)
            return buf.read(), "audio/wav"
        except Exception:
            pass
    # Fallback: Groq Orpheus
    try:
        response = client.audio.speech.create(
            model="canopylabs/orpheus-v1-english",
            voice="autumn",
            input=text,
            response_format="wav",
        )
        return response.read(), "audio/wav"
    except Exception:
        return None, None

# ---------- 构建系统提示 ----------
def build_system_prompt(levels):
    prompt = """You are a Chinese learning assistant helping students learn Chinese. 
You have access to learning materials across 3 levels covering grammar, vocabulary, and conversation.
Keep your answers concise, clear, and helpful. Focus on what the user is currently studying."""
    return prompt

system_prompt = build_system_prompt(levels_data)

# ---------- 初始化状态 ----------
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": system_prompt}]
if "level" not in st.session_state:
    st.session_state.level = None
if "path" not in st.session_state:
    st.session_state.path = []
if "chat_open" not in st.session_state:
    st.session_state.chat_open = False
if "last_audio_id" not in st.session_state:
    st.session_state.last_audio_id = None
if "pending_tts" not in st.session_state:
    st.session_state.pending_tts = None  # (bytes, fmt)

# ========== 对话总结相关状态 ==========
if "conversation_summary" not in st.session_state:
    st.session_state.conversation_summary = ""          # 存储总结文本
if "conv_history" not in st.session_state:
    st.session_state.conv_history = []                  # 存储未总结的对话（用于生成总结）
if "user_msg_count" not in st.session_state:
    st.session_state.user_msg_count = 0                 # 用户消息计数器（用于触发总结）

# ========== 新增：参考资料推送状态 ==========
if "last_reference_path" not in st.session_state:
    st.session_state.last_reference_path = None          # 记录上次推送的目录路径，避免重复

# ========== 参考资料源配置（可随意扩展）==========
# 每个源包含：名称、URL、适用的等级列表、抓取函数（根据主题返回字符串列表）
# 抓取函数应接收 topic 参数（主题关键词），返回一个列表，每个元素是一条参考内容
def fetch_from_bbc_bitesize(topic, level):
    """
    从 BBC Bitesize 抓取与主题相关的内容（模拟）
    实际可改为使用 Selenium/Playwright 进行动态抓取
    """
    # 这里仅作演示，返回固定内容。真实抓取需解析页面结构
    # 注意：BBC Bitesize 可能需要处理 JavaScript，建议使用无头浏览器
    # 示例：使用 requests 获取页面，但可能不完整
    try:
        # 模拟不同等级对应不同页面区域
        base_url = "https://www.bbc.co.uk/bitesize/subjects/zwd88hv"
        # 使用 requests 获取页面（可能无法获取动态内容）
        # headers = {'User-Agent': 'Mozilla/5.0'}
        # resp = requests.get(base_url, headers=headers, timeout=10)
        # soup = BeautifulSoup(resp.text, 'html.parser')
        # 根据 topic 查找相关内容
        # 实际实现需根据页面结构编写选择器

        # 临时模拟返回
        return [
            f"📖 **BBC Bitesize 推荐**（与「{topic}」相关）\n   • 初级语法：……\n   • 实用对话：……\n   🔗 更多内容：{base_url}"
        ]
    except Exception as e:
        return [f"⚠️ 从 BBC Bitesize 抓取失败：{e}，请稍后再试。"]

# 参考资料源列表，可按等级过滤
REFERENCE_SOURCES = [
    {
        "name": "BBC Bitesize",
        "url": "https://www.bbc.co.uk/bitesize/subjects/zwd88hv",
        "levels": [1, 2, 3],  # 适用于所有等级
        "fetch_func": fetch_from_bbc_bitesize
    },
    # 后续可以添加更多源，例如：
    # {
    #     "name": "其他中文学习网站",
    #     "url": "https://example.com",
    #     "levels": [2, 3],
    #     "fetch_func": lambda topic, level: ["..."]
    # },
]

def get_references_for_topic(level, topic):
    """
    根据等级和主题，从所有匹配的参考源获取内容
    返回合并后的字符串列表
    """
    all_refs = []
    for src in REFERENCE_SOURCES:
        if level in src["levels"]:
            try:
                refs = src["fetch_func"](topic, level)
                if refs:
                    # 添加源标识
                    all_refs.append(f"**{src['name']}**")
                    all_refs.extend(refs)
            except Exception as e:
                all_refs.append(f"⚠️ 从 {src['name']} 获取资料时出错：{e}")
    return all_refs

def auto_push_references(level, current_node):
    """
    当用户进入新目录时，自动获取参考资料并插入聊天窗口
    """
    # 生成当前目录的唯一标识（路径字符串）
    current_path_key = " > ".join(st.session_state.path)
    if st.session_state.last_reference_path == current_path_key:
        return  # 已经推送过，避免重复

    # 提取主题关键词：优先使用节点名称，否则用路径最后一级
    topic = current_node.get("name", st.session_state.path[-1]) if current_node else st.session_state.path[-1]

    with st.spinner(f"正在查找与「{topic}」相关的参考资料..."):
        ref_items = get_references_for_topic(level, topic)

    if ref_items:
        # 组装成一条助手的参考消息
        ref_message = "📚 **自动推送的参考资料**（根据当前学习主题）\n\n" + "\n\n".join(ref_items)
        st.session_state.messages.append({"role": "assistant", "content": ref_message})
        # 可选：生成语音
        audio_bytes, fmt = text_to_speech(ref_message)
        if audio_bytes:
            st.session_state.pending_tts = (audio_bytes, fmt)
        # 记录已推送
        st.session_state.last_reference_path = current_path_key
        st.rerun()  # 刷新聊天区域显示新消息
    else:
        # 没有找到内容，也可以不推送
        pass

# ---------- 获取当前页面内容 ----------
def get_current_page_context():
    if not st.session_state.level or not st.session_state.path:
        return None
    data = levels_data[f"Level {st.session_state.level}"]
    node = data
    for key in st.session_state.path:
        node = node.get(key, {})
        if not node:
            return None
    parts = []
    location = " > ".join(st.session_state.path)
    parts.append(f"The user is currently viewing: {location}")
    if "name" in node:
        parts.append(f"Section: {node['name']}")
    if "notes" in node and node["notes"]:
        parts.append(f"Notes: {node['notes']}")
    if "examples" in node and node["examples"]:
        parts.append("Example sentences:\n" + "\n".join(f"  - {e}" for e in node["examples"]))
    if "vocabulary" in node and node["vocabulary"]:
        parts.append("Vocabulary on this page:\n" + "\n".join(f"  - {v}" for v in node["vocabulary"]))
    return "\n".join(parts) if len(parts) > 1 else None

# ========== 缓存的 AI 回复函数 ==========
@st.cache_data(ttl=3600, max_entries=100)
def cached_chat_completion(system_prompt, page_context, summary_text, user_text):
    """缓存 AI 回复，参数必须可哈希"""
    messages = [{"role": "system", "content": system_prompt}]
    if page_context:
        messages.append({"role": "system", "content": f"[Current page context]\n{page_context}"})
    if summary_text:
        messages.append({"role": "system", "content": f"[Previous conversation summary]\n{summary_text}"})
    messages.append({"role": "user", "content": user_text})
    try:
        response = client.chat.completions.create(
            model="groq/compound",
            messages=messages,
            temperature=0.7,
            max_tokens=8192
        )
        return response.choices[0].message.content
    except Exception as e:
        err = str(e)
        if "rate_limit_exceeded" in err or "quota" in err.lower():
            return "I've reached my usage limit. Please try again in a few moments, or click Clear to start fresh."
        else:
            return f"Sorry, I encountered an error: {err}"

# ========== 生成总结的函数 ==========
def generate_summary(history, old_summary=""):
    """基于历史对话和旧总结生成新总结（使用 AI 自身）"""
    if not history:
        return old_summary
    # 构建总结提示
    prompt = "请用中文总结以下对话的核心内容，保持简洁。"
    if old_summary:
        prompt += f"已有的总结：{old_summary}\n"
    prompt += "新对话：\n" + "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])
    try:
        response = client.chat.completions.create(
            model="groq/compound",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=8192
        )
        new_summary = response.choices[0].message.content
        # 保存到文件（便于调试和持久化）
        with open("conversation_summary.txt", "w", encoding="utf-8") as f:
            f.write(new_summary)
        return new_summary
    except Exception:
        # 如果调用失败，返回旧总结
        return old_summary

# ========== get_ai_reply ==========
def get_ai_reply(user_text):
    # 1. 将用户消息加入历史（用于显示和总结）
    st.session_state.messages.append({"role": "user", "content": user_text})
    st.session_state.conv_history.append({"role": "user", "content": user_text})
    st.session_state.user_msg_count += 1

    # 2. 检查是否需要生成总结（每5条用户消息触发一次）
    if st.session_state.user_msg_count % 5 == 0 and st.session_state.conv_history:
        # 生成总结，基于当前对话历史（包括本次用户消息）和旧总结
        new_summary = generate_summary(st.session_state.conv_history, st.session_state.conversation_summary)
        st.session_state.conversation_summary = new_summary
        # 清空历史，为下一轮总结做准备
        st.session_state.conv_history.clear()

    # 3. 获取当前页面上下文
    page_context = get_current_page_context()

    # 4. 调用缓存的 AI 回复（只传递总结，不传递全部历史）
    reply = cached_chat_completion(
        system_prompt,
        page_context if page_context else "",
        st.session_state.conversation_summary,
        user_text
    )

    # 5. 将 AI 回复存入显示用的 messages，并加入对话历史（用于下次总结）
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.session_state.conv_history.append({"role": "assistant", "content": reply})

    # 6. 生成语音
    audio_bytes, fmt = text_to_speech(reply)
    if audio_bytes:
        st.session_state.pending_tts = (audio_bytes, fmt)

# ---------- 自定义CSS ----------
st.markdown(f"""
<style>
    /* ... 原有CSS保持不变 ... */
    /* 这里省略原CSS，你只需保留原来的样式即可 */
</style>
""", unsafe_allow_html=True)

# ---------- 导航和卡片显示 ----------
st.title("CHINESE LEARNING ASSISTANT")

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("Level 1", use_container_width=True):
        st.session_state.level = 1
        st.session_state.path = ["LEVEL_I"]
        st.rerun()
with col2:
    if st.button("Level 2", use_container_width=True):
        st.session_state.level = 2
        st.session_state.path = ["LEVEL_II"]
        st.rerun()
with col3:
    if st.button("Level 3", use_container_width=True):
        st.session_state.level = 3
        st.session_state.path = ["LEVEL_III"]
        st.rerun()

if st.session_state.level:
    data = levels_data[f"Level {st.session_state.level}"]
    current_node = data
    for key in st.session_state.path:
        current_node = current_node.get(key, {})
        if not current_node:
            st.error("Path error. Please go back.")
            st.stop()

    bread = " > ".join(st.session_state.path)
    st.markdown(f"<div class='breadcrumb'>{bread}</div>", unsafe_allow_html=True)

    if len(st.session_state.path) > 1:
        st.markdown("<div class='back-button'>", unsafe_allow_html=True)
        if st.button("Back", key="back_button"):
            st.session_state.path.pop()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    def display_node(node):
        # ... 原有 display_node 代码保持不变 ...
        pass  # 此处省略，实际使用时请复制原来的 display_node 函数体

    display_node(current_node)

    # ========== 新增：自动推送参考资料 ==========
    auto_push_references(st.session_state.level, current_node)

# ---------- 悬浮聊天窗 ----------
# ... 原有聊天窗口代码保持不变 ...
