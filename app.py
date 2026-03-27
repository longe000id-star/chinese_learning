# app.py
import streamlit as st
import logging
import os
import json
import base64
import io
import re
import time
import datetime
import tempfile
import zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import groq

# 页面配置必须在最前面
st.set_page_config(
    layout="wide",
    page_title="LVING PDF Assistant",
    initial_sidebar_state="expanded",
    menu_items=None
)

# 配置日志
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

# 导入模块
from config import AVAILABLE_MODELS, DEFAULT_MODEL
from state.session import init_session_state
from utils.data_loader import load_level_data, load_nemt_cet_data, load_teaching_principles
from utils.tts import load_kokoro, has_chinese, text_to_speech, transcribe_audio
from utils.quiz import generate_quiz, auto_generate_reference
from utils.search import global_search, local_search
from utils.ocr import process_ocr_images, process_ocr_pdf
from utils.github import save_to_github, upload_file_to_github
from ui.sidebar import render_sidebar
from ui.main_content import render_main_content
from ocr_image_module import ocr_images_batch, BAIMIAO_CONFIG as IMAGE_OCR_CONFIG, format_results_as_text
from ocr_pdf_module import ocr_pdf, BAIMIAO_CONFIG as PDF_OCR_CONFIG
from utils.helpers import get_base64_of_image, translate_word
# 初始化 Session State
init_session_state()

# 加载背景图片
bg_base64 = get_base64_of_image("background.jpg")
_bg_warning = None
if bg_base64 is None:
    _bg_warning = "Background image not found. Using solid light background."
    bg_css = "background-color: #f0f0f0;"
else:
    bg_css = f"background-image: url('data:image/jpeg;base64,{bg_base64}');"

# 加载 CSS
def load_css():
    try:
        with open("styles.css", "r", encoding="utf-8") as f:
            css_content = f.read()
            css_content = css_content.replace("{{BG_CSS}}", bg_css)
            st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        st.warning("styles.css not found, using default styling")

load_css()

if _bg_warning:
    st.warning(_bg_warning)

# 加载数据
levels_data = load_level_data(st.session_state.language)
nemt_cet_data = load_nemt_cet_data()

# 加载教学原则
TEACHING_PRINCIPLES = load_teaching_principles()

# Groq 客户端
client = groq.Client(api_key=os.environ.get("GROQ_API_KEY") or st.secrets["GROQ_API_KEY"])

# 构建系统提示
def build_system_prompt():
    prompt = f"""You are a language learning assistant helping students learn Languages.
You have access to learning materials across 3 levels covering grammar, vocabulary, and conversation.

TEACHING PRINCIPLES (MUST FOLLOW):
{TEACHING_PRINCIPLES}

Keep your answers concise, clear, and helpful. Focus on what the user is currently studying. No emojis!"""
    return prompt

system_prompt = build_system_prompt()

if not st.session_state.messages:
    st.session_state.messages = [{"role": "system", "content": system_prompt}]

# 定义需要传递给侧边栏和主界面的函数
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
            if not node:
                return None
        content_node = node
        dir_name = ""
        if isinstance(content_node, dict):
            if len(content_node) == 1:
                dir_name = list(content_node.keys())[0]
                content_node = content_node[dir_name]
            elif "name" in content_node:
                dir_name = content_node["name"]
        name_path_parts = []
        temp_data = data
        for path_key in st.session_state.nemt_cet_path:
            temp_data = temp_data.get(path_key, {})
            if isinstance(temp_data, dict) and len(temp_data) > 0:
                if len(temp_data) == 1:
                    inner_dir_name = list(temp_data.keys())[0]
                    name_path_parts.append(inner_dir_name)
                elif "name" in temp_data:
                    name_path_parts.append(temp_data["name"])
        parts = []
        location = " > ".join(name_path_parts) if name_path_parts else st.session_state.selected_nemt_cet
        parts.append(f"The user is currently viewing: {location}")
        if dir_name:
            parts.append(f"Section: {dir_name}")
        elif "name" in content_node:
            parts.append(f"Section: {content_node['name']}")
        if "notes" in content_node and content_node["notes"]:
            parts.append(f"Notes: {content_node['notes']}")
        if "examples" in content_node and content_node["examples"]:
            parts.append("Example sentences:\n" + "\n".join(f"  - {e}" for e in content_node["examples"]))
        if "words" in content_node and content_node["words"]:
            if isinstance(content_node["words"], str):
                words_list = content_node["words"].split(" / ")
            else:
                words_list = content_node["words"]
            parts.append("Words:\n" + "\n".join(f"  - {w}" for w in words_list[:20]))
        return "\n".join(parts)
    else:
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
            parts.append("Vocabulary:\n" + "\n".join(f"  - {v}" for v in node["vocabulary"]))
        return "\n".join(parts)

