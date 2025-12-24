"""
音频合并路由
实现音频翻译克隆和合并的完整流程
"""
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, UploadFile, HTTPException, Form
from fastapi.responses import FileResponse

from app.services.audio_merge_service import merge_cloned_audios, AudioMergeError

router = APIRouter()


@router.post("/api/audio/merge-cloned")
async def merge_cloned_audios_endpoint(
    audio_file: UploadFile = File(...),
    transcription_model: Optional[str] = Form(None),
    transcription_language: Optional[str] = Form(None),
    transcription_response_format: Optional[str] = Form(None),
    translation_model: Optional[str] = Form(None),
    translation_system_prompt: Optional[str] = Form(None),
    emo_control_method: int = Form(0),
    emo_weight: float = Form(0.65),
    emo_text: str = Form(""),
    max_text_tokens_per_segment: int = Form(120),
    temperature: float = Form(0.8),
    top_p: float = Form(0.8),
    top_k: int = Form(30),
    emo_audio: Optional[UploadFile] = File(None),
    query_interval: float = Form(2.0),
    max_wait_time: float = Form(300.0),
    base_url: str = Form("http://localhost:8000"),
):
    """
    音频翻译克隆并合并完整流程
    
    流程：
    1. 调用音频翻译克隆接口，得到任务ID和最后一段音频路径
    2. 查询所有克隆任务状态，等待完成
    3. 下载所有克隆后的音频
    4. 下载最后一段音频（没有克隆的）
    5. 合并所有音频，返回合并后的音频文件
    
    Args:
        audio_file: 要处理的音频文件（必填）
        transcription_model: 转录使用的模型（可选，默认使用配置中的模型）
        transcription_language: 转录使用的语言代码（可选，默认使用配置中的语言）
        transcription_response_format: 转录响应格式（可选，默认使用配置中的格式）
        translation_model: 翻译使用的模型（可选，默认使用配置中的模型）
        translation_system_prompt: 翻译使用的系统提示词（可选，默认使用配置中的提示词）
        emo_control_method: 情感控制方式: 0-与音色相同, 1-情感参考音频, 2-情感向量, 3-情感文本
        emo_weight: 情感权重
        emo_text: 情感描述文本(当emo_control_method=3时使用)
        max_text_tokens_per_segment: 分句最大Token数
        temperature: 采样温度
        top_p: top_p采样
        top_k: top_k采样
        emo_audio: 情感参考音频文件（可选）
        query_interval: 查询任务状态的间隔时间（秒，默认2.0）
        max_wait_time: 最大等待时间（秒，默认300.0）
        base_url: API 基础URL（默认 http://localhost:8000）
        
    Returns:
        合并后的音频文件（WAV格式）
    """
    # 验证文件类型
    if not audio_file.content_type or not audio_file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="音频文件必须是音频格式")
    
    if emo_audio and (not emo_audio.content_type or not emo_audio.content_type.startswith("audio/")):
        raise HTTPException(status_code=400, detail="情感参考音频必须是音频文件")
    
    # 创建临时文件
    audio_file_id = str(uuid.uuid4())
    audio_file_extension = Path(audio_file.filename).suffix if audio_file.filename else ".wav"
    audio_file_path = Path(tempfile.gettempdir()) / f"{audio_file_id}{audio_file_extension}"
    
    emo_audio_path = None
    if emo_audio:
        emo_audio_id = str(uuid.uuid4())
        emo_audio_extension = Path(emo_audio.filename).suffix if emo_audio.filename else ".wav"
        emo_audio_path = Path(tempfile.gettempdir()) / f"{emo_audio_id}{emo_audio_extension}"
    
    try:
        # 保存上传的文件到临时目录
        with open(audio_file_path, "wb") as f:
            content = await audio_file.read()
            f.write(content)
        
        if emo_audio and emo_audio_path:
            with open(emo_audio_path, "wb") as f:
                content = await emo_audio.read()
                f.write(content)
        
        # 调用服务层处理业务逻辑
        merged_audio_path = await merge_cloned_audios(
            audio_file_path=audio_file_path,
            transcription_model=transcription_model,
            transcription_language=transcription_language,
            transcription_response_format=transcription_response_format,
            translation_model=translation_model,
            translation_system_prompt=translation_system_prompt,
            emo_control_method=emo_control_method,
            emo_weight=emo_weight,
            emo_text=emo_text,
            max_text_tokens_per_segment=max_text_tokens_per_segment,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            emo_audio_path=emo_audio_path,
            query_interval=query_interval,
            max_wait_time=max_wait_time,
            base_url=base_url,
        )
        
        # 返回合并后的音频文件
        return FileResponse(
            path=str(merged_audio_path),
            media_type="audio/wav",
            filename=f"merged_audio.wav"
        )
    
    except AudioMergeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
    
    finally:
        # 清理临时文件
        if audio_file_path.exists():
            audio_file_path.unlink()
        if emo_audio_path and emo_audio_path.exists():
            emo_audio_path.unlink()

