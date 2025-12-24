"""
TTS 音频克隆服务
"""
import json
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any

import httpx

from app.config import (
    TTS_SYNTHESIZE_ASYNC_URL,
    TTS_TASK_QUERY_URL,
    TTS_DOWNLOAD_URL,
)


def get_audio_media_type(filename: str) -> str:
    """
    根据文件扩展名返回对应的 MIME 类型
    
    Args:
        filename: 文件名
        
    Returns:
        MIME 类型字符串
    """
    extension = Path(filename).suffix.lower()
    media_types = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".mpeg": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
        ".m4a": "audio/mp4",
        ".wma": "audio/x-ms-wma",
        ".opus": "audio/opus",
    }
    return media_types.get(extension, "audio/mpeg")


class TTSError(Exception):
    """TTS 服务错误"""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


async def synthesize_audio_async(
    text: str,
    prompt_audio_path: Path,
    emo_control_method: Optional[int] = None,
    emo_weight: Optional[float] = None,
    emo_text: Optional[str] = None,
    max_text_tokens_per_segment: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    emo_audio_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    调用异步语音合成 API 提交合成任务
    
    Args:
        text: 要合成的文本
        prompt_audio_path: 音色参考音频文件路径
        emo_control_method: 情感控制方式: 0-与音色相同, 1-情感参考音频, 2-情感向量, 3-情感文本
        emo_weight: 情感权重
        emo_text: 情感描述文本(当emo_control_method=3时使用)
        max_text_tokens_per_segment: 分句最大Token数
        temperature: 采样温度
        top_p: top_p采样
        top_k: top_k采样
        emo_audio_path: 情感参考音频文件路径(可选)
        
    Returns:
        包含 task_id 的响应字典
        
    Raises:
        TTSError: 如果提交任务失败
    """
    if not prompt_audio_path.exists():
        raise TTSError(f"音色参考音频文件不存在: {prompt_audio_path}")
    
    if emo_audio_path and not emo_audio_path.exists():
        raise TTSError(f"情感参考音频文件不存在: {emo_audio_path}")
    
    # 读取音色参考音频文件
    with open(prompt_audio_path, "rb") as f:
        prompt_audio_content = f.read()
    
    # 根据文件扩展名确定媒体类型
    prompt_audio_media_type = get_audio_media_type(prompt_audio_path.name)
    
    # 准备 multipart/form-data
    files = {
        "prompt_audio": (prompt_audio_path.name, prompt_audio_content, prompt_audio_media_type),
    }
    
    # 如果有情感参考音频，添加到 files
    if emo_audio_path:
        with open(emo_audio_path, "rb") as f:
            emo_audio_content = f.read()
        emo_audio_media_type = get_audio_media_type(emo_audio_path.name)
        files["emo_audio"] = (emo_audio_path.name, emo_audio_content, emo_audio_media_type)
    
    # 表单数据
    data = {
        "text": text,
        "emo_control_method": str(emo_control_method),
        "emo_weight": str(emo_weight),
        "max_text_tokens_per_segment": str(max_text_tokens_per_segment),
        "temperature": str(temperature),
        "top_p": str(top_p),
        "top_k": str(top_k),
    }
    
    # 添加可选参数（只有当值不为 None 且不为空字符串时才添加）
    if emo_text is not None and emo_text.strip():
        data["emo_text"] = emo_text
    
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.post(
                TTS_SYNTHESIZE_ASYNC_URL,
                files=files,
                data=data,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        error_detail = e.response.text if e.response else str(e)
        raise TTSError(
            f"TTS API 请求失败 (状态码 {e.response.status_code}): {error_detail}"
        )
    except httpx.RequestError as e:
        raise TTSError(f"TTS API 请求错误: {str(e)}")
    except Exception as e:
        raise TTSError(f"提交合成任务失败: {str(e)}")


async def query_task_status(task_id: str) -> Dict[str, Any]:
    """
    查询任务状态和结果
    
    Args:
        task_id: 任务ID
        
    Returns:
        任务状态和结果字典
        
    Raises:
        TTSError: 如果查询失败
    """
    if not task_id or not task_id.strip():
        raise TTSError("任务ID不能为空")
    
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(
                f"{TTS_TASK_QUERY_URL}/{task_id}",
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        error_detail = e.response.text if e.response else str(e)
        raise TTSError(
            f"查询任务状态失败 (状态码 {e.response.status_code}): {error_detail}"
        )
    except httpx.RequestError as e:
        raise TTSError(f"查询任务状态请求错误: {str(e)}")
    except Exception as e:
        raise TTSError(f"查询任务状态失败: {str(e)}")


async def download_audio_file(filename: str) -> bytes:
    """
    从 TTS 服务器下载音频文件
    
    Args:
        filename: 音频文件名
        
    Returns:
        音频文件的二进制内容
        
    Raises:
        TTSError: 如果下载失败
    """
    if not filename or not filename.strip():
        raise TTSError("文件名不能为空")
    
    try:
        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
            response = await client.get(
                f"{TTS_DOWNLOAD_URL}/{filename}",
            )
            response.raise_for_status()
            return response.content
    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code if e.response else 500
        error_message = str(e)
        
        # 尝试解析JSON格式的错误响应
        if e.response:
            try:
                error_json = e.response.json()
                if isinstance(error_json, dict):
                    # 提取错误消息
                    if "message" in error_json:
                        error_message = error_json["message"]
                    elif "error" in error_json:
                        error_message = error_json["error"]
                    elif "detail" in error_json:
                        error_message = error_json["detail"]
            except (json.JSONDecodeError, ValueError):
                # 如果不是JSON格式，使用原始文本
                error_message = e.response.text if e.response.text else str(e)
        
        # 传递状态码，让调用者知道是404还是其他错误
        raise TTSError(
            error_message,
            status_code=status_code
        )
    except httpx.RequestError as e:
        raise TTSError(f"下载音频文件请求错误: {str(e)}", status_code=500)
    except Exception as e:
        raise TTSError(f"下载音频文件失败: {str(e)}", status_code=500)

