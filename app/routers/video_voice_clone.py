"""
综合视频音色克隆、裁剪与字幕叠加路由。
"""
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException, Form
from fastapi.responses import FileResponse

from app.config import UPLOAD_DIR, OUTPUT_DIR
from app.services.video_voice_clone_service import (
    process_video_voice_clone,
    process_video_voice_clone_audio_only,
    VideoVoiceCloneError,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/video/voice-clone-overlay")
async def video_voice_clone_overlay(
    file: UploadFile = File(..., description="视频文件"),
    title_text: str = Form(..., description="顶部标题文本"),
):
    """
    上传视频，完成音色克隆替换、固定裁剪（上200/下250）并叠加标题与字幕。
    """
    if not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="请上传视频文件")

    file_id = uuid.uuid4().hex
    extension = Path(file.filename).suffix if file.filename else ".mp4"
    raw_video_path = UPLOAD_DIR / f"{file_id}{extension}"

    try:
        logger.info("收到 /video/voice-clone-overlay 请求，文件: %s, 标题: %s", file.filename, title_text)
        content = await file.read()
        with open(raw_video_path, "wb") as f:
            f.write(content)

        result = await process_video_voice_clone(
            video_path=raw_video_path,
            title_text=title_text,
        )

        final_path: Path = result["video_path"]
        if not final_path.exists():
            raise HTTPException(status_code=500, detail="处理失败，未生成输出文件")

        logger.info("处理完成，返回文件: %s", final_path)
        return FileResponse(
            path=str(final_path),
            media_type=file.content_type or "video/mp4",
            filename=f"{Path(file.filename).stem if file.filename else 'video'}_voice_clone_overlay{extension}",
        )
    except VideoVoiceCloneError as e:
        logger.error("处理失败 VideoVoiceCloneError: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("处理失败: %s", e)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
    finally:
        if raw_video_path.exists():
            try:
                raw_video_path.unlink()
            except Exception:
                pass


@router.post("/video/voice-clone")
async def video_voice_clone(
    file: UploadFile = File(..., description="视频文件"),
):
    """
    上传视频，仅进行语言翻译和音色克隆，替换原音轨，不裁剪、不叠字幕。
    """
    if not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="请上传视频文件")

    file_id = uuid.uuid4().hex
    extension = Path(file.filename).suffix if file.filename else ".mp4"
    raw_video_path = UPLOAD_DIR / f"{file_id}{extension}"

    try:
        logger.info("收到 /video/voice-clone 请求，文件: %s", file.filename)
        content = await file.read()
        with open(raw_video_path, "wb") as f:
            f.write(content)

        result = await process_video_voice_clone_audio_only(video_path=raw_video_path)

        final_path: Path = result["video_path"]
        if not final_path.exists():
            raise HTTPException(status_code=500, detail="处理失败，未生成输出文件")

        logger.info("处理完成，返回文件: %s", final_path)
        return FileResponse(
            path=str(final_path),
            media_type=file.content_type or "video/mp4",
            filename=f"{Path(file.filename).stem if file.filename else 'video'}_voice_clone{extension}",
        )
    except VideoVoiceCloneError as e:
        logger.error("处理失败 VideoVoiceCloneError: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("处理失败: %s", e)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
    finally:
        if raw_video_path.exists():
            try:
                raw_video_path.unlink()
            except Exception:
                pass

