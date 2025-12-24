"""
音频提取服务
"""
from pathlib import Path

import ffmpeg

from app.config import AUDIO_CODEC, AUDIO_CHANNELS, AUDIO_SAMPLE_RATE
from app.utils.ffmpeg_utils import check_ffmpeg_available, get_ffmpeg_install_hint


class AudioExtractionError(Exception):
    """音频提取错误"""
    pass


def extract_audio(video_path: Path, output_path: Path) -> Path:
    """
    从视频文件中提取音频
    
    Args:
        video_path: 视频文件路径
        output_path: 输出音频文件路径
        
    Returns:
        输出音频文件路径
        
    Raises:
        AudioExtractionError: 如果提取失败
    """
    # 检查 FFmpeg 是否可用
    if not check_ffmpeg_available():
        raise AudioExtractionError(
            f"FFmpeg 未安装或不在系统 PATH 中。{get_ffmpeg_install_hint()}"
        )
    
    try:
        # 使用 ffmpeg 提取音频，输出为 MP3 格式
        stream = ffmpeg.input(str(video_path))
        stream = ffmpeg.output(
            stream,
            str(output_path),
            acodec=AUDIO_CODEC,
            ac=AUDIO_CHANNELS,
            ar=AUDIO_SAMPLE_RATE
        )
        ffmpeg.run(stream, overwrite_output=True, quiet=True)
        return output_path
    except FileNotFoundError as e:
        raise AudioExtractionError(
            f"FFmpeg 未找到: {str(e)}。{get_ffmpeg_install_hint()}"
        )
    except ffmpeg.Error as e:
        error_message = e.stderr.decode() if e.stderr else str(e)
        raise AudioExtractionError(f"音频提取失败: {error_message}")
    except Exception as e:
        # 捕获其他可能的异常（如 OSError）
        if "No such file or directory" in str(e) or "ffmpeg" in str(e).lower():
            raise AudioExtractionError(
                f"FFmpeg 未找到: {str(e)}。{get_ffmpeg_install_hint()}"
            )
        raise AudioExtractionError(f"音频提取失败: {str(e)}")