def get_page_recommendations():
    page_key = get_current_page_key()
    if st.session_state.current_page_key != page_key:
        st.session_state.current_page_key = page_key
    if page_key not in st.session_state.page_recommendations:
        full_page_content = get_current_page_full_content()
        if full_page_content:
            path_string = ""
            mode = ""
            level = None
            if st.session_state.current_mode == "textbook":
                path_string = " > ".join(st.session_state.path)
                mode = "textbook"
                level = st.session_state.level
            else:
                data = nemt_cet_data.get(st.session_state.selected_nemt_cet, {})
                if len(data) == 1 and st.session_state.selected_nemt_cet in data:
                    data = data[st.session_state.selected_nemt_cet]
                name_path_parts = []
                temp_data = data
                for path_key in st.session_state.nemt_cet_path:
                    temp_data = temp_data.get(path_key, {})
                    if isinstance(temp_data, dict) and len(temp_data) > 0:
                        if len(temp_data) == 1:
                            inner_dir_name = list(temp_data.keys())[0]
                            name_path_parts.append(inner_dir_name)
                        elif "name" in temp_data:
                            name_path_parts.append(temp_data["name"])
                path_string = " > ".join(name_path_parts) if name_path_parts else st.session_state.selected_nemt_cet
                mode = "nemt_cet"
                level = None
            ref_msg = auto_generate_reference(client, level, full_page_content, path_string, mode)
            if ref_msg:
                st.session_state.page_recommendations[page_key] = ref_msg
    return st.session_state.page_recommendations.get(page_key)


# ========== 生成并保存对话总结 ==========
def generate_and_save_summary():
    if not st.session_state.conv_history:
        return

    conv_text = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in st.session_state.conv_history])

    summary_prompt = f"""The following is a conversation between a user and an AI Chinese learning assistant.
Please provide a concise summary (2-3 sentences) covering the main topics discussed.

Conversation:
{conv_text}

Summary:"""
    try:
        response = client.chat.completions.create(
            model=st.session_state.model_name,
            messages=[{"role": "user", "content": summary_prompt}],
            temperature=0.5,
            max_tokens=st.session_state.model_max_tokens,
        )
        new_summary = response.choices[0].message.content.strip()

        if st.session_state.conversation_summary:
            st.session_state.conversation_summary += "\n\n" + new_summary
        else:
            st.session_state.conversation_summary = new_summary

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"""
## Conversation Summary - {timestamp}
{new_summary}

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

        st.session_state.conv_history = []
    except Exception as e:
        logger.error(f"Failed to generate summary: {e}")
        st.warning(f"Failed to generate summary: {e}")

# ========== AI 回复函数 ==========
def get_ai_reply(user_input):
    logger.info(f"User input: {user_input[:100]}...")
    
    # 如果 Quiz 处于活跃状态，处理 Quiz 答案
    if st.session_state.quiz_active and st.session_state.current_quiz:
        questions = st.session_state.current_quiz.get("questions", [])
        
        # 检查用户是否在请求答案
        if user_input.lower().strip() in ["give me answers", "show answers", "give answers", "show me the answers"]:
            reply = "I'd be happy to help! Let's go through the answers together. Which question would you like me to explain first?"
            st.session_state.quiz_active = False
            st.session_state.current_quiz = None
            st.session_state.quiz_answers = {}
            st.session_state.quiz_asked = False
            
            st.session_state.messages.append({"role": "assistant", "content": reply})
            st.session_state.conv_history.append({"role": "assistant", "content": reply})
            
            try:
                audio_bytes, fmt = text_to_speech(client, reply)
                if audio_bytes:
                    st.session_state.pending_tts = (audio_bytes, fmt)
            except Exception as e:
                logger.error(f"TTS error: {e}")
            return
        
        # ========== 解析用户答案（支持多行）==========
        lines = user_input.split('\n')
        all_matches = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            match = re.match(r'^(\d+)[\.\:\-\s]+(.+)$', line)
            if match:
                q_num = int(match.group(1))
                ans = match.group(2).strip()
                all_matches.append((q_num, ans))
        
        if all_matches:
            for q_num, ans in all_matches:
                if 1 <= q_num <= len(questions):
                    st.session_state.quiz_answers[q_num] = ans
        else:
            answer_pattern = re.findall(r'(\d+)[\.\:\-\s]+([^,]+?)(?=\s*\d+[\.\:\-\s]|$)', user_input)
            if answer_pattern:
                for num_str, ans in answer_pattern:
                    q_num = int(num_str)
                    if 1 <= q_num <= len(questions):
                        st.session_state.quiz_answers[q_num] = ans.strip()
            else:
                current_q_num = len(st.session_state.quiz_answers) + 1
                if current_q_num <= len(questions):
                    st.session_state.quiz_answers[current_q_num] = user_input
        
        # ========== 每次输入后都检查是否已完成 ==========
        if len(st.session_state.quiz_answers) >= len(questions):
            qa_list = []
            for i, q in enumerate(questions):
                user_ans = st.session_state.quiz_answers.get(i+1, "No answer")
                qa_list.append(f"Question {i+1}: {q}\nYour answer: {user_ans}")
            
            eval_prompt = f"""You are a language teacher. Evaluate these quiz answers. Be GENEROUS in your evaluation.

