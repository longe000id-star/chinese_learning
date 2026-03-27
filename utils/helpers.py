# utils/helpers.py
import base64
import re
import logging
import datetime
import streamlit as st
from utils.github import save_to_github
from utils.tts import has_chinese

logger = logging.getLogger(__name__)

def get_base64_of_image(image_path):
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except FileNotFoundError:
        return None

def translate_word(client, word, target_lang="Chinese"):
    try:
        logger.info(f"Translating word: {word}")
        clean_word = re.sub(r'[^a-zA-Z\u4e00-\u9fff\s-]', '', word).strip()
        clean_word = clean_word.split()[0] if clean_word else word
        clean_word = clean_word.lower() if not has_chinese(clean_word) else clean_word
        
        if not clean_word or len(clean_word) < 1:
            logger.warning(f"Invalid word after cleaning: {word}, returning original")
            return word
        
        prompt = f"""Translate the following word to {target_lang}. Only return the translation word, nothing else.
Word: {clean_word}
Translation:"""
        
        response = client.chat.completions.create(
            model=st.session_state.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=50,
        )
        translation = response.choices[0].message.content.strip()
        
        if not translation:
            logger.warning(f"Empty translation for '{clean_word}', returning original")
            return clean_word
        
        logger.info(f"Translation for '{clean_word}': '{translation}'")
        return translation
    except Exception as e:
        logger.error(f"Translation error for '{word}': {e}")
        return word

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