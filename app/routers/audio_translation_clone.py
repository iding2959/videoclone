"""
音频翻译克隆路由
整合音频转录、翻译、切分和音色克隆的完整流程
"""
import json
import tempfile
import uuid
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, File, UploadFile, HTTPException, Form

from app.services.audio_translation_clone_service import (
    process_audio_translation_clone,
    AudioTranslationCloneError,
)
from app.services.tts_service import query_task_status, TTSError

router = APIRouter()


@router.post("/api/audio/translation-clone")
async def audio_translation_clone_endpoint(
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
):
    """
    音频翻译克隆完整流程
    
    流程：
    1. 音频转录 - 将音频转录为文本，得到 segments 和 duration
    2. 翻译文本 - 对每个 segment 的文本进行翻译
    3. 音频切分 - 根据 segments 切分音频，得到对应的音频段（包括最后多余的一段）
    4. 音色克隆 - 对每个切分后的音频段，使用该音频段本身作为音色参考，使用对应的翻译文本进行音色克隆
    
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
        
    Returns:
        包含任务ID列表的响应，每个任务对应一个音频段的克隆
    """
    # 验证文件类型
    if not audio_file.content_type or not audio_file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="音频文件必须是音频格式")
    
    if emo_audio and (not emo_audio.content_type or not emo_audio.content_type.startswith("audio/")):
        raise HTTPException(status_code=400, detail="情感参考音频必须是音频文件")
    
    # 创建临时文件
    audio_file_id = str(uuid.uuid4())
    audio_file_extension = Path(audio_file.filename).suffix if audio_file.filename else ".mp3"
    audio_file_path = Path(tempfile.gettempdir()) / f"{audio_file_id}{audio_file_extension}"
    
    emo_audio_path = None
    if emo_audio:
        emo_audio_id = str(uuid.uuid4())
        emo_audio_extension = Path(emo_audio.filename).suffix if emo_audio.filename else ".mp3"
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
        result = await process_audio_translation_clone(
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
        )
        
        return result
    
    except AudioTranslationCloneError as e:
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


@router.post("/api/audio/translation-clone/query-tasks")
async def query_clone_tasks_status(
    task_ids: str = Form(...),
):
    """
    批量查询音色克隆任务状态
    
    查询多个任务的状态和结果。任务完成后，从返回的 result 中获取音频地址。
    
    Args:
        task_ids: 任务ID列表的JSON字符串，例如 ["task_id_1", "task_id_2", "task_id_3"]
        
    Returns:
        包含所有任务状态和结果的字典
    """
    try:
        # 解析任务ID列表
        try:
            task_id_list = json.loads(task_ids)
            if not isinstance(task_id_list, list):
                raise ValueError("task_ids 必须是数组")
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"任务ID列表格式错误: {str(e)}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        if not task_id_list:
            raise HTTPException(status_code=400, detail="任务ID列表不能为空")
        
        # 批量查询任务状态
        results = []
        for task_id in task_id_list:
            if not task_id or not str(task_id).strip():
                results.append({
                    "task_id": task_id,
                    "status": "error",
                    "error": "任务ID为空",
                })
                continue
            
            try:
                task_result = await query_task_status(task_id=str(task_id))
                results.append({
                    "task_id": task_id,
                    "status": "success",
                    "result": task_result,
                })
            except TTSError as e:
                results.append({
                    "task_id": task_id,
                    "status": "error",
                    "error": str(e),
                })
            except Exception as e:
                results.append({
                    "task_id": task_id,
                    "status": "error",
                    "error": f"查询失败: {str(e)}",
                })
        
        return {
            "message": "批量查询完成",
            "total_tasks": len(task_id_list),
            "tasks": results,
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.get("/api/audio/translation-clone/task/{task_id}")
async def query_single_clone_task_status(task_id: str):
    """
    查询单个音色克隆任务状态
    
    查询单个任务的状态和结果。任务完成后，从返回的 result 中获取音频地址。
    
    Args:
        task_id: 任务ID（从 /api/audio/translation-clone 接口返回的 tasks 中的 task_id）
        
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