CRITICAL RULES:
- Multiple choice: Accept the letter (A, B, C, D) OR the full text. Any answer that indicates the correct option is CORRECT.
- Fill in the blank: Accept ANY word that makes the sentence grammatically correct and semantically meaningful. If multiple answers are possible, ALL are CORRECT. Only mark incorrect if the word makes no sense or creates a grammar error.
- Translation: Accept if the meaning is preserved. Wording can vary. Even if it's not exactly the same, if the idea is conveyed, it's CORRECT.
- Error correction: Accept if the error is fixed. The fix doesn't have to be exactly the same as expected.
- Sentence making: Accept ANY grammatically correct sentence that uses all the given words. Order and wording can vary.

For incorrect answers, DO NOT give the correct answer directly. Instead:
1. Briefly explain why it's not ideal
2. Ask a Socratic question to help

CRITICAL: Must give the correct answers when the user asks for them (e.g., "give me answers", "show answers").

Quiz Questions and Answers:
{chr(10).join(qa_list)}

Return exactly this format:
1: [✅/❌] - [if ❌: brief explanation + Socratic question]
2: [✅/❌] - [if ❌: brief explanation + Socratic question]
3: [✅/❌] - [if ❌: brief explanation + Socratic question]
4: [✅/❌] - [if ❌: brief explanation + Socratic question]
5: [✅/❌] - [if ❌: brief explanation + Socratic question]
Total: X/5"""
            
            try:
                eval_response = client.chat.completions.create(
                    model=st.session_state.model_name,
                    messages=[{"role": "user", "content": eval_prompt}],
                    temperature=0.3,
                    max_tokens=st.session_state.model_max_tokens,
                )
                evaluation = eval_response.choices[0].message.content.strip()
                
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                entry = f"""
## Quiz Record - {timestamp}

**Topic:** {st.session_state.current_quiz.get("topic", "General")}
**Mode:** {st.session_state.language}

### Quiz:
{st.session_state.current_quiz.get("quiz_text", "No quiz text")}

### User Answers:
{chr(10).join([f"{i+1}. {st.session_state.quiz_answers.get(i+1, 'No answer')}" for i in range(len(questions))])}

### Evaluation:
{evaluation}

