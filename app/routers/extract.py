"""
音频提取路由
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import FileResponse

from app.config import UPLOAD_DIR, OUTPUT_DIR
from app.services.audio_service import extract_audio, AudioExtractionError

router = APIRouter()


@router.post("/extract")
async def extract_audio_from_video(file: UploadFile = File(...)):
    """
    上传视频文件并提取音频
    
    Args:
        file: 上传的视频文件
        
    Returns:
        提取的音频文件
    """
    # 验证文件类型
    if not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="请上传视频文件")
    
    # 生成唯一文件名
    file_id = str(uuid.uuid4())
    video_extension = Path(file.filename).suffix if file.filename else ".mp4"
    video_path = UPLOAD_DIR / f"{file_id}{video_extension}"
    audio_path = OUTPUT_DIR / f"{file_id}.mp3"
    
    try:
        # 保存上传的视频文件
        with open(video_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # 提取音频
        extract_audio(video_path, audio_path)
        
        # 检查输出文件是否存在
        if not audio_path.exists():
            raise HTTPException(status_code=500, detail="音频提取失败，输出文件未生成")
        
        # 返回音频文件
        return FileResponse(
            path=str(audio_path),
            media_type="audio/mpeg",
            filename=f"{Path(file.filename).stem if file.filename else 'audio'}.mp3"
        )
    
    except AudioExtractionError as e:
        # 清理已创建的文件
        if video_path.exists():
            video_path.unlink()
        if audio_path.exists():
            audio_path.unlink()
        
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
    
    except Exception as e:
        # 清理已创建的文件
        if video_path.exists():
            video_path.unlink()
        if audio_path.exists():
            audio_path.unlink()
        
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
    
    finally:
        # 清理上传的视频文件（可选，根据需求决定是否保留）
        if video_path.exists():
            video_path.unlink()

