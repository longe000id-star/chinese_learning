# utils/data_loader.py
import json
import logging
import streamlit as st

logger = logging.getLogger(__name__)

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

@st.cache_data
def load_level_data(language):
    levels = {}
    suffix = "_en" if language == "English" else ""
    for i in range(1, 4):
        try:
            filename = f"data/level{i}{suffix}.json"   # ✅ 添加 data/ 路径
            with open(filename, "r", encoding="utf-8") as f:
                levels[f"Level {i}"] = json.load(f)
        except FileNotFoundError:
            st.error(f"{filename} not found. Please ensure all level files exist.")
            st.stop()
    return levels

@st.cache_data
def load_nemt_cet_data():
    nemt_cet_data = {}
    files_to_load = ["data/TEM-8.json", "data/NEMT.json", "data/CET-46.json"]   # ✅ 添加 data/ 路径
    
    for filename in files_to_load:
        try:
            with open(filename, "r", encoding="utf-8") as f:
                # 去掉 data/ 前缀和 .json 后缀作为 key
                key = filename.replace('data/', '').replace('.json', '')
                nemt_cet_data[key] = json.load(f)
                logger.info(f"Successfully loaded {filename}")
        except FileNotFoundError:
            key = filename.replace('data/', '').replace('.json', '')
            logger.warning(f"{filename} not found")
            nemt_cet_data[key] = {}
        except json.JSONDecodeError as e:
            key = filename.replace('data/', '').replace('.json', '')
            logger.error(f"JSON parse error in {filename}: {e}")
            nemt_cet_data[key] = {}
    
    return nemt_cet_data