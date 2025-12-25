"""
FastAPI 应用创建
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import APP_TITLE, APP_VERSION, init_directories
from app.utils import logger  # 导入 loguru 日志系统，确保在应用启动时初始化
from app.routers import (
    base,
    audio_basic,
    audio_clone,
    audio_workflow,
    text,
    video,
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
    app.include_router(base.router)
    app.include_router(audio_basic.router)
    app.include_router(audio_clone.router)
    app.include_router(audio_workflow.router)
    app.include_router(text.router)
    app.include_router(video.router)
    
    return app

