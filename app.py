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
from utils.data_loader import load_level_data, load_nemt_cet_data, load_teaching_principles, get_word_state_key, save_learning_states
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
        result = "\n".join(parts)
        # 已去掉长度限制，返回完整内容
        return result
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
        result = "\n".join(parts)
        # 已去掉长度限制，返回完整内容
        return result

def get_page_recommendations():
    page_key = get_current_page_key()
    
    # 如果页面没变且已有推荐，直接返回缓存的推荐
    if st.session_state.current_page_key == page_key and page_key in st.session_state.page_recommendations:
        return st.session_state.page_recommendations[page_key]
    
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


# ========== 自动化系统函数 ==========

def auto_update_word_states_from_quiz(evaluation_text):
    """
    Quiz评分后自动更新词汇学习状态：
    - 答对 >= 80% → 未学习的词自动标为"已掌握"(🟢)
    - 答对 < 50%  → 相关词自动标为"需复习"(🔴)
    - 50-79%      → 不自动更改
    """
    correct = 0
    total = 0
    for line in evaluation_text.split('\n'):
        m = re.match(r'^\d+:\s*(✅|❌)', line.strip())
        if m:
            total += 1
            if m.group(1) == '✅':
                correct += 1
    
    if total == 0:
        return
    
    score_ratio = correct / total
    score_msg = ""
    
    if score_ratio >= 0.8:
        new_state = 1  # 已掌握
        score_msg = f"Auto-marked words as Learned ({correct}/{total} correct)"
    elif score_ratio < 0.5:
        new_state = 2  # 需复习
        score_msg = f"Auto-marked words for Review ({correct}/{total} correct)"
    else:
        return  # 50~79%: 不自动更改
    
    updated = False
    
    if st.session_state.current_mode == "textbook" and st.session_state.level and st.session_state.path:
        data = levels_data.get(f"Level {st.session_state.level}", {})
        node = data
        for key in st.session_state.path:
            node = node.get(key, {})
        if "vocabulary" in node and node["vocabulary"]:
            path_str = "_".join(st.session_state.path)
            for idx in range(len(node["vocabulary"])):
                word_key = get_word_state_key("textbook", st.session_state.level, [path_str], idx)
                current = st.session_state.learning_states.get(word_key, 0)
                if new_state == 1 and current == 0:
                    st.session_state.learning_states[word_key] = 1
                    updated = True
                elif new_state == 2:
                    if current != 1:  # 已掌握的不降级
                        st.session_state.learning_states[word_key] = 2
                        updated = True
    
    elif st.session_state.current_mode == "nemt_cet" and st.session_state.selected_nemt_cet and st.session_state.nemt_cet_path:
        data = nemt_cet_data.get(st.session_state.selected_nemt_cet, {})
        if len(data) == 1 and st.session_state.selected_nemt_cet in data:
            data = data[st.session_state.selected_nemt_cet]
        node = data
        for key in st.session_state.nemt_cet_path:
            node = node.get(key, {})
        if "words" in node and node["words"]:
            words_list = node["words"].split(" / ") if isinstance(node["words"], str) else node["words"]
            path_str = "_".join([str(p) for p in st.session_state.nemt_cet_path])
            for idx in range(len(words_list)):
                word_key = get_word_state_key("nemt_cet", st.session_state.selected_nemt_cet, [path_str], idx)
                current = st.session_state.learning_states.get(word_key, 0)
                if new_state == 1 and current == 0:
                    st.session_state.learning_states[word_key] = 1
                    updated = True
                elif new_state == 2:
                    if current != 1:
                        st.session_state.learning_states[word_key] = 2
                        updated = True
    
    if updated:
        save_learning_states(st.session_state.learning_states)
        logger.info(f"[AUTO] {score_msg}")


def send_auto_page_greeting():
    """
    进入新内容页面时自动发一条苏格拉底式问候。
    每个页面只触发一次，不重复打扰。
    """
    full_page = get_current_page_full_content()
    if not full_page:
        return
    
    page_key = get_current_page_key()
    if page_key in st.session_state.page_greeted:
        return
    
    st.session_state.page_greeted.add(page_key)
    
    greeting_prompt = f"""The user just opened a new content page. Give a BRIEF intro (2-3 sentences max):
1. State what this section covers (use the content's target language for language content)
2. End with ONE concise thought-provoking question to activate prior knowledge

Content summary:
{full_page[:600]}

RULES: No emojis. Under 60 words total. Be direct."""
    
    try:
        response = client.chat.completions.create(
            model=st.session_state.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": greeting_prompt}
            ],
            temperature=0.7,
            max_tokens=120,
        )
        greeting = response.choices[0].message.content.strip()
        st.session_state.messages.append({"role": "assistant", "content": greeting})
        st.session_state.conv_history.append({"role": "assistant", "content": greeting})
        try:
            audio_bytes, fmt = text_to_speech(client, greeting)
            if audio_bytes:
                st.session_state.pending_tts = (audio_bytes, fmt)
        except Exception as e:
            logger.error(f"TTS greeting error: {e}")
        logger.info(f"[AUTO] Page greeting sent for {page_key}")
    except Exception as e:
        logger.error(f"[AUTO] Greeting error: {e}")


