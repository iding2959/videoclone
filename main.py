"""
应用入口
"""
import os
import uvicorn
from app.app import create_app
from app.utils import logger

# 创建应用实例
app = create_app()


def main():
    """主函数：启动应用服务器"""
    # 从环境变量获取配置，默认值用于开发环境
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "true").lower() == "true"  # 默认开启热更新
    workers = int(os.getenv("WORKERS", "1"))  # 工作进程数，生产环境可设置为 CPU 核心数
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    
    # 开发环境配置
    if reload:
        logger.info(f"🚀 启动开发服务器 (热更新已启用)")
        logger.info(f"📍 服务地址: http://{host}:{port}")
        logger.info(f"📚 API 文档: http://{host}:{port}/docs")
        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            reload=reload,
            reload_dirs=["app"],  # 只监听 app 目录的变化
            log_level=log_level,
        )
    else:
        # 生产环境配置
        logger.info(f"🚀 启动生产服务器")
        logger.info(f"📍 服务地址: http://{host}:{port}")
        logger.info(f"👷 工作进程数: {workers}")
        uvicorn.run(
            app,
            host=host,
            port=port,
            workers=workers,
            log_level=log_level,
        )


if __name__ == "__main__":
    main()
