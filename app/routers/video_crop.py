"""
视频自动裁剪路由：上传视频，检测顶部标题与底部字幕并返回裁剪后视频。
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.config import UPLOAD_DIR, OUTPUT_DIR
from app.services.video_crop_service import detect_and_crop_video, VideoCropError

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