---
"""
                with open("feedback.md", "a", encoding="utf-8") as f:
                    f.write(entry)
                try:
                    with open("feedback.md", "r", encoding="utf-8") as f:
                        full_feedback_content = f.read()
                    save_to_github("feedback.md", full_feedback_content, f"Add quiz record - {timestamp}")
                except Exception as e:
                    logger.error(f"Failed to read feedback.md for GitHub upload: {e}")

                reply = evaluation + "\n\nGreat job! Let me know if you have any questions about the feedback."
                
                st.session_state.quiz_active = False
                st.session_state.current_quiz = None
                st.session_state.quiz_answers = {}
                st.session_state.quiz_asked = False
                
                st.session_state.messages.append({"role": "assistant", "content": reply})
                st.session_state.conv_history.append({"role": "assistant", "content": reply})
                
                try:
                    audio_bytes, fmt = text_to_speech(client, reply)
                    if audio_bytes:
                        st.session_state.pending_tts = (audio_bytes, fmt)
                except Exception as e:
                    logger.error(f"TTS error: {e}")
                return
                
            except Exception as e:
                logger.error(f"Evaluation error: {e}")
                reply = f"Evaluation failed: {str(e)}\n\nPlease try again."
                st.session_state.messages.append({"role": "assistant", "content": reply})
                st.session_state.conv_history.append({"role": "assistant", "content": reply})
                try:
                    audio_bytes, fmt = text_to_speech(client, reply)
                    if audio_bytes:
                        st.session_state.pending_tts = (audio_bytes, fmt)
                except Exception as e:
                    logger.error(f"TTS error: {e}")
                return
        else:
            answered = set(st.session_state.quiz_answers.keys())
            next_q_num = 1
            while next_q_num in answered:
                next_q_num += 1
            
            if next_q_num <= len(questions):
                current_q_text = questions[next_q_num - 1] if next_q_num - 1 < len(questions) else f"Question {next_q_num}"
                reply = f"Please answer question {next_q_num}: {current_q_text}\n\nUse format: '{next_q_num}. answer' (e.g., '1. A')"
            else:
                reply = f"Please answer the remaining questions."
            
            st.session_state.messages.append({"role": "assistant", "content": reply})
            st.session_state.conv_history.append({"role": "assistant", "content": reply})
            
            try:
                audio_bytes, fmt = text_to_speech(client, reply)
                if audio_bytes:
                    st.session_state.pending_tts = (audio_bytes, fmt)
            except Exception as e:
                logger.error(f"TTS error: {e}")
            return
    
    # ========== 正常处理用户输入（非 Quiz 状态）==========
    st.session_state.messages.append({"role": "user", "content": user_input})
    st.session_state.user_msg_count += 1
    st.session_state.conv_history.append({"role": "user", "content": user_input})

    full_page = get_current_page_full_content()
    context_msgs = st.session_state.messages.copy()

    if st.session_state.language:
        lang_msg = {"role": "system", "content": f"The user is currently learning {st.session_state.language}."}
        context_msgs.insert(1, lang_msg)

    if full_page:
        insert_idx = 2 if st.session_state.language else 1
        context_msgs.insert(insert_idx, {"role": "system", "content": full_page})

    if st.session_state.conversation_summary:
        summary_msg = {"role": "system", "content": f"[Previous conversation summary]\n{st.session_state.conversation_summary}"}
        base = 1
        if st.session_state.language:
            base += 1
        if full_page:
            base += 1
        context_msgs.insert(base, summary_msg)

    try:
        response = client.chat.completions.create(
            model=st.session_state.model_name,
            messages=context_msgs,
            temperature=0.7,
            max_tokens=st.session_state.model_max_tokens,
        )
        reply = response.choices[0].message.content.strip()
        logger.info(f"AI reply: {reply[:100]}...")
    except Exception as e:
        logger.error(f"AI reply error: {e}")
        reply = f"[Error: {e}]"

    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.session_state.conv_history.append({"role": "assistant", "content": reply})

    try:
        audio_bytes, fmt = text_to_speech(client, reply)
        if audio_bytes:
            st.session_state.pending_tts = (audio_bytes, fmt)
    except Exception as e:
        logger.error(f"TTS error in get_ai_reply: {e}")

    if st.session_state.user_msg_count % 5 == 0 and st.session_state.user_msg_count > 0:
        generate_and_save_summary()

# ========== AI 回复函数（带图片）==========
def get_ai_reply_with_image(user_input, image_bytes):
    logger.info(f"User input with image: {user_input[:100]}...")
    
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    mime_type = st.session_state.get("image_mime", "image/jpeg")
    image_url = f"data:{mime_type};base64,{image_base64}"
    
    context_msgs = st.session_state.messages.copy()
    
    full_page = get_current_page_full_content()
    if full_page:
        context_msgs.insert(1, {"role": "system", "content": full_page})
    
    if st.session_state.language:
        lang_msg = {"role": "system", "content": f"The user is currently learning {st.session_state.language}."}
        context_msgs.insert(1, lang_msg)
    
    if st.session_state.conversation_summary:
        summary_msg = {"role": "system", "content": f"[Previous conversation summary]\n{st.session_state.conversation_summary}"}
        base = 1
        if st.session_state.language:
            base += 1
        if full_page:
            base += 1
        context_msgs.insert(base, summary_msg)
    
    context_msgs.append({
        "role": "user",
        "content": [
            {"type": "text", "text": user_input},
            {"type": "image_url", "image_url": {"url": image_url}}
        ]
    })
    
    try:
        response = client.chat.completions.create(
            model=st.session_state.model_name,
            messages=context_msgs,
            temperature=0.7,
            max_tokens=st.session_state.model_max_tokens,
        )
        reply = response.choices[0].message.content.strip()
        logger.info(f"AI reply with image: {reply[:100]}...")
    except Exception as e:
        logger.error(f"AI reply error with image: {e}")
        reply = f"[Error: {e}]"
    
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.session_state.conv_history.append({"role": "assistant", "content": reply})
    
    try:
        audio_bytes, fmt = text_to_speech(client, reply)
        if audio_bytes:
            st.session_state.pending_tts = (audio_bytes, fmt)
    except Exception as e:
        logger.error(f"TTS error in get_ai_reply_with_image: {e}")

# 渲染侧边栏
render_sidebar(levels_data, nemt_cet_data, client, system_prompt, get_current_page_full_content, get_ai_reply)

# TTS 音频播放
if st.session_state.pending_tts:
    audio_bytes, fmt = st.session_state.pending_tts
    st.audio(audio_bytes, format=fmt, autoplay=True)
    st.session_state.pending_tts = None

# 渲染主内容
render_main_content(levels_data, nemt_cet_data, client, get_current_page_full_content, get_page_recommendations, get_ai_reply)