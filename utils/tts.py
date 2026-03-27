# utils/tts.py
import io
import re
import logging
import streamlit as st
import os

logger = logging.getLogger(__name__)

def has_chinese(text):
    """判断文本是否包含中文"""
    return bool(re.search(r'[\u4e00-\u9fff]', text))

@st.cache_resource
def load_kokoro():
    """加载 Kokoro TTS 模型"""
    try:
        from kokoro_onnx import Kokoro
        model_path = "kokoro-chinese/model_static.onnx"
        voices_path = "kokoro-chinese/voices"
        if os.path.exists(model_path) and os.path.exists(voices_path):
            return Kokoro(model_path, voices_path)
        return None
    except Exception:
        return None

def text_to_speech(client, text):
    """
    文字转语音
    
    Args:
        client: Groq 客户端
        text: 要转换的文字
    
    Returns:
        (audio_bytes, format) 或 (None, None)
    """
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
            pass
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

def transcribe_audio(client, audio_bytes):
    """
    语音转文字
    
    Args:
        client: Groq 客户端
        audio_bytes: 音频字节数据
    
    Returns:
        识别出的文字，失败返回 None
    """
    try:
        transcription = client.audio.transcriptions.create(
            file=("audio.wav", audio_bytes, "audio/wav"),
            model="whisper-large-v3",
        )
        return transcription.text
    except Exception as e:
        logger.error(f"语音识别失败: {e}")
        st.error(f"语音识别失败: {e}")
        return None