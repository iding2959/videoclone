"""
音频处理服务
整合音频提取、切分、合并等功能
"""
import asyncio
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import httpx
import ffmpeg

from app.config import OUTPUT_DIR, AUDIO_CODEC, AUDIO_CHANNELS, AUDIO_SAMPLE_RATE
from app.utils.ffmpeg_utils import check_ffmpeg_available, get_ffmpeg_install_hint
from app.utils.logger import logger

from app.services.text_processing_service import query_task_status, download_audio_file, TTSError


class AudioProcessingError(Exception):
    """音频处理错误基类"""
    pass


class AudioExtractionError(AudioProcessingError):
    """音频提取错误"""
    pass


class AudioSegmentationError(AudioProcessingError):
    """音频切分错误"""
    pass


class AudioMergeError(AudioProcessingError):
    """音频合并错误"""
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
    if not check_ffmpeg_available():
        raise AudioExtractionError(
            f"FFmpeg 未安装或不在系统 PATH 中。{get_ffmpeg_install_hint()}"
        )
    
    try:
        logger.info(f"开始提取音频: {video_path} -> {output_path}")
        stream = ffmpeg.input(str(video_path))
        stream = ffmpeg.output(
            stream,
            str(output_path),
            acodec=AUDIO_CODEC,
            ac=AUDIO_CHANNELS,
            ar=AUDIO_SAMPLE_RATE
        )
        ffmpeg.run(stream, overwrite_output=True, quiet=True)
        logger.info(f"音频提取完成: {output_path}")
        return output_path
    except FileNotFoundError as e:
        raise AudioExtractionError(
            f"FFmpeg 未找到: {str(e)}。{get_ffmpeg_install_hint()}"
        )
    except ffmpeg.Error as e:
        error_message = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"音频提取失败: {error_message}")
        raise AudioExtractionError(f"音频提取失败: {error_message}")
    except Exception as e:
        if "No such file or directory" in str(e) or "ffmpeg" in str(e).lower():
            raise AudioExtractionError(
                f"FFmpeg 未找到: {str(e)}。{get_ffmpeg_install_hint()}"
            )
        logger.error(f"音频提取异常: {str(e)}")
        raise AudioExtractionError(f"音频提取失败: {str(e)}")


