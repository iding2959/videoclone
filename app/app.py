"""
FastAPI 应用创建
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import APP_TITLE, APP_VERSION, init_directories
from app.utils import logger  # 导入 loguru 日志系统，确保在应用启动时初始化
from app.routers import (
    root,
    health,
    extract,
    transcription,
    translation,
    tts,
    audio_translation_clone,
    audio_merge,
    video_crop,
    video_overlay,
    video_voice_clone,
)


def create_app() -> FastAPI:
    """
    创建并配置 FastAPI 应用
    
    Returns:
        配置好的 FastAPI 应用实例
    """
    # 日志系统已在导入时自动初始化（app.utils.logger）
    logger.info("正在初始化 FastAPI 应用...")
    
    # 初始化目录
    init_directories()
    
    # 创建应用
    app = FastAPI(title=APP_TITLE, version=APP_VERSION)
    
    # 配置 CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 注册路由
    app.include_router(root.router)
    app.include_router(health.router)
    app.include_router(extract.router)
    app.include_router(transcription.router)
    app.include_router(translation.router)
    app.include_router(tts.router)
    app.include_router(audio_translation_clone.router)
    app.include_router(audio_merge.router)
    app.include_router(video_crop.router)
    app.include_router(video_overlay.router)
    app.include_router(video_voice_clone.router)
    
    return app

