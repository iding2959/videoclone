"""
文本处理服务
整合音频转录、文本翻译、语音合成等功能
"""
import json
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any

import httpx

from app.config import (
    TRANSCRIPTION_API_URL,
    TRANSCRIPTION_API_TOKEN,
    TRANSCRIPTION_DEFAULT_MODEL,
    TRANSCRIPTION_DEFAULT_LANGUAGE,
    TRANSCRIPTION_DEFAULT_RESPONSE_FORMAT,
    TRANSLATION_API_URL,
    TRANSLATION_API_TOKEN,
    TRANSLATION_DEFAULT_MODEL,
    TRANSLATION_DEFAULT_SYSTEM_PROMPT,
    TTS_SYNTHESIZE_ASYNC_URL,
    TTS_TASK_QUERY_URL,
    TTS_DOWNLOAD_URL,
)
from app.utils.logger import logger


class TextProcessingError(Exception):
    """文本处理错误基类"""
    pass


class TranscriptionError(TextProcessingError):
    """音频转录错误"""
    pass


class TranslationError(TextProcessingError):
    """翻译错误"""
    pass


class TTSError(TextProcessingError):
    """TTS 服务错误"""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


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
    
    model = model or TRANSCRIPTION_DEFAULT_MODEL
    language = language or TRANSCRIPTION_DEFAULT_LANGUAGE
    response_format = response_format or TRANSCRIPTION_DEFAULT_RESPONSE_FORMAT
    
    if not TRANSCRIPTION_API_TOKEN or TRANSCRIPTION_API_TOKEN.strip() == "":
        raise TranscriptionError("转录 API Token 未配置，请在 config.py 中设置 TRANSCRIPTION_API_TOKEN")
    
    headers = {
        "Authorization": f"Bearer {TRANSCRIPTION_API_TOKEN.strip()}",
        "Accept": "*/*",
    }
    
    try:
        logger.info(f"开始转录音频: {audio_file_path.name}, 模型: {model}, 语言: {language}")
        with open(audio_file_path, "rb") as f:
            file_content = f.read()
        
        files = {
            "file": (audio_file_path.name, file_content, "audio/mpeg"),
        }
        
        data = {
            "model": model,
            "language": language,
            "response_format": response_format,
        }
        
        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
            response = await client.post(
                TRANSCRIPTION_API_URL,
                headers=headers,
                files=files,
                data=data,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"音频转录完成: {audio_file_path.name}")
            return result
    except httpx.HTTPStatusError as e:
        error_detail = e.response.text if e.response else str(e)
        if e.response.status_code == 401:
            raise TranscriptionError(
                f"认证失败 (401): 请检查 config.py 中的 TRANSCRIPTION_API_TOKEN 是否正确。"
                f"原始错误: {error_detail}"
            )
        logger.error(f"转录 API 请求失败 (状态码 {e.response.status_code}): {error_detail}")
        raise TranscriptionError(
            f"转录 API 请求失败 (状态码 {e.response.status_code}): {error_detail}"
        )
    except httpx.RequestError as e:
        logger.error(f"转录 API 请求错误: {str(e)}")
        raise TranscriptionError(f"转录 API 请求错误: {str(e)}")
    except Exception as e:
        logger.error(f"转录异常: {str(e)}")
        raise TranscriptionError(f"转录失败: {str(e)}")


