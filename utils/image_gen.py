# utils/image_gen.py
import base64
import logging
import streamlit as st
from typing import Optional, List, Tuple
import requests

logger = logging.getLogger(__name__)

# 可用模型列表（按推荐顺序）
# NOTE: gemini-2.5-flash-image free tier IPM = 0 since Dec 7 2025.
#       Billing must be enabled for ALL these models to generate images via API.
AVAILABLE_MODELS = [
    "gemini-3.1-flash-image-preview",   # ✅ Recommended: latest fast model (billing required)
    "gemini-2.5-flash-image",           # ✅ Previous gen, still works (billing required)
    "gemini-3-pro-image-preview",       # ✅ Highest quality (billing required, higher cost)
]

# API 端点模板
API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# 极简信息图风格指令
STYLE_SPECIFICATION = """
Visual Style Specification (STRICT ADHERENCE REQUIRED):
- Background: Pure White (#FFFFFF). Absolutely no grid lines, gradients, or background patterns.
- Primary Outlines: Solid Black (#000000). Used for all main illustrations, text, and borders.
- Secondary/Emphasis Outlines: Blue (#4285F4), Red (#EA4335), Black (#000000). Use these ONLY for auxiliary details or to emphasize specific parts.
- Drawing Style: Minimalist, clear line art. NO FILL, NO SHADOWS, NO GRADIENTS. Consistent line thickness throughout.
- Typography: Clean sans-serif font. Text must be legible and consist only of the requested language. No decorative symbols.
- Highlighting: Use fluorescent marker-style lines (Green #34A853 background) behind key keywords or numbers to create visual rhythm.
- Layout: If the input contains multiple items or a list of words, EVERY SINGLE ITEM/WORD must be represented by its own distinct illustration. Arrange them in a clean grid or sequential layout.
"""

def get_api_key() -> Optional[str]:
    """从 Streamlit secrets 获取 Google API 密钥"""
    try:
        key = st.secrets.get("GOOGLE_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return None

def generate_image_with_model(prompt: str, model_name: str, api_key: str) -> Tuple[Optional[str], str]:
    """
    使用指定的模型生成图片。

    FIX 1: Added 'generationConfig' with responseModalities: ["TEXT", "IMAGE"].
           Without this, the API returns HTTP 200 but with empty parts — no image, no error.
    FIX 2: Iterate over ALL parts instead of assuming parts[0] contains the image,
           since the response may contain both text and image parts.

    Returns:
        (base64_image, error_message) - 成功时 error_message 为空字符串
    """
    url = API_URL_TEMPLATE.format(model=model_name)
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    data = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        # FIX 1: responseModalities MUST include both "TEXT" and "IMAGE".
        # Using ["IMAGE"] alone also silently returns empty parts.
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        }
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=60)
        if response.status_code != 200:
            error_msg = f"API returned {response.status_code}"
            try:
                error_msg += f": {response.text[:200]}"
            except Exception:
                pass
            return None, error_msg

        response_data = response.json()

        # FIX 2: Iterate over all parts to find the image inline_data.
        # Do not assume the image is always at parts[0].
        parts = (
            response_data
            .get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        for part in parts:
            inline_data = part.get("inlineData", {})
            if "data" in inline_data:
                return inline_data["data"], ""

        return None, "No image data found in any part of the API response"

    except requests.exceptions.Timeout:
        return None, "Request timed out"
    except requests.exceptions.ConnectionError as e:
        return None, f"Connection error: {e}"
    except Exception as e:
        return None, f"Unexpected error: {str(e)[:100]}"


def generate_image_from_prompt(prompt: str, preferred_model: Optional[str] = None) -> Optional[str]:
    """
    生成图片，支持自动回退到其他模型。

    Args:
        prompt: 图片生成提示词
        preferred_model: 可选，优先使用的模型名称

    Returns:
        base64 图片数据，失败返回 None
    """
    api_key = get_api_key()
    if not api_key:
        st.error("Google API key not found. Please add GOOGLE_API_KEY to your secrets.toml")
        logger.error("Missing GOOGLE_API_KEY")
        return None

    # 确定尝试顺序
    if preferred_model and preferred_model in AVAILABLE_MODELS:
        models_to_try = [preferred_model] + [m for m in AVAILABLE_MODELS if m != preferred_model]
    else:
        models_to_try = AVAILABLE_MODELS.copy()

    last_error = ""
    for model in models_to_try:
        logger.info(f"Attempting to generate image with model: {model}")
        img_base64, error = generate_image_with_model(prompt, model, api_key)
        if img_base64:
            logger.info(f"Success with model: {model}")
            return img_base64
        else:
            last_error = error
            logger.warning(f"Model {model} failed: {error}")
            # If billing not enabled, no point trying other models
            if "FAILED_PRECONDITION" in last_error or "billing" in last_error.lower():
                st.error("Billing is not enabled on your Google Cloud project. "
                         "Image generation requires billing even for the free-tier models. "
                         "Enable it at: https://console.cloud.google.com/billing")
                return None
            continue

    st.error(f"Image generation failed with all models. Last error: {last_error}")
    return None


def build_prompt_for_page(content: str, title: str, language: str = "English") -> str:
    """为页面内容构建图片生成 prompt"""
    content_summary = content[:300] if content else ""
    return (
        f"Create a minimalist infographic about '{title}'. "
        f"{STYLE_SPECIFICATION} "
        f"Use {language} for any text. "
        f"Illustrate the main points from the content: {content_summary}"
    )


def build_prompt_for_words(words: List[str], language: str = "English") -> str:
    """为词汇列表构建图片生成 prompt"""
    limited_words = words[:15]
    words_str = ", ".join(limited_words)
    prompt = (
        f"Create a grid of minimalist illustrations for each word: {words_str}. "
        f"{STYLE_SPECIFICATION} "
        f"Label each with the word in {language}."
    )
    if len(words) > 15:
        prompt += f" (Plus {len(words) - 15} more words not shown)"
    return prompt


def generate_image_for_page(
    content: str,
    title: str,
    language: str = "English",
    preferred_model: Optional[str] = None,
) -> Optional[str]:
    """为页面生成信息图"""
    prompt = build_prompt_for_page(content, title, language)
    return generate_image_from_prompt(prompt, preferred_model)


def generate_image_for_words(
    words: List[str],
    language: str = "English",
    preferred_model: Optional[str] = None,
) -> Optional[str]:
    """为词汇列表生成视觉解释图"""
    if not words:
        return None
    prompt = build_prompt_for_words(words, language)
    return generate_image_from_prompt(prompt, preferred_model)