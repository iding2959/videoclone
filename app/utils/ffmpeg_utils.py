"""
FFmpeg 相关工具函数
"""
import shutil
import platform


def check_ffmpeg_available() -> bool:
    """
    检查系统是否安装了 FFmpeg
    
    Returns:
        True 如果 FFmpeg 可用，False 否则
    """
    return shutil.which("ffmpeg") is not None


def get_ffmpeg_install_hint() -> str:
    """
    根据操作系统返回 FFmpeg 安装提示
    
    Returns:
        安装提示信息
    """
    system = platform.system().lower()
    
    if system == "linux":
        return "请运行: sudo apt update && sudo apt install ffmpeg"
    elif system == "darwin":
        return "请运行: brew install ffmpeg"
    elif system == "windows":
        return "请从 https://ffmpeg.org/download.html 下载并添加到系统 PATH"
    else:
        return "请安装 FFmpeg 并确保它在系统 PATH 中"