async def translate_text(
    text: str,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    调用翻译 API 进行翻译
    
    Args:
        text: 要翻译的文本
        model: 使用的模型，默认使用配置中的模型
        system_prompt: 系统提示词，默认使用配置中的提示词
        
    Returns:
        翻译结果字典（完整的 chat completion 响应）
        
    Raises:
        TranslationError: 如果翻译失败
    """
    if not text or not text.strip():
        raise TranslationError("翻译文本不能为空")
    
    model = model or TRANSLATION_DEFAULT_MODEL
    system_prompt = system_prompt or TRANSLATION_DEFAULT_SYSTEM_PROMPT
    
    if not TRANSLATION_API_TOKEN or TRANSLATION_API_TOKEN.strip() == "":
        raise TranslationError("翻译 API Token 未配置，请在 config.py 中设置 TRANSLATION_API_TOKEN")
    
    headers = {
        "Authorization": f"Bearer {TRANSLATION_API_TOKEN.strip()}",
        "Content-Type": "application/json",
        "Accept": "*/*",
    }
    
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": text
            }
        ]
    }
    
    try:
        logger.debug(f"开始翻译文本: {text[:50]}...")
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.post(
                TRANSLATION_API_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            logger.debug(f"文本翻译完成")
            return result
    except httpx.HTTPStatusError as e:
        error_detail = e.response.text if e.response else str(e)
        if e.response.status_code == 401:
            raise TranslationError(
                f"认证失败 (401): 请检查 config.py 中的 TRANSLATION_API_TOKEN 是否正确。"
                f"原始错误: {error_detail}"
            )
        logger.error(f"翻译 API 请求失败 (状态码 {e.response.status_code}): {error_detail}")
        raise TranslationError(
            f"翻译 API 请求失败 (状态码 {e.response.status_code}): {error_detail}"
        )
    except httpx.RequestError as e:
        logger.error(f"翻译 API 请求错误: {str(e)}")
        raise TranslationError(f"翻译 API 请求错误: {str(e)}")
    except Exception as e:
        logger.error(f"翻译异常: {str(e)}")
        raise TranslationError(f"翻译失败: {str(e)}")


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
    
    try:
        logger.info(f"开始提交语音合成任务: 文本长度={len(text)}, 音色参考={prompt_audio_path.name}")
        with open(prompt_audio_path, "rb") as f:
            prompt_audio_content = f.read()
        
        prompt_audio_media_type = get_audio_media_type(prompt_audio_path.name)
        
        files = {
            "prompt_audio": (prompt_audio_path.name, prompt_audio_content, prompt_audio_media_type),
        }
        
        if emo_audio_path:
            with open(emo_audio_path, "rb") as f:
                emo_audio_content = f.read()
            emo_audio_media_type = get_audio_media_type(emo_audio_path.name)
            files["emo_audio"] = (emo_audio_path.name, emo_audio_content, emo_audio_media_type)
        
        data = {
            "text": text,
            "emo_control_method": str(emo_control_method),
            "emo_weight": str(emo_weight),
            "max_text_tokens_per_segment": str(max_text_tokens_per_segment),
            "temperature": str(temperature),
            "top_p": str(top_p),
            "top_k": str(top_k),
        }
        
        if emo_text is not None and emo_text.strip():
            data["emo_text"] = emo_text
        
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.post(
                TTS_SYNTHESIZE_ASYNC_URL,
                files=files,
                data=data,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"语音合成任务提交成功")
            return result
    except httpx.HTTPStatusError as e:
        error_detail = e.response.text if e.response else str(e)
        logger.error(f"TTS API 请求失败 (状态码 {e.response.status_code}): {error_detail}")
        raise TTSError(
            f"TTS API 请求失败 (状态码 {e.response.status_code}): {error_detail}"
        )
    except httpx.RequestError as e:
        logger.error(f"TTS API 请求错误: {str(e)}")
        raise TTSError(f"TTS API 请求错误: {str(e)}")
    except Exception as e:
        logger.error(f"提交合成任务异常: {str(e)}")
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
        logger.debug(f"查询任务状态: {task_id}")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(
                f"{TTS_TASK_QUERY_URL}/{task_id}",
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        error_detail = e.response.text if e.response else str(e)
        logger.error(f"查询任务状态失败 (状态码 {e.response.status_code}): {error_detail}")
        raise TTSError(
            f"查询任务状态失败 (状态码 {e.response.status_code}): {error_detail}"
        )
    except httpx.RequestError as e:
        logger.error(f"查询任务状态请求错误: {str(e)}")
        raise TTSError(f"查询任务状态请求错误: {str(e)}")
    except Exception as e:
        logger.error(f"查询任务状态异常: {str(e)}")
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
        logger.info(f"开始下载音频文件: {filename}")
        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
            response = await client.get(
                f"{TTS_DOWNLOAD_URL}/{filename}",
            )
            response.raise_for_status()
            logger.info(f"音频文件下载完成: {filename}")
            return response.content
    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code if e.response else 500
        error_message = str(e)
        
        if e.response:
            try:
                error_json = e.response.json()
                if isinstance(error_json, dict):
                    if "message" in error_json:
                        error_message = error_json["message"]
                    elif "error" in error_json:
                        error_message = error_json["error"]
                    elif "detail" in error_json:
                        error_message = error_json["detail"]
            except (json.JSONDecodeError, ValueError):
                error_message = e.response.text if e.response.text else str(e)
        
        logger.error(f"下载音频文件失败 (状态码 {status_code}): {error_message}")
        raise TTSError(error_message, status_code=status_code)
    except httpx.RequestError as e:
        logger.error(f"下载音频文件请求错误: {str(e)}")
        raise TTSError(f"下载音频文件请求错误: {str(e)}", status_code=500)
    except Exception as e:
        logger.error(f"下载音频文件异常: {str(e)}")
        raise TTSError(f"下载音频文件失败: {str(e)}", status_code=500)

