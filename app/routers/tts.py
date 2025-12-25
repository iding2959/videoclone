"""
TTS 音频克隆路由
"""
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, UploadFile, HTTPException, Form
from fastapi.responses import Response

from app.services.text_processing_service import synthesize_audio_async, query_task_status, download_audio_file, TTSError

router = APIRouter()


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
    return media_types.get(extension, "application/octet-stream")


@router.post("/api/tts/synthesize-async")
async def synthesize_audio_async_endpoint(
    text: str = Form(...),
    prompt_audio: UploadFile = File(...),
    emo_control_method: int = Form(0),
    emo_weight: float = Form(0.65),
    emo_text: str = Form(""),
    max_text_tokens_per_segment: int = Form(120),
    temperature: float = Form(0.8),
    top_p: float = Form(0.8),
    top_k: int = Form(30),
    emo_audio: Optional[UploadFile] = File(None),
):
    """
    异步语音合成接口 - 立即返回任务ID
    
    本接口提交合成任务后立即返回，不需要等待合成完成。
    使用返回的 task_id 可以查询任务进度和结果。
    
    Args:
        text: 要合成的文本（必填）
        prompt_audio: 音色参考音频文件（必填）
        emo_control_method: 情感控制方式: 0-与音色相同, 1-情感参考音频, 2-情感向量, 3-情感文本
        emo_weight: 情感权重
        emo_text: 情感描述文本(当emo_control_method=3时使用)
        max_text_tokens_per_segment: 分句最大Token数
        temperature: 采样温度
        top_p: top_p采样
        top_k: top_k采样
        emo_audio: 情感参考音频文件（可选）
        
    Returns:
        包含 task_id 的响应
    """
    # 验证文件类型
    if not prompt_audio.content_type or not prompt_audio.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="音色参考音频必须是音频文件")
    
    if emo_audio and (not emo_audio.content_type or not emo_audio.content_type.startswith("audio/")):
        raise HTTPException(status_code=400, detail="情感参考音频必须是音频文件")
    
    # 创建临时文件
    prompt_audio_id = str(uuid.uuid4())
    prompt_audio_extension = Path(prompt_audio.filename).suffix if prompt_audio.filename else ".mp3"
    prompt_audio_path = Path(tempfile.gettempdir()) / f"{prompt_audio_id}{prompt_audio_extension}"
    
    emo_audio_path = None
    if emo_audio:
        emo_audio_id = str(uuid.uuid4())
        emo_audio_extension = Path(emo_audio.filename).suffix if emo_audio.filename else ".mp3"
        emo_audio_path = Path(tempfile.gettempdir()) / f"{emo_audio_id}{emo_audio_extension}"
    
    try:
        # 保存音色参考音频文件到临时目录
        with open(prompt_audio_path, "wb") as f:
            content = await prompt_audio.read()
            f.write(content)
        
        # 如果有情感参考音频，保存到临时目录
        if emo_audio and emo_audio_path:
            with open(emo_audio_path, "wb") as f:
                content = await emo_audio.read()
                f.write(content)
        
        # 调用 TTS 服务
        result = await synthesize_audio_async(
            text=text,
            prompt_audio_path=prompt_audio_path,
            emo_control_method=emo_control_method,
            emo_weight=emo_weight,
            emo_text=emo_text,
            max_text_tokens_per_segment=max_text_tokens_per_segment,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            emo_audio_path=emo_audio_path,
        )
        
        return result
    
    except TTSError as e:
        raise HTTPException(status_code=500, detail=f"提交合成任务失败: {str(e)}")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
    
    finally:
        # 清理临时文件
        if prompt_audio_path.exists():
            prompt_audio_path.unlink()
        if emo_audio_path and emo_audio_path.exists():
            emo_audio_path.unlink()


@router.get("/api/tts/task/{task_id}")
async def query_task_status_endpoint(task_id: str):
    """
    查询任务状态和结果
    
    使用此接口查询异步语音合成任务的状态和结果。
    任务完成后，从返回的 result 中获取音频地址。
    
    Args:
        task_id: 任务ID（从 /api/tts/synthesize-async 接口返回）
        
    Returns:
        任务状态和结果
    """
    try:
        result = await query_task_status(task_id=task_id)
        return result
    
    except TTSError as e:
        raise HTTPException(status_code=500, detail=f"查询任务状态失败: {str(e)}")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.get("/api/tts/download/{filename}")
async def download_tts_audio_file_endpoint(filename: str):
    """
    下载生成的音频文件
    
    从 TTS 服务器下载音频文件并返回给客户端。
    
    Args:
        filename: 音频文件名
        
    Returns:
        音频文件
    """
    try:
        # 从 TTS 服务器下载音频文件
        audio_content = await download_audio_file(filename=filename)
        
        # 根据文件扩展名确定媒体类型
        media_type = get_audio_media_type(filename)
        
        # 返回音频文件，保留原始格式
        return Response(
            content=audio_content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    
    except TTSError as e:
        # 根据错误状态码返回相应的HTTP状态码
        status_code = e.status_code if e.status_code else 500
        raise HTTPException(status_code=status_code, detail=e.message)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