def segment_audio(
    audio_file_path: Path,
    segments: List[Dict[str, Any]],
    duration: float,
    output_dir: Optional[Path] = None,
) -> List[Path]:
    """
    根据 segments 切分音频文件
    
    切分规则：
    1. 逐段按 start/end 切分，保持与转录段落一致
    2. 追加尾段（最后一个 segment 的 end 到音频结束）
    
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
    if not check_ffmpeg_available():
        raise AudioSegmentationError(
            f"FFmpeg 未安装或不在系统 PATH 中。{get_ffmpeg_install_hint()}"
        )
    
    if not audio_file_path.exists():
        raise AudioSegmentationError(f"音频文件不存在: {audio_file_path}")
    
    if not segments:
        raise AudioSegmentationError("segments 列表为空，无法切分音频")
    
    output_dir = output_dir or OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)
    
    audio_stem = audio_file_path.stem
    output_paths = []
    
    try:
        logger.info(f"开始切分音频: {audio_file_path}, 共 {len(segments)} 个段落")
        time_segments = _calculate_time_segments(segments, duration)
        
        for idx, (start_time, end_time) in enumerate(time_segments, 1):
            output_filename = f"{audio_stem}_segment_{idx}.wav"
            output_path = output_dir / output_filename
            
            logger.debug(f"切分段落 {idx}: [{start_time:.2f}s - {end_time:.2f}s] -> {output_path.name}")
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
        
        logger.info(f"音频切分完成: 共生成 {len(output_paths)} 个音频段")
        return output_paths
    
    except FileNotFoundError as e:
        raise AudioSegmentationError(
            f"FFmpeg 未找到: {str(e)}。{get_ffmpeg_install_hint()}"
        )
    except ffmpeg.Error as e:
        error_message = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"音频切分失败: {error_message}")
        raise AudioSegmentationError(f"音频切分失败: {error_message}")
    except Exception as e:
        if "No such file or directory" in str(e) or "ffmpeg" in str(e).lower():
            raise AudioSegmentationError(
                f"FFmpeg 未找到: {str(e)}。{get_ffmpeg_install_hint()}"
            )
        logger.error(f"音频切分异常: {str(e)}")
        raise AudioSegmentationError(f"音频切分失败: {str(e)}")


def _calculate_time_segments(
    segments: List[Dict[str, Any]],
    duration: float
) -> List[Tuple[float, float]]:
    """
    计算切分时间段
    
    切分规则：
    1. 逐段按 start/end 切分，保持与转录段落一致
    2. 追加尾段（最后一个 segment 的 end 到音频结束）
    
    Args:
        segments: 转录结果的 segments 列表
        duration: 音频总时长
        
    Returns:
        时间段列表，每个元素为 (start_time, end_time) 元组
    """
    time_segments = []
    
    if not segments:
        return time_segments
    
    sorted_segments = sorted(segments, key=lambda x: x.get("start", 0))
    
    # 逐段按 start/end 切分，保持与转录段落一致
    for seg in sorted_segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        if seg_end <= seg_start:
            continue
        time_segments.append((float(seg_start), float(seg_end)))
    
    # 追加尾段（原始音频，不做克隆/翻译）
    last_end = sorted_segments[-1].get("end", 0) if sorted_segments else 0
    if last_end < duration:
        time_segments.append((float(last_end), float(duration)))
    
    return time_segments


async def merge_audio_files(audio_files: List[Path]) -> Path:
    """
    合并多个音频文件
    
    Args:
        audio_files: 音频文件路径列表
        
    Returns:
        合并后的音频文件路径
        
    Raises:
        AudioMergeError: 如果合并失败
    """
    if not audio_files:
        raise AudioMergeError("没有音频文件需要合并")
    
    if len(audio_files) == 1:
        logger.info("只有一个音频文件，无需合并")
        return audio_files[0]
    
    output_id = str(uuid.uuid4())
    output_path = OUTPUT_DIR / f"merged_{output_id}.wav"
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    try:
        logger.info(f"开始合并 {len(audio_files)} 个音频文件 -> {output_path}")
        inputs = [ffmpeg.input(str(audio_file)) for audio_file in audio_files]
        merged = ffmpeg.concat(*inputs, v=0, a=1)
        stream = ffmpeg.output(
            merged,
            str(output_path),
            acodec=AUDIO_CODEC,
            ac=AUDIO_CHANNELS,
            ar=AUDIO_SAMPLE_RATE
        )
        ffmpeg.run(stream, overwrite_output=True, quiet=True)
        logger.info(f"音频合并完成: {output_path}")
        return output_path
    
    except FileNotFoundError as e:
        raise AudioMergeError(f"FFmpeg 未找到: {str(e)}。{get_ffmpeg_install_hint()}")
    except ffmpeg.Error as e:
        error_message = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"音频合并失败: {error_message}")
        raise AudioMergeError(f"音频合并失败: {error_message}")
    except Exception as e:
        if "No such file or directory" in str(e) or "ffmpeg" in str(e).lower():
            raise AudioMergeError(f"FFmpeg 未找到: {str(e)}。{get_ffmpeg_install_hint()}")
        logger.error(f"音频合并异常: {str(e)}")
        raise AudioMergeError(f"音频合并失败: {str(e)}")


async def wait_and_download_cloned_audios(
    task_info_list: List[Tuple[str, int]],
    query_interval: float = 2.0,
    max_wait_time: float = 300.0,
) -> List[Path]:
    """
    等待克隆任务完成并下载音频文件
    
    Args:
        task_info_list: (task_id, segment_index) 元组列表，按 segment_index 排序
        query_interval: 查询间隔（秒）
        max_wait_time: 最大等待时间（秒）
        
    Returns:
        下载的音频文件路径列表，按 segment_index 顺序排列
        
    Raises:
        AudioMergeError: 如果等待或下载失败
    """
    temp_dir = Path(tempfile.gettempdir()) / f"audio_merge_{uuid.uuid4()}"
    temp_dir.mkdir(exist_ok=True)
    
    downloaded_files_dict = {}
    pending_tasks = {task_id: segment_index for task_id, segment_index in task_info_list}
    
    start_time = time.time()
    query_count = 0
    
    while pending_tasks and (time.time() - start_time) < max_wait_time:
        query_count += 1
        elapsed_time = time.time() - start_time
        logger.info(f"查询轮次 {query_count}: 还有 {len(pending_tasks)} 个任务待处理，已等待 {elapsed_time:.1f} 秒")
        
        for task_id, segment_index in list(pending_tasks.items()):
            try:
                result = await query_task_status(task_id=task_id)
                
                data = result.get("data", {})
                if not data:
                    data = result
                    logger.debug(f"使用顶层数据（无data字段）")
                
                status = data.get("status", "")
                logger.debug(f"任务 {task_id} (segment {segment_index}) 状态: '{status}'")
                
                if status in ["completed", "success", "done", "finished"]:
                    task_result = data.get("result", {})
                    if not task_result:
                        task_result = result.get("result", {})
                    
                    filename = task_result.get("filename") or task_result.get("file") or task_result.get("audio_file")
                    if filename:
                        logger.info(f"任务完成，开始下载音频文件: {filename}")
                        audio_content = await download_audio_file(filename)
                        audio_path = temp_dir / filename
                        with open(audio_path, "wb") as f:
                            f.write(audio_content)
                        downloaded_files_dict[segment_index] = audio_path
                        del pending_tasks[task_id]
                        logger.info(f"音频文件已下载: {audio_path}")
                    else:
                        logger.warning(f"任务完成但未找到文件名，完整响应: {result}")
                elif status in ["failed", "error", "failure"]:
                    error_msg = data.get("error") or data.get("message") or result.get("error") or result.get("message") or "任务失败"
                    raise AudioMergeError(f"克隆任务 {task_id} 失败: {error_msg}")
                elif status in ["processing", "pending", "running", "in_progress", "queued"]:
                    logger.debug(f"任务进行中，继续等待...")
                else:
                    logger.warning(f"未知状态 '{status}'，完整响应: {result}")
                
            except TTSError as e:
                logger.error(f"查询任务 {task_id} 状态失败: {str(e)}")
                raise AudioMergeError(f"查询任务 {task_id} 状态失败: {str(e)}")
        
        if pending_tasks:
            logger.debug(f"等待 {query_interval} 秒后继续查询...")
            await asyncio.sleep(query_interval)
    
    if pending_tasks:
        raise AudioMergeError(f"等待任务完成超时，仍有 {len(pending_tasks)} 个任务未完成")
    
    sorted_segments = sorted(downloaded_files_dict.keys())
    return [downloaded_files_dict[idx] for idx in sorted_segments]


async def download_segment_file(filename: str, base_url: str) -> Path:
    """
    从服务器下载切分的音频文件
    
    Args:
        filename: 文件名
        base_url: API 基础URL
        
    Returns:
        下载的音频文件路径
        
    Raises:
        AudioMergeError: 如果下载失败
    """
    download_url = f"{base_url}/segment/download/{filename}"
    
    temp_file_id = str(uuid.uuid4())
    file_extension = Path(filename).suffix
    audio_path = Path(tempfile.gettempdir()) / f"audio_merge_{temp_file_id}{file_extension}"
    
    try:
        logger.info(f"开始下载音频文件: {filename}")
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(download_url)
            response.raise_for_status()
            
            with open(audio_path, "wb") as f:
                f.write(response.content)
            
            logger.info(f"音频文件下载完成: {audio_path}")
            return audio_path
    except httpx.HTTPStatusError as e:
        logger.error(f"下载音频文件失败 (状态码 {e.response.status_code}): {e.response.text}")
        raise AudioMergeError(f"下载音频文件失败 (状态码 {e.response.status_code}): {e.response.text}")
    except httpx.RequestError as e:
        logger.error(f"下载音频文件请求错误: {str(e)}")
        raise AudioMergeError(f"下载音频文件请求错误: {str(e)}")
    except Exception as e:
        logger.error(f"下载音频文件异常: {str(e)}")
        raise AudioMergeError(f"下载音频文件失败: {str(e)}")

