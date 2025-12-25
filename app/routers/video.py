"""
视频处理路由模块
包含视频裁剪、叠加字幕、音色克隆等视频处理功能
"""
import uuid
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, File, UploadFile, HTTPException, Form
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.config import UPLOAD_DIR, OUTPUT_DIR
from app.services.video_processing_service import (
    detect_and_crop_video,
    VideoCropError,
    overlay_title_and_subtitles,
    VideoOverlayError,
)
from app.services.workflow_service import (
    process_video_voice_clone,
    process_video_voice_clone_audio_only,
    VideoVoiceCloneError,
)
from app.utils.logger import logger

router = APIRouter()


@router.post("/video/crop")
async def crop_video(
    file: UploadFile = File(...),
    top_cut: int = 0,
    bottom_cut: int = 0,
):
    """
    上传视频并裁剪顶部/底部像素；如未指定则尝试自动检测。
    """
    if not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="请上传视频文件")

    file_id = uuid.uuid4().hex
    extension = Path(file.filename).suffix if file.filename else ".mp4"
    raw_video_path = UPLOAD_DIR / f"{file_id}{extension}"
    output_video_path = OUTPUT_DIR / f"{file_id}_cropped{extension}"

    try:
        # 保存上传视频
        content = await file.read()
        with open(raw_video_path, "wb") as f:
            f.write(content)

        # 同步裁剪逻辑放在线程池，避免阻塞事件循环
        cropped_path = await run_in_threadpool(
            detect_and_crop_video,
            raw_video_path,
            output_video_path,
            top_cut,
            bottom_cut,
        )

        if not cropped_path.exists():
            raise HTTPException(status_code=500, detail="裁剪失败，未生成输出文件")

        return FileResponse(
            path=str(cropped_path),
            media_type=file.content_type or "video/mp4",
            filename=f"{Path(file.filename).stem if file.filename else 'video'}_cropped{extension}",
        )
    except VideoCropError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
    finally:
        # 可选清理：保留输出文件供下载，上传文件删除
        if raw_video_path.exists():
            try:
                raw_video_path.unlink()
            except Exception:
                pass


def _validate_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(segments, list) or not segments:
        raise HTTPException(status_code=400, detail="segments 不能为空")
    normalized = []
    for seg in segments:
        try:
            start = float(seg.get("start"))
            end = float(seg.get("end"))
        except Exception:
            raise HTTPException(status_code=400, detail="segments 中 start/end 必须为数字")
        if end <= start:
            raise HTTPException(status_code=400, detail="segment 的 end 必须大于 start")
        text = seg.get("translated_text") or seg.get("text")
        if text is None:
            raise HTTPException(status_code=400, detail="segment 缺少 text/translated_text")
        normalized.append(
            {
                "start": start,
                "end": end,
                "text": seg.get("text"),
                "translated_text": seg.get("translated_text"),
            }
        )
    return normalized


