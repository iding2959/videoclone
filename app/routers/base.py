"""
基础路由模块
包含根路径和健康检查等基础功能
"""
from fastapi import APIRouter

from app.config import APP_VERSION
from app.utils.ffmpeg_utils import check_ffmpeg_available, get_ffmpeg_install_hint

router = APIRouter()


@router.get("/")
async def root():
    """根路径，返回服务信息"""
    return {
        "service": "视频音频分离服务",
        "version": APP_VERSION,
        "endpoints": {
            "POST /extract": "上传视频文件，提取音频",
            "POST /transcribe": "上传音频文件，进行转录",
            "GET /health": "健康检查"
        }
    }


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

