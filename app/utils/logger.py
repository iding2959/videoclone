"""
日志工具模块
使用 loguru 实现日志系统
"""
import sys
from loguru import logger
from pathlib import Path
from app.config import (
    LOG_DIR,
    LOG_CONSOLE_LEVEL,
    LOG_FILE_LEVEL,
    LOG_ROTATION,
    LOG_RETENTION_DAYS,
    LOG_ENCODING,
)

# 导出日志配置常量，供其他模块使用
__all__ = [
    "logger",
    "setup_logger",
    "LOG_DIR",
    "LOG_CONSOLE_LEVEL",
    "LOG_FILE_LEVEL",
    "LOG_ROTATION",
    "LOG_RETENTION_DAYS",
    "LOG_ENCODING",
]


def setup_logger():
    """
    配置 loguru 日志系统
    
    配置说明:
    - 控制台输出: INFO 级别
    - 文件输出: DEBUG 级别
    - 日志文件: 按年月日命名，每天午夜切分
    - 日志保留: 30天
    """
    # 移除默认的处理器
    logger.remove()
    
    # 添加控制台输出处理器（INFO 级别）
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=LOG_CONSOLE_LEVEL,
        colorize=True,
    )
    
    # 确保日志目录存在
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    # 添加文件输出处理器（DEBUG 级别）
    # 日志文件名格式: logs/2024-01-01.log (按年月日命名)
    log_file_path = LOG_DIR / "{time:YYYY-MM-DD}.log"
    
    logger.add(
        str(log_file_path),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        level=LOG_FILE_LEVEL,
        rotation=LOG_ROTATION,  # 每天午夜切分
        retention=f"{LOG_RETENTION_DAYS} days",  # 保留30天
        encoding=LOG_ENCODING,
        enqueue=True,  # 异步写入，提高性能
        backtrace=True,  # 显示完整的错误堆栈
        diagnose=True,  # 显示变量值
    )
    
    return logger


# 初始化日志系统
setup_logger()

