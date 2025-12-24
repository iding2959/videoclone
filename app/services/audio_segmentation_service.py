"""
音频切分服务
根据转录结果的 segments 切分音频文件
"""
from pathlib import Path
from typing import List, Dict, Any, Tuple

import ffmpeg

from app.config import AUDIO_CODEC, AUDIO_CHANNELS, AUDIO_SAMPLE_RATE, OUTPUT_DIR
from app.utils.ffmpeg_utils import check_ffmpeg_available, get_ffmpeg_install_hint


class AudioSegmentationError(Exception):
    """音频切分错误"""
    pass


def segment_audio(
    audio_file_path: Path,
    segments: List[Dict[str, Any]],
    duration: float,
    output_dir: Path = None,
) -> List[Path]:
    """
    根据 segments 切分音频文件
    
    切分规则：
    1. 第一段：0 到第二个 segment 的 start（如果有多个 segment）
       如果只有一个 segment，则第一段是 0 到该 segment 的 start
    2. 中间段：每个 segment 的 start 到 end（从第二个 segment 开始）
    3. 最后一段：最后一个 segment 的 end 到音频结束
    
    例如：segments = [{start:0, end:2.18}, {start:2.46, end:6.14}], duration=11.888625
    切分为：
    - 0-2.46 (0 到第二个 segment 的 start)
    - 2.46-6.14 (第二个 segment 的 start 到 end)
    - 6.14-11.888625 (最后一个 segment 的 end 到结束)
    
    Args:
        audio_file_path: 音频文件路径
        segments: 转录结果的 segments 列表，每个 segment 包含 start 和 end
        duration: 音频总时长（秒）
        output_dir: 输出目录，默认为配置中的 OUTPUT_DIR
        
    Returns:
        切分后的音频文件路径列表
        
    Raises:
        AudioSegmentationError: 如果切分失败
    """
    # 检查 FFmpeg 是否可用
    if not check_ffmpeg_available():
        raise AudioSegmentationError(
            f"FFmpeg 未安装或不在系统 PATH 中。{get_ffmpeg_install_hint()}"
        )
    
    if not audio_file_path.exists():
        raise AudioSegmentationError(f"音频文件不存在: {audio_file_path}")
    
    if not segments:
        raise AudioSegmentationError("segments 列表为空，无法切分音频")
    
    # 使用配置的输出目录
    output_dir = output_dir or OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)
    
    # 生成输出文件名前缀
    audio_stem = audio_file_path.stem
    output_paths = []
    
    try:
        # 计算切分时间段
        time_segments = _calculate_time_segments(segments, duration)
        
        # 对每个时间段进行切分
        for idx, (start_time, end_time) in enumerate(time_segments, 1):
            output_filename = f"{audio_stem}_segment_{idx}.wav"
            output_path = output_dir / output_filename
            
            # 使用 ffmpeg 切分音频
            stream = ffmpeg.input(str(audio_file_path), ss=start_time, t=end_time - start_time)
            stream = ffmpeg.output(
                stream,
                str(output_path),
                acodec=AUDIO_CODEC,
                ac=AUDIO_CHANNELS,
                ar=AUDIO_SAMPLE_RATE
            )
            ffmpeg.run(stream, overwrite_output=True, quiet=True)
            
            output_paths.append(output_path)
        
        return output_paths
    
    except FileNotFoundError as e:
        raise AudioSegmentationError(
            f"FFmpeg 未找到: {str(e)}。{get_ffmpeg_install_hint()}"
        )
    except ffmpeg.Error as e:
        error_message = e.stderr.decode() if e.stderr else str(e)
        raise AudioSegmentationError(f"音频切分失败: {error_message}")
    except Exception as e:
        if "No such file or directory" in str(e) or "ffmpeg" in str(e).lower():
            raise AudioSegmentationError(
                f"FFmpeg 未找到: {str(e)}。{get_ffmpeg_install_hint()}"
            )
        raise AudioSegmentationError(f"音频切分失败: {str(e)}")


def _calculate_time_segments(
    segments: List[Dict[str, Any]],
    duration: float
) -> List[Tuple[float, float]]:
    """
    计算切分时间段
    
    切分规则：
    1. 第一段：0 到第二个 segment 的 start（如果有多个 segment）
       如果只有一个 segment，则第一段是 0 到该 segment 的 start
    2. 中间段：每个 segment 的 start 到 end（从第二个 segment 开始）
    3. 最后一段：最后一个 segment 的 end 到音频结束
    
    例如：segments = [{start:0, end:2.18}, {start:2.46, end:6.14}], duration=11.888625
    切分为：
    - 0-2.46 (0 到第二个 segment 的 start)
    - 2.46-6.14 (第二个 segment 的 start 到 end)
    - 6.14-11.888625 (最后一个 segment 的 end 到结束)
    
    Args:
        segments: 转录结果的 segments 列表
        duration: 音频总时长
        
    Returns:
        时间段列表，每个元素为 (start_time, end_time) 元组
    """
    time_segments = []
    
    if not segments:
        return time_segments
    
    # 按 start 时间排序 segments
    sorted_segments = sorted(segments, key=lambda x: x.get("start", 0))
    
    if len(sorted_segments) == 1:
        # 只有一个 segment 的情况
        segment = sorted_segments[0]
        segment_start = segment.get("start", 0)
        segment_end = segment.get("end", 0)
        
        # 第一段：0 到 segment 的 start
        if segment_start > 0:
            time_segments.append((0.0, segment_start))
        
        # 第二段：segment 的 end 到结束
        if segment_end < duration:
            time_segments.append((segment_end, duration))
    else:
        # 多个 segments 的情况
        # 第一段：0 到第二个 segment 的 start
        second_segment_start = sorted_segments[1].get("start", 0)
        if second_segment_start > 0:
            time_segments.append((0.0, second_segment_start))
        
        # 中间段：从第二个 segment 开始，每个 segment 的 start 到 end
        for i in range(1, len(sorted_segments)):
            segment = sorted_segments[i]
            segment_start = segment.get("start", 0)
            segment_end = segment.get("end", 0)
            time_segments.append((segment_start, segment_end))
        
        # 最后一段：最后一个 segment 的 end 到音频结束
        last_segment_end = sorted_segments[-1].get("end", 0)
        if last_segment_end < duration:
            time_segments.append((last_segment_end, duration))
    
    return time_segments