def _maybe_load_json(value: Optional[Any]) -> Optional[Any]:
    """如果是字符串且为 JSON，尝试解析，否则原样返回。"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _resolve_segments(segments: Optional[Any], payload: Optional[Any]) -> List[Dict[str, Any]]:
    """
    支持多种传法：
    - 直接 segments 为数组
    - segments 是字符串的 JSON
    - payload 内包含 segments（可为对象或字符串 JSON）
    - segments/payload 为对象且内部有 segments 字段
    """
    segs = _maybe_load_json(segments)
    pay = _maybe_load_json(payload)

    # 如果 segs 是对象且包含 segments 字段
    if isinstance(segs, dict) and "segments" in segs:
        segs = segs.get("segments")

    # 如果 segs 为空，尝试从 payload 获取
    if not segs and isinstance(pay, dict):
        segs = pay.get("segments")

    # 如果 segs 依然是字符串，最后再尝试解析一次
    segs = _maybe_load_json(segs)

    if not segs:
        raise HTTPException(status_code=400, detail="缺少 segments 数据")
    if not isinstance(segs, list):
        raise HTTPException(status_code=400, detail="segments 应该是数组或包含 segments 的对象")
    return _validate_segments(segs)


@router.post("/video/overlay")
async def add_title_and_subtitles(
    file: UploadFile = File(..., description="视频文件"),
    title_text: str = Form(..., description="顶部标题文本"),
    title_block_height: int = Form(120, description="标题区域高度（像素，自顶向下，黑底）"),
    subtitle_block_height: int = Form(160, description="字幕区域高度（像素，自底向上，黑底）"),
    title_font_size: Optional[int] = Form(None, description="标题字体大小，可选"),
    subtitle_font_size: Optional[int] = Form(None, description="字幕字体大小，可选"),
    segments: Optional[str] = Form(
        None,
        description="字幕分段，可为 JSON 字符串或数组字符串；若为空可用 payload 提供",
    ),
    payload: Optional[str] = Form(
        None,
        description="可选 JSON 字符串，内部含 segments（兼容 transcription/segments 结构）",
    ),
    fontfile: Optional[str] = Form(None, description="可选字体文件路径"),
):
    """
    在视频上叠加标题（全程显示）和分段字幕（按时间显示）。
    - 标题区域：顶部黑底块，高度 `title_block_height`，垂直居中显示标题。
    - 字幕区域：底部黑底块，高度 `subtitle_block_height`，垂直居中显示字幕。
    - 字体大小可显式指定（title_font_size / subtitle_font_size），未指定则自适应。
    - segments: 包含 start/end/text/translated_text，用 translated_text 优先。
    """
    if not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="请上传视频文件")

    segments_norm = _resolve_segments(segments, payload)
    if title_block_height <= 0 or subtitle_block_height <= 0:
        raise HTTPException(status_code=400, detail="标题/字幕块高度必须大于 0")
    if title_font_size is not None and title_font_size <= 0:
        raise HTTPException(status_code=400, detail="标题字体大小必须大于 0")
    if subtitle_font_size is not None and subtitle_font_size <= 0:
        raise HTTPException(status_code=400, detail="字幕字体大小必须大于 0")

    file_id = uuid.uuid4().hex
    extension = Path(file.filename).suffix if file.filename else ".mp4"
    raw_video_path = UPLOAD_DIR / f"{file_id}{extension}"
    output_video_path = OUTPUT_DIR / f"{file_id}_overlay{extension}"

    try:
        content = await file.read()
        with open(raw_video_path, "wb") as f:
            f.write(content)

        out_path = await run_in_threadpool(
            overlay_title_and_subtitles,
            raw_video_path,
            output_video_path,
            title_text,
            segments_norm,
            title_block_height,
            subtitle_block_height,
            title_font_size,
            subtitle_font_size,
            fontfile,
        )

        if not out_path.exists():
            raise HTTPException(status_code=500, detail="叠加失败，未生成输出文件")

        return FileResponse(
            path=str(out_path),
            media_type=file.content_type or "video/mp4",
            filename=f"{Path(file.filename).stem if file.filename else 'video'}_overlay{extension}",
        )
    except VideoOverlayError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
    finally:
        if raw_video_path.exists():
            try:
                raw_video_path.unlink()
            except Exception:
                pass


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
        logger.debug("收到 /video/voice-clone-overlay 请求，文件: {}, 标题: {}", file.filename, title_text)
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

        logger.debug("处理完成，返回文件: {}", final_path)
        return FileResponse(
            path=str(final_path),
            media_type=file.content_type or "video/mp4",
            filename=f"{Path(file.filename).stem if file.filename else 'video'}_voice_clone_overlay{extension}",
        )
    except VideoVoiceCloneError as e:
        logger.error("处理失败 VideoVoiceCloneError: {}", e)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("处理失败: {}", e)
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
        logger.debug("收到 /video/voice-clone 请求，文件: {}", file.filename)
        content = await file.read()
        with open(raw_video_path, "wb") as f:
            f.write(content)

        result = await process_video_voice_clone_audio_only(video_path=raw_video_path)

        final_path: Path = result["video_path"]
        if not final_path.exists():
            raise HTTPException(status_code=500, detail="处理失败，未生成输出文件")

        logger.debug("处理完成，返回文件: {}", final_path)
        return FileResponse(
            path=str(final_path),
            media_type=file.content_type or "video/mp4",
            filename=f"{Path(file.filename).stem if file.filename else 'video'}_voice_clone{extension}",
        )
    except VideoVoiceCloneError as e:
        logger.error("处理失败 VideoVoiceCloneError: {}", e)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("处理失败: {}", e)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
    finally:
        if raw_video_path.exists():
            try:
                raw_video_path.unlink()
            except Exception:
                pass