def pregenerate_quiz_for_page(page_key):
    """
    后台预生成当前页面的 Quiz，缓存到 session_state。
    侧边栏点击 Quiz 时直接从缓存取，无需等待 API。
    """
    if page_key in st.session_state.auto_quiz_cache:
        return  # 已缓存
    
    full_page = get_current_page_full_content()
    if not full_page:
        return
    
    topic = "general"
    sec_match = re.search(r"Section: (.+)", full_page)
    if sec_match:
        topic = sec_match.group(1)
    
    def _do_generate():
        try:
            quiz_text = generate_quiz(client, topic, full_page)
            if quiz_text:
                questions = []
                for line in quiz_text.split('\n'):
                    line = line.strip()
                    if re.match(r'^\d+[\.\s]', line):
                        questions.append(line)
                st.session_state.auto_quiz_cache[page_key] = {
                    "quiz_text": quiz_text,
                    "topic": topic,
                    "questions": questions
                }
                logger.info(f"[AUTO] Quiz pre-generated for {page_key}")
        except Exception as e:
            logger.error(f"[AUTO] Quiz pre-gen error: {e}")
    
    # 用线程执行，不阻塞主流程
    executor = ThreadPoolExecutor(max_workers=1)
    executor.submit(_do_generate)
    executor.shutdown(wait=False)

# ========== 结束：自动化系统函数 ==========

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
    logger.info(f"Current messages count: {len(st.session_state.messages)}")
    
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
                
                # ===== 自动更新词汇状态 =====
                auto_update_word_states_from_quiz(evaluation)
                # ===========================
                
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

    # ========== 将原始 context_msgs 写入文件（调试用，无任何截断）==========
    with open("/tmp/context_msgs_original.txt", "w", encoding="utf-8") as f:
        f.write("="*80 + "\n")
        f.write("ORIGINAL CONTEXT_MSGS (before any truncation):\n")
        f.write("="*80 + "\n")
        for i, msg in enumerate(context_msgs):
            f.write(f"\n--- Message {i+1} ---\n")
            f.write(f"Role: {msg['role']}\n")
            content = msg.get('content', '')
            if isinstance(content, str):
                f.write(f"Content length: {len(content)} chars\n")
                f.write("Content:\n")
                f.write(content + "\n")
            else:
                f.write(f"Content: {content}\n")
        f.write("="*80 + "\n")
    # ========== 结束写入 ==========

    # 注意：已移除所有内容截断和历史长度限制，完全保留原始 context_msgs

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

# ========== 自动化：检测页面切换 ==========
# 当用户导航到新内容页面时，自动发问候 + 预生成 Quiz
_has_content_page = (
    (st.session_state.current_mode == "textbook" and st.session_state.level and len(st.session_state.path) > 1)
    or (st.session_state.current_mode == "nemt_cet" and st.session_state.selected_nemt_cet and st.session_state.nemt_cet_path)
)
if _has_content_page:
    try:
        _current_nav_key = get_current_page_key()
        if _current_nav_key != st.session_state.last_nav_page_key:
            st.session_state.last_nav_page_key = _current_nav_key
            # 自动问候（苏格拉底式）
            send_auto_page_greeting()
            # 预生成 Quiz 缓存（后台线程，不阻塞）
            pregenerate_quiz_for_page(_current_nav_key)
    except Exception as _e:
        logger.error(f"[AUTO] Page-change hook error: {_e}")
# ==========================================

# 渲染侧边栏
render_sidebar(levels_data, nemt_cet_data, client, system_prompt, get_current_page_full_content, get_ai_reply)

# TTS 音频播放
if st.session_state.pending_tts:
    audio_bytes, fmt = st.session_state.pending_tts
    st.audio(audio_bytes, format=fmt, autoplay=True)
    st.session_state.pending_tts = None

# 渲染主内容
render_main_content(levels_data, nemt_cet_data, client, get_current_page_full_content, get_page_recommendations, get_ai_reply)