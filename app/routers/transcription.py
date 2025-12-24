"""
音频转录路由
"""
from typing import Optional

from fastapi import APIRouter, File, UploadFile, HTTPException, Form
from pydantic import BaseModel

from app.services.transcription_service import transcribe_audio, TranscriptionError

router = APIRouter()


class TranscriptionResponse(BaseModel):
    """转录响应模型"""
    text: Optional[str] = None
    language: Optional[str] = None
    duration: Optional[float] = None
    segments: Optional[list] = None


@router.post("/transcribe")
async def transcribe_audio_file(
    file: UploadFile = File(...),
    model: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    response_format: Optional[str] = Form(None),
):
    """
    上传音频文件并进行转录
    
    Args:
        file: 上传的音频文件
        model: 使用的模型（可选，默认使用配置中的模型）
        language: 语言代码（可选，默认使用配置中的语言）
        response_format: 响应格式（可选，默认使用配置中的格式）
        
    Returns:
        转录结果
    """
    # 验证文件类型
    if not file.content_type or not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="请上传音频文件")
    
    import tempfile
    import uuid
    from pathlib import Path
    
    # 创建临时文件
    file_id = str(uuid.uuid4())
    file_extension = Path(file.filename).suffix if file.filename else ".mp3"
    temp_file_path = Path(tempfile.gettempdir()) / f"{file_id}{file_extension}"
    
    try:
        # 保存上传的音频文件到临时目录
        with open(temp_file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # 调用转录服务
        result = await transcribe_audio(
            audio_file_path=temp_file_path,
            model=model,
            language=language,
            response_format=response_format,
        )
        
        return result
    
    except TranscriptionError as e:
        raise HTTPException(status_code=500, detail=f"转录失败: {str(e)}")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
    
    finally:
        # 清理临时文件
        if temp_file_path.exists():
            temp_file_path.unlink()

