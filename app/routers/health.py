"""
健康检查路由
"""
from fastapi import APIRouter

from app.utils.ffmpeg_utils import check_ffmpeg_available, get_ffmpeg_install_hint

router = APIRouter()


@router.get("/health")
async def health():
    """
    健康检查接口
    
    检查服务状态和 FFmpeg 可用性
    """
    ffmpeg_available = check_ffmpeg_available()
    status = "healthy" if ffmpeg_available else "degraded"
    
    return {
        "status": status,
        "ffmpeg_available": ffmpeg_available,
        "message": "服务正常" if ffmpeg_available else f"FFmpeg 不可用。{get_ffmpeg_install_hint()}"
    }

