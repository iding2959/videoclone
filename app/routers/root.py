"""
根路由
"""
from fastapi import APIRouter

from app.config import APP_VERSION

router = APIRouter()


@router.get("/")
async def root():
    """根路径，返回服务信息"""
    return {
        "service": "视频音频分离服务",
        "version": APP_VERSION,
        "endpoints": {
            "POST /extract": "上传视频文件，提取音频",
            "GET /health": "健康检查"
        }
    }

