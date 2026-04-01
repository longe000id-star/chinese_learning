# config.py
import streamlit as st

AVAILABLE_MODELS = {
    "Llama 4 Scout 17B": {"id": "meta-llama/llama-4-scout-17b-16e-instruct", "max_tokens": 8192},
    "Llama 3.3 70B": {"id": "llama-3.3-70b-versatile", "max_tokens": 32768},
    "Llama 3.1 8B": {"id": "llama-3.1-8b-instant", "max_tokens": 131072},
    "GPT OSS 120B": {"id": "openai/gpt-oss-120b", "max_tokens": 65536},
    "GPT OSS 20B": {"id": "openai/gpt-oss-20b", "max_tokens": 65536},
    "Qwen 3 32B": {"id": "qwen/qwen3-32b", "max_tokens": 40960},
    "Kimi K2 Instruct": {"id": "moonshotai/kimi-k2-instruct-0905", "max_tokens": 8192},
    "Groq Compound": {"id": "groq/compound", "max_tokens": 8192},
    "Groq Compound Mini": {"id": "groq/compound-mini", "max_tokens": 8192},
}
DEFAULT_MODEL = "GPT OSS 20B"

GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN")
REPO_OWNER = st.secrets.get("GITHUB_REPO_OWNER")
REPO_NAME = st.secrets.get("GITHUB_REPO_NAME")
GITHUB_ENABLED = GITHUB_TOKEN and REPO_OWNER and REPO_NAME
