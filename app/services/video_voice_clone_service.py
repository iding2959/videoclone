"""
综合视频音色克隆与字幕叠加服务。

流程：
1. 从视频中提取音频。
2. 调用音频翻译克隆流程，获得克隆任务与字幕分段。
3. 轮询并下载克隆音频，合并为完整音轨。
4. 将合并后的音轨替换到原视频。
5. 按固定像素裁剪视频（默认上 200、下 250）。
6. 叠加标题与字幕，输出最终视频。
"""
import asyncio
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any

import ffmpeg

from app.config import OUTPUT_DIR
from app.services.audio_service import extract_audio, AudioExtractionError
from app.services.audio_translation_clone_service import (
    process_audio_translation_clone,
    AudioTranslationCloneError,
)
from app.services.audio_merge_service import (
    _wait_and_download_cloned_audios,
    _download_segment_file,
    _merge_audio_files,
    AudioMergeError,
)
from app.services.video_crop_service import detect_and_crop_video, VideoCropError
from app.services.video_overlay_service import overlay_title_and_subtitles, VideoOverlayError
from app.utils.ffmpeg_utils import check_ffmpeg_available, get_ffmpeg_install_hint

logger = logging.getLogger(__name__)


class VideoVoiceCloneError(Exception):
    """综合视频音色克隆错误"""


