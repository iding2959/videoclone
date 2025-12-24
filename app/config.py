"""
应用配置
"""
from pathlib import Path

# 目录配置
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")

# 应用配置
APP_TITLE = "视频音频分离服务"
APP_VERSION = "0.1.0"

# 音频输出配置
AUDIO_CODEC = "libmp3lame"
AUDIO_CHANNELS = 2
AUDIO_SAMPLE_RATE = "44100"
AUDIO_FORMAT = "mp3"


def init_directories():
    """初始化必要的目录"""
    UPLOAD_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

