"""
音频转录路由
"""
import json
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, File, UploadFile, HTTPException, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.services.transcription_service import transcribe_audio, TranscriptionError
from app.services.audio_segmentation_service import segment_audio, AudioSegmentationError
from app.config import OUTPUT_DIR

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


@router.post("/segment")
async def segment_audio_file(
    file: UploadFile = File(...),
    transcription_result: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    response_format: Optional[str] = Form(None),
    download: Optional[bool] = Form(False),
):
    """
    根据转录结果切分音频文件
    
    如果未提供 transcription_result，将自动调用转录服务进行转录。
    
    Args:
        file: 上传的音频文件
        transcription_result: 转录结果 JSON 字符串（可选），如果提供则使用该结果，否则自动调用转录服务
        model: 转录使用的模型（可选，仅在自动转录时使用）
        language: 转录使用的语言代码（可选，仅在自动转录时使用）
        response_format: 转录响应格式（可选，仅在自动转录时使用）
        download: 是否直接返回 ZIP 压缩包（默认 False，返回 JSON 信息）
        
    Returns:
        如果 download=True，返回 ZIP 压缩包文件
        如果 download=False，返回切分后的音频文件信息（JSON）
    """
    # 验证文件类型
    if not file.content_type or not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="请上传音频文件")
    
    # 创建临时文件
    file_id = str(uuid.uuid4())
    file_extension = Path(file.filename).suffix if file.filename else ".mp3"
    temp_file_path = Path(tempfile.gettempdir()) / f"{file_id}{file_extension}"
    
    transcription_data = None
    
    try:
        # 保存上传的音频文件到临时目录
        with open(temp_file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # 如果没有提供转录结果，自动调用转录服务
        if transcription_result is None:
            try:
                transcription_data = await transcribe_audio(
                    audio_file_path=temp_file_path,
                    model=model,
                    language=language,
                    response_format=response_format,
                )
            except TranscriptionError as e:
                raise HTTPException(status_code=500, detail=f"自动转录失败: {str(e)}")
        else:
            # 解析提供的转录结果
            try:
                transcription_data = json.loads(transcription_result)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="转录结果 JSON 格式错误")
        
        # 从转录结果中提取 segments 和 duration
        segments = transcription_data.get("segments", [])
        duration = transcription_data.get("duration", 0)
        
        if not segments:
            raise HTTPException(status_code=400, detail="转录结果中 segments 为空")
        
        if duration <= 0:
            raise HTTPException(status_code=400, detail="转录结果中 duration 无效")
        
        # 调用音频切分服务
        output_paths = segment_audio(
            audio_file_path=temp_file_path,
            segments=segments,
            duration=duration,
        )
        
        # 如果请求下载，返回 ZIP 压缩包
        if download:
            # 创建临时 ZIP 文件
            zip_id = str(uuid.uuid4())
            zip_path = Path(tempfile.gettempdir()) / f"{zip_id}.zip"
            
            try:
                # 创建 ZIP 文件
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for path in output_paths:
                        if path.exists():
                            zipf.write(path, path.name)
                
                # 生成下载文件名
                audio_stem = temp_file_path.stem
                zip_filename = f"{audio_stem}_segments.zip"
                
                # 返回 ZIP 文件
                return FileResponse(
                    path=str(zip_path),
                    media_type="application/zip",
                    filename=zip_filename
                )
            except Exception as e:
                # 清理 ZIP 文件
                if zip_path.exists():
                    zip_path.unlink()
                raise HTTPException(status_code=500, detail=f"创建 ZIP 文件失败: {str(e)}")
        
        # 返回切分后的文件信息和转录结果
        return {
            "message": "音频切分成功",
            "transcription": {
                "text": transcription_data.get("text"),
                "language": transcription_data.get("language"),
                "duration": transcription_data.get("duration"),
                "model": transcription_data.get("model"),
            },
            "segment_count": len(output_paths),
            "segments": [
                {
                    "index": idx,
                    "filename": path.name,
                    "path": str(path),
                }
                for idx, path in enumerate(output_paths, 1)
            ]
        }
    
    except HTTPException:
        raise
    except AudioSegmentationError as e:
        raise HTTPException(status_code=500, detail=f"音频切分失败: {str(e)}")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
    
    finally:
        # 清理临时文件
        if temp_file_path.exists():
            temp_file_path.unlink()


@router.get("/segment/download/{filename}")
async def download_segment_file(filename: str):
    """
    下载单个切分后的音频文件
    
    Args:
        filename: 切分后的音频文件名
        
    Returns:
        音频文件
    """
    file_path = OUTPUT_DIR / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {filename}")
    
    # 验证文件在输出目录中（防止路径遍历攻击）
    try:
        file_path.resolve().relative_to(OUTPUT_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="无权访问该文件")
    
    return FileResponse(
        path=str(file_path),
        media_type="audio/mpeg",
        filename=filename
    )


@router.post("/segment/download")
async def download_segments_zip(
    file_paths: str = Form(...),
):
    """
    下载多个切分后的音频文件（打包成 ZIP）
    
    Args:
        file_paths: 文件路径列表的 JSON 字符串，例如 ["outputs/file1.mp3", "outputs/file2.mp3"]
        
    Returns:
        ZIP 压缩包文件
    """
    try:
        paths_list = json.loads(file_paths)
        if not isinstance(paths_list, list):
            raise ValueError("file_paths 必须是数组")
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"文件路径格式错误: {str(e)}")
    
    if not paths_list:
        raise HTTPException(status_code=400, detail="文件路径列表为空")
    
    # 创建临时 ZIP 文件
    zip_id = str(uuid.uuid4())
    zip_path = Path(tempfile.gettempdir()) / f"{zip_id}.zip"
    
    try:
        # 创建 ZIP 文件
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path_str in paths_list:
                file_path = Path(file_path_str)
                
                # 验证文件在输出目录中（防止路径遍历攻击）
                try:
                    file_path.resolve().relative_to(OUTPUT_DIR.resolve())
                except ValueError:
                    continue  # 跳过不在输出目录中的文件
                
                if file_path.exists() and file_path.is_file():
                    zipf.write(file_path, file_path.name)
        
        # 生成下载文件名
        zip_filename = "audio_segments.zip"
        
        # 返回 ZIP 文件
        return FileResponse(
            path=str(zip_path),
            media_type="application/zip",
            filename=zip_filename
        )
    
    except Exception as e:
        # 清理 ZIP 文件
        if zip_path.exists():
            zip_path.unlink()
        raise HTTPException(status_code=500, detail=f"创建 ZIP 文件失败: {str(e)}")