async def _replace_video_audio(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """使用 ffmpeg 将视频音轨替换为新的音频。"""
    if not video_path.exists():
        raise VideoVoiceCloneError(f"视频文件不存在: {video_path}")
    if not audio_path.exists():
        raise VideoVoiceCloneError(f"音频文件不存在: {audio_path}")
    if not check_ffmpeg_available():
        raise VideoVoiceCloneError(f"FFmpeg 未安装或不可用。{get_ffmpeg_install_hint()}")

    try:
        logger.info("开始替换视频音轨 -> 视频: %s, 音频: %s", video_path, audio_path)
        stream = ffmpeg.input(str(video_path))
        audio_stream = ffmpeg.input(str(audio_path))
        stream = ffmpeg.output(
            stream["v"],
            audio_stream["a"],
            str(output_path),
            vcodec="copy",
            acodec="aac",
            strict="-2",
            shortest=None,
        )
        ffmpeg.run(stream, overwrite_output=True, quiet=True)
        logger.info("音轨替换完成 -> 输出: %s", output_path)
        return output_path
    except ffmpeg.Error as e:
        detail = e.stderr.decode() if e.stderr else str(e)
        raise VideoVoiceCloneError(f"音频替换失败: {detail}")
    except Exception as e:
        if isinstance(e, VideoVoiceCloneError):
            raise
        raise VideoVoiceCloneError(f"音频替换失败: {str(e)}")


async def _collect_and_merge_clone_audios(
    clone_result: Dict[str, Any],
    query_interval: float = 2.0,
    max_wait_time: float = 300.0,
    base_url: str = "http://localhost:8000",
) -> Path:
    """
    基于克隆结果下载并合并音频。
    仅合并有翻译文本的克隆段 + 尾段原始音频，确保段数与切分一致。
    """
    tasks = clone_result.get("tasks", [])
    if not tasks:
        raise VideoVoiceCloneError("没有生成任何克隆任务，无法合并音频")

    # 按 segment_index 排序
    sorted_tasks = sorted(tasks, key=lambda x: x.get("segment_index", 0))

    # 分离克隆段与尾段
    clone_task_info = []  # (task_id, segment_index)
    tail_audio_paths: List[Path] = []
    for task in sorted_tasks:
        task_id = task.get("task_id")
        error = task.get("error") or ""
        audio_path_str = task.get("audio_path")
        seg_idx = task.get("segment_index", 0)

        if task_id:
            clone_task_info.append((task_id, seg_idx))
        # 认为没有翻译文本的段（尾段或空翻译）只保留原始音频
        if "没有对应的翻译文本" in error and audio_path_str:
            tail_audio_paths.append(Path(audio_path_str))

    logger.info("开始收集克隆任务音频，克隆段数: %d, 尾段数: %d", len(clone_task_info), len(tail_audio_paths))

    cloned_audio_files: List[Path] = []
    if clone_task_info:
        logger.info("等待并下载克隆音频，轮询间隔: %.1fs，超时: %.1fs", query_interval, max_wait_time)
        cloned_audio_files.extend(
            await _wait_and_download_cloned_audios(
                task_info_list=clone_task_info,
                query_interval=query_interval,
                max_wait_time=max_wait_time,
            )
        )

    # 追加尾段原始音频
    for tail_path in tail_audio_paths:
        if tail_path.exists():
            cloned_audio_files.append(tail_path)
        else:
            logger.info("下载尾段原始音频: %s", tail_path.name)
            downloaded = await _download_segment_file(tail_path.name, base_url)
            cloned_audio_files.append(downloaded)

    if not cloned_audio_files:
        raise VideoVoiceCloneError("未获取到任何可用的克隆/原始音频文件")

    try:
        logger.info("开始合并 %d 段音频", len(cloned_audio_files))
        merged_audio_path = await _merge_audio_files(cloned_audio_files)
        logger.info("音频合并完成 -> %s", merged_audio_path)
    except AudioMergeError as e:
        raise VideoVoiceCloneError(str(e))

    # 清理中间文件（合并后的文件除外）
    for temp_file in cloned_audio_files:
        if temp_file != merged_audio_path and temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass

    return merged_audio_path


async def process_video_voice_clone(
    video_path: Path,
    title_text: str,
    top_cut: int = 200,
    bottom_cut: int = 250,
    query_interval: float = 2.0,
    max_wait_time: float = 300.0,
    base_url: str = "http://localhost:8000",
    title_block_height: int = 120,
    subtitle_block_height: int = 160,
    title_font_size: Optional[int] = None,
    subtitle_font_size: Optional[int] = None,
    fontfile: Optional[str] = None,
) -> Dict[str, Any]:
    """
    执行视频音色克隆、裁剪与字幕叠加的完整流程。

    返回最终视频路径及字幕数据。
    """
    if not video_path.exists():
        raise VideoVoiceCloneError(f"视频文件不存在: {video_path}")

    temp_audio_path = Path(tempfile.gettempdir()) / f"{uuid.uuid4().hex}.wav"
    replaced_video_path = OUTPUT_DIR / f"voice_replaced_{uuid.uuid4().hex}{video_path.suffix}"
    cropped_video_path = OUTPUT_DIR / f"cropped_{uuid.uuid4().hex}{video_path.suffix}"
    final_video_path = OUTPUT_DIR / f"voice_clone_overlay_{uuid.uuid4().hex}{video_path.suffix}"

    try:
        # 1. 提取音频
        logger.info("步骤1: 提取视频音频 -> %s", temp_audio_path)
        await asyncio.to_thread(extract_audio, video_path, temp_audio_path)

        # 2. 音频翻译克隆，获取字幕
        logger.info("步骤2: 调用音频翻译克隆流程")
        clone_result = await process_audio_translation_clone(audio_file_path=temp_audio_path)
        subtitle_segments = clone_result.get("subtitle_segments", [])
        logger.info("克隆任务数: %d，字幕段数: %d", len(clone_result.get("tasks", [])), len(subtitle_segments))

        # 3. 下载并合并克隆音频
        logger.info("步骤3: 下载并合并克隆音频")
        merged_audio_path = await _collect_and_merge_clone_audios(
            clone_result=clone_result,
            query_interval=query_interval,
            max_wait_time=max_wait_time,
            base_url=base_url,
        )

        # 4. 替换视频音轨
        logger.info("步骤4: 替换视频音轨")
        await _replace_video_audio(video_path, merged_audio_path, replaced_video_path)

        # 5. 固定裁剪
        logger.info("步骤5: 固定裁剪视频 top=%d bottom=%d", top_cut, bottom_cut)
        await asyncio.to_thread(
            detect_and_crop_video,
            replaced_video_path,
            cropped_video_path,
            top_cut,
            bottom_cut,
        )

        # 6. 叠加标题与字幕
        logger.info("步骤6: 叠加标题与字幕，标题: %s", title_text)
        await asyncio.to_thread(
            overlay_title_and_subtitles,
            cropped_video_path,
            final_video_path,
            title_text,
            subtitle_segments,
            title_block_height,
            subtitle_block_height,
            title_font_size,
            subtitle_font_size,
            fontfile,
        )

        logger.info("流程完成，输出视频: %s", final_video_path)
        return {
            "video_path": final_video_path,
            "subtitle_segments": subtitle_segments,
            "clone_result": clone_result,
        }

    except (AudioExtractionError, AudioTranslationCloneError, VideoCropError, VideoOverlayError) as e:
        raise VideoVoiceCloneError(str(e))
    except VideoVoiceCloneError:
        raise
    except Exception as e:
        raise VideoVoiceCloneError(f"处理失败: {str(e)}")
    finally:
        # 清理临时与中间文件（保留最终视频）
        for path in [
            temp_audio_path,
            merged_audio_path if "merged_audio_path" in locals() else None,
            replaced_video_path if replaced_video_path.exists() and final_video_path != replaced_video_path else None,
            cropped_video_path if cropped_video_path.exists() and final_video_path != cropped_video_path else None,
        ]:
            if path and path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass

