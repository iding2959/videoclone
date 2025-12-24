"""
翻译路由
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.translation_service import translate_text, TranslationError

router = APIRouter()


class TranslationRequest(BaseModel):
    """翻译请求模型"""
    text: str = Field(..., description="要翻译的文本")
    model: Optional[str] = Field(None, description="使用的模型，不提供时使用默认模型")
    system_prompt: Optional[str] = Field(None, description="系统提示词，不提供时使用默认提示词")


@router.post("/translate")
async def translate_text_endpoint(request: TranslationRequest):
    """
    翻译文本
    
    如果未提供 model 或 system_prompt，将使用配置中的默认值。
    
    Args:
        request: 翻译请求，包含要翻译的文本（必需）、模型和系统提示词（可选）
        
    Returns:
        翻译结果（完整的 chat completion 响应）
    """
    try:
        result = await translate_text(
            text=request.text,
            model=request.model,
            system_prompt=request.system_prompt,
        )
        return result
    
    except TranslationError as e:
        raise HTTPException(status_code=500, detail=f"翻译失败: {str(e)}")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

