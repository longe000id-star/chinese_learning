import json
import base64
import io
import re
import os
import time
import logging
import datetime
import streamlit as st
import groq
import requests
import tempfile
import zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
# 导入OCR模块
try:
    from ocr_image_module import ocr_images_batch, BAIMIAO_CONFIG as IMAGE_OCR_CONFIG, format_results_as_text, save_results_to_txt
    from ocr_pdf_module import ocr_pdf, BAIMIAO_CONFIG as PDF_OCR_CONFIG
except ImportError:
    pass

# ---------- 配置日志记录 ----------
if not os.path.exists("logs"):
    os.makedirs("logs")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/app.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ---------- 模型配置 ----------
AVAILABLE_MODELS = {
    "Llama 4 Scout 17B": {
        "id": "meta-llama/llama-4-scout-17b-16e-instruct",
        "max_tokens": 8192
    },
    "Llama 3.3 70B": {
        "id": "llama-3.3-70b-versatile",
        "max_tokens": 8192
    },
    "Llama 3.1 8B": {
        "id": "llama-3.1-8b-instant",
        "max_tokens": 8192
    },
    "GPT OSS 120B": {
        "id": "openai/gpt-oss-120b",
        "max_tokens": 8192
    },
    "GPT OSS 20B": {
        "id": "openai/gpt-oss-20b",
        "max_tokens": 8192
    },
    "Qwen 3 32B": {
        "id": "qwen/qwen3-32b",
        "max_tokens": 8192
    },
    "Kimi K2 Instruct": {
        "id": "moonshotai/kimi-k2-instruct-0905",
        "max_tokens": 8192
    },
    "Groq Compound": {
        "id": "groq/compound",
        "max_tokens": 8192
    },
    "Groq Compound Mini": {
        "id": "groq/compound-mini",
        "max_tokens": 8192
    },
}
DEFAULT_MODEL = "Llama 3.3 70B"

# ---------- 核心修复：模型参数同步函数 ----------
def sync_model_params():
    """当用户在下拉菜单选择模型时，立即同步全局 session_state"""
    selected = st.session_state.model_selector_ui
    model_info = AVAILABLE_MODELS[selected]
    st.session_state.selected_model = selected
    st.session_state.model_name = model_info["id"]
    st.session_state.model_max_tokens = model_info["max_tokens"]
    logger.info(f"Model successfully switched to: {selected}")

# 初始化模型选择状态
if "selected_model" not in st.session_state:
    st.session_state.selected_model = DEFAULT_MODEL
if "model_name" not in st.session_state:
    st.session_state.model_name = AVAILABLE_MODELS[DEFAULT_MODEL]["id"]
if "model_max_tokens" not in st.session_state:
    st.session_state.model_max_tokens = AVAILABLE_MODELS[DEFAULT_MODEL]["max_tokens"]

# ---------- GitHub 配置 ----------
GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN")
REPO_OWNER = st.secrets.get("GITHUB_REPO_OWNER")
REPO_NAME = st.secrets.get("GITHUB_REPO_NAME")
GITHUB_ENABLED = GITHUB_TOKEN and REPO_OWNER and REPO_NAME

# ---------- 加载 Quiz 题型模板 ----------
def load_quiz_template():
    try:
        with open("chinese_test_template.txt", "r", encoding="utf-8") as f:
            content = f.read()
            logger.info("Successfully loaded chinese_test_template.txt")
            return content
    except FileNotFoundError:
        logger.warning("chinese_test_template.txt not found, using default template")
        return """
1. 单选题（Multiple Choice）：
   题目描述：以下哪个选项最符合题意？
   A. 选项A
   B. 选项B
   C. 选项C
   D. 选项D
2. 填空题（Fill in the blank）：
   请用正确的词语完成以下句子：
   ______
3. 翻译题（Translation）：
   请将以下句子翻译成中文：
   ______
"""
QUIZ_TEMPLATE = load_quiz_template()

# ---------- GitHub 上传函数 ----------
def upload_file_to_github(file_path, content, commit_message):
    """上传文件到 GitHub"""
    if not GITHUB_ENABLED:
        logger.warning("GitHub not configured, skipping upload")
        return False
    api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    try:
        response = requests.get(api_url, headers=headers)
        if response.status_code == 200:
            file_data = response.json()
            existing_content = base64.b64decode(file_data["content"]).decode("utf-8")
            if existing_content == content:
                logger.info(f"File {file_path} unchanged, skipping upload")
                return True
            sha = file_data["sha"]
        else:
            sha = None
        data = {
            "message": commit_message,
            "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            "sha": sha
        }
        response = requests.put(api_url, headers=headers, json=data)
        if response.status_code in [200, 201]:
            logger.info(f"Successfully uploaded {file_path} to GitHub")
            return True
        else:
            logger.error(f"GitHub upload failed: {response.text}")
            return False
    except Exception as e:
        logger.error(f"GitHub upload error: {e}")
        return False

def save_to_github(file_path, content, commit_message):
    """保存文件到 GitHub（如果配置了）或本地"""
    if GITHUB_ENABLED:
        return upload_file_to_github(file_path, content, commit_message)
    else:
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"Saved to local {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save locally: {e}")
            return False

# ---------- 加载 Teaching Principles ----------
def load_teaching_principles():
    try:
        with open("teaching_principle.txt", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return """Core: Guide, Don't Answer
NEVER give direct answers. Use guidance instead.
Guidance: Analogy, examples, simple words, Socratic questions
Feedback: Show score, indicate correct/incorrect. DO NOT give answers unless requested.
Log every quiz to feedback.md"""
TEACHING_PRINCIPLES = load_teaching_principles()

# ---------- Quiz 状态管理 ----------
if "quiz_active" not in st.session_state:
    st.session_state.quiz_active = False
if "current_quiz" not in st.session_state:
    st.session_state.current_quiz = None
if "quiz_answers" not in st.session_state:
    st.session_state.quiz_answers = {}
if "quiz_asked" not in st.session_state:
    st.session_state.quiz_asked = False

# ---------- 保存对话总结到 GitHub ----------
def save_conversation_summary(summary):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"""
## Conversation Summary - {timestamp}
{summary}
---
"""
    existing_content = ""
    try:
        with open("conversation_summary.txt", "r", encoding="utf-8") as f:
            existing_content = f.read()
    except FileNotFoundError:
        pass
    new_content = existing_content + entry if existing_content else "# Conversation Summaries\n\n" + entry
    save_to_github("conversation_summary.txt", new_content, f"Add conversation summary - {timestamp}")
    try:
        with open("conversation_summary.txt", "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        logger.error(f"Failed to save local summary: {e}")

# ---------- 生成 Quiz ----------
def generate_quiz(topic, full_page_content):
    if st.session_state.language == "Chinese":
        template = """
### 1. 单选题 (Multiple Choice)
**Instruction:** Choose the ONE best answer.
---
### 2. 填空题 (Fill in the blank)
**Instruction:** Fill in the blank with the correct word.
---
### 3. 翻译题 (Translation)
**Instruction:** Translate into English.
---
### 4. 改错题 (Error correction)
**Instruction:** Find and correct the mistake.
---
### 5. 造句题 (Sentence making)
**Instruction:** Use the given words to make a sentence.
"""
    else:
        template = """
### 1. 单选题 (Multiple Choice)
**Instruction:** Choose the ONE best answer.
---
### 2. 填空题 (Fill in the blank)
**Instruction:** Fill in the blank with the correct word.
---
### 3. 翻译题 (Translation)
**Instruction:** Translate into Chinese.
---
### 4. 改错题 (Error correction)
**Instruction:** Find and correct the mistake.
---
### 5. 造句题 (Sentence making)
**Instruction:** Use the given words to make a sentence.
"""
    prompt = f"""You are a language test designer. Based on the topic and content below, generate a COMPLETE quiz with ALL 5 question types.
**Topic:** {topic}
**Current Content:** {full_page_content[:800] if full_page_content else "No additional content"}
**Question Types (generate ONE question for EACH type):**
{template}
**STRUCTURE REQUIREMENTS:**
Use EXACTLY this format with 5 numbered questions:
## Quiz: {topic}
1. [Question 1 - Multiple Choice with A, B, C, D options]
2. [Question 2 - Fill in the blank with a complete sentence and a blank]
3. [Question 3 - Translation question with a full sentence to translate]
4. [Question 4 - Error correction question with a sentence containing one error]
5. [Question 5 - Sentence making question with 3-5 words to arrange]
**CRITICAL RULES:**
- Create COMPLETE, answerable questions based on "{topic}"
- Multiple choice: Provide 4 realistic options (A, B, C, D)
- Fill in the blank: Create a complete sentence with one blank (____)
- Translation: Provide a full sentence to translate
- Error correction: Provide a sentence with ONE specific error
- Sentence making: Provide 3-5 words that can form a meaningful sentence
- NEVER include the answer
- Number questions 1 through 5 only
Generate the quiz:"""
    try:
        response = client.chat.completions.create(
            model=st.session_state.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=st.session_state.model_max_tokens,
        )
        quiz_text = response.choices[0].message.content.strip()
        lines = quiz_text.split('\n')
        cleaned_lines = []
        question_count = 0
        for line in lines:
            if re.match(r'^\d+\.', line.strip()):
                question_count += 1
                if question_count <= 5:
                    cleaned_lines.append(line)
            else:
                if question_count <= 5:
                    cleaned_lines.append(line)
        return "\n".join(cleaned_lines)
    except Exception as e:
        logger.error(f"Quiz generation error: {e}")
        return None

# ---------- 背景图片转换 ----------
def get_base64_of_image(image_path):
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except FileNotFoundError:
        return None
bg_base64 = get_base64_of_image("background.jpg")
if bg_base64 is None:
    bg_css = "background-color: #f0f0f0;"
else:
    bg_css = f"background-image: url('data:image/jpeg;base64,{bg_base64}');"

# Page config
st.set_page_config(layout="wide", page_title="LVING PDF Assistant", initial_sidebar_state="collapsed", menu_items=None)

# ---------- 初始化语言状态 ----------
if "language" not in st.session_state:
    st.session_state.language = "Chinese"

# ---------- 加载所有 Level 数据 ----------
@st.cache_data
def load_level_data(language):
    levels = {}
    suffix = "_en" if language == "English" else ""
    for i in range(1, 4):
        try:
            filename = f"level{i}{suffix}.json"
            with open(filename, "r", encoding="utf-8") as f:
                levels[f"Level {i}"] = json.load(f)
        except FileNotFoundError:
            st.error(f"{filename} not found.")
            st.stop()
    return levels
levels_data = load_level_data(st.session_state.language)

# ---------- 加载 NEMT & CET 数据 ----------
@st.cache_data
def load_nemt_cet_data():
    nemt_cet_data = {}
    files_to_load = ["TEM-8.json", "NEMT.json", "CET-46.json"]
    for filename in files_to_load:
        try:
            with open(filename, "r", encoding="utf-8") as f:
                nemt_cet_data[filename.replace('.json', '')] = json.load(f)
        except FileNotFoundError:
            nemt_cet_data[filename.replace('.json', '')] = {}
    return nemt_cet_data
nemt_cet_data = load_nemt_cet_data()

# 状态管理
if "current_mode" not in st.session_state:
    st.session_state.current_mode = "textbook"
if "selected_nemt_cet" not in st.session_state:
    st.session_state.selected_nemt_cet = None
if "nemt_cet_path" not in st.session_state:
    st.session_state.nemt_cet_path = []

# ---------- Groq 客户端 ----------
client = groq.Client(api_key=os.environ.get("GROQ_API_KEY") or st.secrets["GROQ_API_KEY"])

# ---------- 加载 Kokoro TTS ----------
@st.cache_resource
def load_kokoro():
    try:
        from kokoro_onnx import Kokoro
        model_path = "kokoro-chinese/model_static.onnx"
        voices_path = "kokoro-chinese/voices"
        if os.path.exists(model_path) and os.path.exists(voices_path):
            return Kokoro(model_path, voices_path)
        return None
    except Exception: return None

# ---------- 语音转文字 ----------
def transcribe_audio(audio_bytes):
    try:
        transcription = client.audio.transcriptions.create(
            file=("audio.wav", audio_bytes, "audio/wav"),
            model="whisper-large-v3",
        )
        return transcription.text
    except Exception as e:
        logger.error(f"语音识别失败: {e}")
        return None

def has_chinese(text):
    return bool(re.search(r'[\u4e00-\u9fff]', text))

# ---------- 文字转语音 ----------
def text_to_speech(text):
    kokoro = load_kokoro()
    if kokoro is not None:
        try:
            import soundfile as sf
            voice = "zf_001" if has_chinese(text) else "af_sol"
            samples, sample_rate = kokoro.create(text, voice=voice, speed=1.0)
            buf = io.BytesIO()
            sf.write(buf, samples, sample_rate, format="WAV")
            buf.seek(0)
            return buf.read(), "audio/wav"
        except Exception as e:
            logger.error(f"Kokoro TTS error: {e}")
    try:
        response = client.audio.speech.create(
            model="canopylabs/orpheus-v1-english",
            voice="autumn",
            input=text,
            response_format="wav",
        )
        return response.read(), "audio/wav"
    except Exception as e:
        logger.error(f"Orpheus TTS error: {e}")
        return None, None

# ---------- 构建系统提示 ----------
def build_system_prompt(levels):
    prompt = f"""You are a language learning assistant helping students learn Languages.
TEACHING PRINCIPLES:
{TEACHING_PRINCIPLES}
Keep answers concise, no emojis!"""
    return prompt
system_prompt = build_system_prompt(levels_data)

# ---------- 初始化聊天状态 ----------
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": system_prompt}]
if "level" not in st.session_state:
    st.session_state.level = None
if "path" not in st.session_state:
    st.session_state.path = []
if "chat_open" not in st.session_state:
    st.session_state.chat_open = False

# ========== 状态补全 ==========
if "conversation_summary" not in st.session_state:
    st.session_state.conversation_summary = ""
if "page_recommendations" not in st.session_state:
    st.session_state.page_recommendations = {}
if "current_page_key" not in st.session_state:
    st.session_state.current_page_key = None
if "flip_states" not in st.session_state:
    st.session_state.flip_states = {}

# ---------- 获取当前页面标识与内容 ----------
def get_current_page_key():
    if st.session_state.current_mode == "textbook":
        return f"textbook_{st.session_state.level}_{'_'.join(st.session_state.path)}"
    else:
        return f"nemt_cet_{st.session_state.selected_nemt_cet}_{'_'.join(st.session_state.nemt_cet_path)}"

def get_current_page_full_content():
    if st.session_state.current_mode == "nemt_cet":
        if not st.session_state.selected_nemt_cet or not st.session_state.nemt_cet_path:
            return None
        data = nemt_cet_data.get(st.session_state.selected_nemt_cet, {})
        if len(data) == 1 and st.session_state.selected_nemt_cet in data:
            data = data[st.session_state.selected_nemt_cet]
        node = data
        for key in st.session_state.nemt_cet_path:
            node = node.get(key, {})
            if not node: return None
        content_node = node
        parts = [f"The user is viewing: {' > '.join(st.session_state.nemt_cet_path)}"]
        if isinstance(content_node, dict):
            if "notes" in content_node: parts.append(f"Notes: {content_node['notes']}")
            if "examples" in content_node: parts.append("Examples:\n" + "\n".join(content_node["examples"]))
        return "\n".join(parts)
    else:
        if not st.session_state.level or not st.session_state.path:
            return None
        data = levels_data[f"Level {st.session_state.level}"]
        node = data
        for key in st.session_state.path:
            node = node.get(key, {})
            if not node: return None
        parts = [f"Viewing: {' > '.join(st.session_state.path)}"]
        if "notes" in node: parts.append(f"Notes: {node['notes']}")
        return "\n".join(parts)

# ---------- 搜索功能 ----------
def search_in_json(data, query, path=[]):
    results = []
    if isinstance(data, dict):
        for key, value in data.items():
            new_path = path + [key]
            if query.lower() in key.lower():
                results.append({"path": new_path, "type": "key", "content": key})
            if isinstance(value, (dict, list)):
                results.extend(search_in_json(value, query, new_path))
            elif isinstance(value, str) and query.lower() in value.lower():
                results.append({"path": new_path, "type": "content", "content": value})
    elif isinstance(data, list):
        for i, item in enumerate(data):
            new_path = path + [f"Item {i+1}"]
            results.extend(search_in_json(item, query, new_path))
    return results

# ---------- 侧边栏 UI 布局 ----------
with st.sidebar:
    st.title("Control Center")
    
    # 语言切换
    new_lang = st.selectbox("Language / 语言", ["Chinese", "English"], 
                            index=0 if st.session_state.language == "Chinese" else 1)
    if new_lang != st.session_state.language:
        st.session_state.language = new_lang
        st.rerun()

    st.divider()

    # 1. 模型选择器（核心修复：绑定回调）
    st.selectbox(
        "AI Model Selection",
        options=list(AVAILABLE_MODELS.keys()),
        index=list(AVAILABLE_MODELS.keys()).index(st.session_state.selected_model),
        key="model_selector_ui",
        on_change=sync_model_params
    )
    st.caption(f"Current Model ID: `{st.session_state.model_name}`")

    st.divider()

    # 2. 模式切换
    mode_options = ["Textbook", "NEMT & CET"]
    selected_mode_ui = st.radio("Study Mode", mode_options, 
                                index=0 if st.session_state.current_mode == "textbook" else 1)
    st.session_state.current_mode = "textbook" if selected_mode_ui == "Textbook" else "nemt_cet"

    st.divider()

    # 3. 搜索框
    search_query = st.text_input("🔍 Search Lessons", "")
    if search_query:
        search_target = levels_data if st.session_state.current_mode == "textbook" else nemt_cet_data
        search_results = search_in_json(search_target, search_query)
        if search_results:
            for res in search_results[:5]:
                if st.button(f"Go to: {' > '.join(res['path'])}", key=f"search_{res['path']}"):
                    if st.session_state.current_mode == "textbook":
                        st.session_state.level = res['path'][0].split()[-1]
                        st.session_state.path = res['path'][1:]
                    else:
                        st.session_state.selected_nemt_cet = res['path'][0]
                        st.session_state.nemt_cet_path = res['path'][1:]
                    st.rerun()
        else:
            st.write("No results found.")

# ---------- 主界面逻辑 ----------
if st.session_state.current_mode == "textbook":
    col_nav, col_main = st.columns([1, 3])
    
    with col_nav:
        st.subheader("Curriculum")
        lvl_display = [f"Level {i}" for i in range(1, 4)]
        selected_lvl = st.selectbox("Select Level", lvl_display, 
                                    index=int(st.session_state.level)-1 if st.session_state.level else 0)
        st.session_state.level = selected_lvl.split()[-1]
        
        level_content = levels_data.get(selected_lvl, {})
        # 递归渲染路径选择
        current_node = level_content
        new_path = []
        for i, p in enumerate(st.session_state.path):
            options = list(current_node.keys())
            if not options: break
            idx = options.index(p) if p in options else 0
            sel = st.selectbox(f"Select {'Unit' if i==0 else 'Sub-topic'}", options, index=idx, key=f"path_{i}")
            new_path.append(sel)
            current_node = current_node.get(sel, {})
        
        # 允许继续深入
        if isinstance(current_node, dict) and current_node:
            more_options = list(current_node.keys())
            if more_options and "notes" not in more_options:
                sel_more = st.selectbox("Next level", ["-- Select --"] + more_options, key=f"path_new")
                if sel_more != "-- Select --":
                    new_path.append(sel_more)
                    st.session_state.path = new_path
                    st.rerun()
        st.session_state.path = new_path

    with col_main:
        if st.session_state.path:
            st.markdown(f"### {' > '.join(st.session_state.path)}")
            # 显示笔记内容
            if isinstance(current_node, dict) and "notes" in current_node:
                st.info(current_node["notes"])
            
            # Quiz 生成按钮
            if st.button("🚀 Generate Quiz for this Page"):
                full_content = get_current_page_full_content()
                with st.spinner("AI is thinking..."):
                    quiz_txt = generate_quiz(st.session_state.path[-1], full_content)
                    if quiz_txt:
                        st.session_state.current_quiz = quiz_txt
                        st.session_state.quiz_active = True
            
            if st.session_state.quiz_active and st.session_state.current_quiz:
                st.markdown("---")
                st.markdown(st.session_state.current_quiz)

else: # NEMT & CET 模式
    # 此处逻辑与 Textbook 类似，渲染 nemt_cet_data
    st.subheader("NEMT & CET Specialized Training")
    selected_exam = st.selectbox("Select Exam Type", list(nemt_cet_data.keys()))
    st.session_state.selected_nemt_cet = selected_exam
    # 简化的路径导航...
    st.write(f"Content for {selected_exam} will appear here.")

# ---------- 底部聊天室交互 ----------
st.divider()
st.subheader("💬 AI Tutor Chat")

# 渲染对话历史
for message in st.session_state.messages[1:]:
    with st.chat_message(message["role"]):
        st.write(message["content"])

# 处理输入
if prompt := st.chat_input("Ask a question..."):
    # 如果有 Quiz 正在进行，将上下文注入
    context_prefix = ""
    if st.session_state.quiz_active:
        context_prefix = f"[Context: User is currently taking a quiz on {st.session_state.path[-1]}] "
    
    st.session_state.messages.append({"role": "user", "content": context_prefix + prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        try:
            # 这里的 client 使用之前定义的 Groq 客户端
            # 核心修复点：这里会自动使用 st.session_state.model_name
            chat_response = client.chat.completions.create(
                model=st.session_state.model_name,
                messages=st.session_state.messages,
                max_tokens=st.session_state.model_max_tokens,
                temperature=0.7
            )
            response_text = chat_response.choices[0].message.content
            st.write(response_text)
            st.session_state.messages.append({"role": "assistant", "content": response_text})
            
            # 每 5 轮保存一次摘要
            if len(st.session_state.messages) % 10 == 0:
                save_conversation_summary(response_text[:200] + "...")
        except Exception as e:
            st.error(f"Chat error: {e}")

# 脚本结束