"""
音频转录服务
"""
import os
from pathlib import Path
from typing import Optional, Dict, Any

import httpx

from app.config import (
    TRANSCRIPTION_API_URL,
    TRANSCRIPTION_API_TOKEN,
    TRANSCRIPTION_DEFAULT_MODEL,
    TRANSCRIPTION_DEFAULT_LANGUAGE,
    TRANSCRIPTION_DEFAULT_RESPONSE_FORMAT,
)


class TranscriptionError(Exception):
    """音频转录错误"""
    pass


async def transcribe_audio(
    audio_file_path: Path,
    model: Optional[str] = None,
    language: Optional[str] = None,
    response_format: Optional[str] = None,
) -> Dict[str, Any]:
    """
    调用音频转录 API 进行转录
    
    Args:
        audio_file_path: 音频文件路径
        model: 使用的模型，默认使用配置中的模型
        language: 语言代码，默认使用配置中的语言
        response_format: 响应格式，默认使用配置中的格式
        
    Returns:
        转录结果字典
        
    Raises:
        TranscriptionError: 如果转录失败
    """
    if not audio_file_path.exists():
        raise TranscriptionError(f"音频文件不存在: {audio_file_path}")
    
    # 使用配置中的默认值
    model = model or TRANSCRIPTION_DEFAULT_MODEL
    language = language or TRANSCRIPTION_DEFAULT_LANGUAGE
    response_format = response_format or TRANSCRIPTION_DEFAULT_RESPONSE_FORMAT
    
    # 检查 token 是否配置
    if not TRANSCRIPTION_API_TOKEN or TRANSCRIPTION_API_TOKEN.strip() == "":
        raise TranscriptionError("转录 API Token 未配置，请在 config.py 中设置 TRANSCRIPTION_API_TOKEN")
    
    # 准备请求头（不包含 Content-Type，让 httpx 自动设置 multipart/form-data）
    # 匹配 curl 命令中的关键 headers
    headers = {
        "User-Agent": "Apifox/1.0.0 (https://apifox.com)",
        "Authorization": f"Bearer {TRANSCRIPTION_API_TOKEN.strip()}",
        "Accept": "*/*",
        # 注意：Host 和 Connection 由 httpx 自动处理，不需要手动设置
    }
    
    # 读取文件内容
    with open(audio_file_path, "rb") as f:
        file_content = f.read()
    
    # 准备 multipart/form-data
    # 使用 files 和 data 参数，httpx 会自动处理 multipart 格式
    # 注意：httpx 会自动处理 Content-Type 和 boundary
    files = {
        "file": (audio_file_path.name, file_content, "audio/mpeg"),
    }
    
    # 表单数据（字符串值，httpx 会自动处理）
    data = {
        "model": model,
        "language": language,
        "response_format": response_format,
    }
    
    try:
        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
            response = await client.post(
                TRANSCRIPTION_API_URL,
                headers=headers,
                files=files,
                data=data,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        error_detail = e.response.text if e.response else str(e)
        # 对于 401 错误，提供更详细的提示
        if e.response.status_code == 401:
            raise TranscriptionError(
                f"认证失败 (401): 请检查 config.py 中的 TRANSCRIPTION_API_TOKEN 是否正确。"
                f"原始错误: {error_detail}"
            )
        raise TranscriptionError(
            f"转录 API 请求失败 (状态码 {e.response.status_code}): {error_detail}"
        )
    except httpx.RequestError as e:
        raise TranscriptionError(f"转录 API 请求错误: {str(e)}")
    except Exception as e:
        raise TranscriptionError(f"转录失败: {str(e)}")

