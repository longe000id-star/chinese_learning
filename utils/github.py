# utils/github.py
import base64
import requests
import logging
from config import GITHUB_TOKEN, REPO_OWNER, REPO_NAME, GITHUB_ENABLED

logger = logging.getLogger(__name__)

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