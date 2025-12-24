"""
翻译服务
"""
from typing import Optional, Dict, Any, List

import httpx

from app.config import (
    TRANSLATION_API_URL,
    TRANSLATION_API_TOKEN,
    TRANSLATION_DEFAULT_MODEL,
    TRANSLATION_DEFAULT_SYSTEM_PROMPT,
)


class TranslationError(Exception):
    """翻译错误"""
    pass


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
    
    # 使用配置中的默认值
    model = model or TRANSLATION_DEFAULT_MODEL
    system_prompt = system_prompt or TRANSLATION_DEFAULT_SYSTEM_PROMPT
    
    # 检查 token 是否配置
    if not TRANSLATION_API_TOKEN or TRANSLATION_API_TOKEN.strip() == "":
        raise TranslationError("翻译 API Token 未配置，请在 config.py 中设置 TRANSLATION_API_TOKEN")
    
    # 准备请求头
    headers = {
        "Authorization": f"Bearer {TRANSLATION_API_TOKEN.strip()}",
        "Content-Type": "application/json",
        "Accept": "*/*",
    }
    
    # 准备请求体
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
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.post(
                TRANSLATION_API_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        error_detail = e.response.text if e.response else str(e)
        # 对于 401 错误，提供更详细的提示
        if e.response.status_code == 401:
            raise TranslationError(
                f"认证失败 (401): 请检查 config.py 中的 TRANSLATION_API_TOKEN 是否正确。"
                f"原始错误: {error_detail}"
            )
        raise TranslationError(
            f"翻译 API 请求失败 (状态码 {e.response.status_code}): {error_detail}"
        )
    except httpx.RequestError as e:
        raise TranslationError(f"翻译 API 请求错误: {str(e)}")
    except Exception as e:
        raise TranslationError(f"翻译失败: {str(e)}")

