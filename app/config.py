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
AUDIO_CODEC = "pcm_s16le"  # WAV 格式使用 PCM 16-bit little-endian
AUDIO_CHANNELS = 2
AUDIO_SAMPLE_RATE = "44100"
AUDIO_FORMAT = "wav"

# 音频转录 API 配置
TRANSCRIPTION_API_URL = "http://192.168.0.214/v1/audio/transcriptions"
TRANSCRIPTION_API_TOKEN = "gpustack_db6811f08062786a_f9fa57c6db2b89b6297bf749ecddd9bf"
TRANSCRIPTION_DEFAULT_MODEL = "Faster-Whisper-Large-V3"
TRANSCRIPTION_DEFAULT_LANGUAGE = "zh"
TRANSCRIPTION_DEFAULT_RESPONSE_FORMAT = "verbose_json"

# 翻译 API 配置
TRANSLATION_API_URL = "http://192.168.0.214/v1/chat/completions"
TRANSLATION_API_TOKEN = "gpustack_db6811f08062786a_f9fa57c6db2b89b6297bf749ecddd9bf"
TRANSLATION_DEFAULT_MODEL = "Hunyuan-MT-Chimera-7B"
TRANSLATION_DEFAULT_SYSTEM_PROMPT = "你是一名专业的翻译官，将下面文本翻译成英文"

# TTS 音频克隆 API 配置
TTS_API_BASE_URL = "http://192.168.0.215:8147"
TTS_SYNTHESIZE_ASYNC_URL = f"{TTS_API_BASE_URL}/api/tts/synthesize-async"
TTS_TASK_QUERY_URL = f"{TTS_API_BASE_URL}/api/tts/task"
TTS_DOWNLOAD_URL = f"{TTS_API_BASE_URL}/api/tts/download"


def init_directories():
    """初始化必要的目录"""
    UPLOAD_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

