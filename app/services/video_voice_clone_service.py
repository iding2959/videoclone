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
    """使用 ffmpeg 将视频音轨替换为新的音频，确保音频长度与视频长度匹配。"""
    if not video_path.exists():
        raise VideoVoiceCloneError(f"视频文件不存在: {video_path}")
    if not audio_path.exists():
        raise VideoVoiceCloneError(f"音频文件不存在: {audio_path}")
    if not check_ffmpeg_available():
        raise VideoVoiceCloneError(f"FFmpeg 未安装或不可用。{get_ffmpeg_install_hint()}")

    try:
        # 获取视频和音频的时长
        video_probe = ffmpeg.probe(str(video_path))
        video_stream = next((s for s in video_probe["streams"] if s["codec_type"] == "video"), None)
        video_duration = float(video_stream.get("duration", 0)) if video_stream else 0
        
        audio_probe = ffmpeg.probe(str(audio_path))
        audio_stream = next((s for s in audio_probe["streams"] if s["codec_type"] == "audio"), None)
        audio_duration = float(audio_stream.get("duration", 0)) if audio_stream else 0
        
        if video_duration <= 0:
            raise VideoVoiceCloneError("无法获取视频时长")
        if audio_duration <= 0:
            raise VideoVoiceCloneError("无法获取音频时长")
        
        logger.info("视频时长: %.2f秒, 音频时长: %.2f秒", video_duration, audio_duration)
        
        video_input = ffmpeg.input(str(video_path))
        audio_input = ffmpeg.input(str(audio_path))
        
        # 通过调整播放速度使音频长度与视频长度匹配
        if abs(audio_duration - video_duration) < 0.1:
            # 时长几乎相同，不需要调整
            logger.info("音频和视频时长匹配，无需调整")
            processed_audio = audio_input["a"]
        else:
            # 计算速度调整比例：音频时长 / 视频时长
            # 如果音频长，需要加速（tempo > 1.0）
            # 如果音频短，需要减速（tempo < 1.0）
            tempo_ratio = audio_duration / video_duration
            
            if tempo_ratio > 1.0:
                logger.info("音频比视频长 %.2f秒，加速音频 %.2fx 倍", audio_duration - video_duration, tempo_ratio)
            else:
                logger.info("音频比视频短 %.2f秒，减速音频 %.2fx 倍", video_duration - audio_duration, tempo_ratio)
            
            # 先获取音频流
            processed_audio = audio_input["a"]
            
            # atempo 过滤器的范围是 0.5 到 2.0
            # 如果需要的调整超出范围，需要串联多个 atempo 过滤器
            if tempo_ratio >= 0.5 and tempo_ratio <= 2.0:
                # 在范围内，直接使用一个 atempo
                processed_audio = processed_audio.filter("atempo", tempo_ratio)
            elif tempo_ratio > 2.0:
                # 需要加速超过 2 倍，串联多个 atempo
                # 例如：如果需要 4 倍速，使用 atempo=2.0, atempo=2.0
                remaining = tempo_ratio
                while remaining > 2.0:
                    processed_audio = processed_audio.filter("atempo", 2.0)
                    remaining /= 2.0
                # 如果 remaining 不等于 1.0，需要再添加一个 atempo
                if abs(remaining - 1.0) > 0.01:  # 允许小的浮点误差
                    processed_audio = processed_audio.filter("atempo", remaining)
            else:
                # 需要减速超过 0.5 倍，串联多个 atempo
                # 例如：如果需要 0.25 倍速，使用 atempo=0.5, atempo=0.5
                remaining = tempo_ratio
                while remaining < 0.5:
                    processed_audio = processed_audio.filter("atempo", 0.5)
                    remaining /= 0.5
                # 如果 remaining 不等于 1.0，需要再添加一个 atempo
                if abs(remaining - 1.0) > 0.01:  # 允许小的浮点误差
                    processed_audio = processed_audio.filter("atempo", remaining)
        
        stream = ffmpeg.output(
            video_input["v"],
            processed_audio,
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
    按 segment_index 顺序合并：克隆成功的段 + 尾段原始音频。
    如果克隆失败，会抛出错误，不会使用原始音频。
    """
    tasks = clone_result.get("tasks", [])
    if not tasks:
        raise VideoVoiceCloneError("没有生成任何克隆任务，无法合并音频")

    # 按 segment_index 排序
    sorted_tasks = sorted(tasks, key=lambda x: x.get("segment_index", 0))

    # 分离克隆任务和尾段（不需要克隆的段）
    clone_task_info = []  # (task_id, segment_index) - 需要等待克隆完成的任务
    tail_audio_tasks = []  # (segment_index, audio_path) - 尾段（没有翻译文本，使用原始音频）
    clone_failed_tasks = []  # (segment_index, error) - 克隆失败的段
    
    for task in sorted_tasks:
        task_id = task.get("task_id")
        error = task.get("error") or ""
        audio_path_str = task.get("audio_path")
        translated_text = task.get("translated_text", "")
        seg_idx = task.get("segment_index", 0)

        if task_id:
            # 有 task_id，需要等待克隆完成
            clone_task_info.append((task_id, seg_idx))
        elif "没有对应的翻译文本" in error or "尾段" in error:
            # 尾段（没有翻译文本），使用原始音频
            if audio_path_str:
                tail_audio_tasks.append((seg_idx, audio_path_str))
            else:
                logger.warning("尾段 segment_%d 没有 audio_path", seg_idx)
        elif translated_text and translated_text.strip():
            # 有翻译文本但没有 task_id，说明克隆失败
            clone_failed_tasks.append((seg_idx, error or "克隆失败：未获取到 task_id"))
        elif audio_path_str:
            # 没有翻译文本也没有 task_id，可能是尾段，但错误信息不明确
            logger.warning("segment_%d 没有 task_id 也没有明确的错误信息，使用原始音频", seg_idx)
            tail_audio_tasks.append((seg_idx, audio_path_str))

    # 检查是否有克隆失败的段
    if clone_failed_tasks:
        failed_segments = [f"segment_{idx}: {err}" for idx, err in clone_failed_tasks]
        error_msg = f"以下音频段克隆失败，必须克隆成功才能继续：\n" + "\n".join(failed_segments)
        logger.error(error_msg)
        raise VideoVoiceCloneError(error_msg)

    logger.info("开始收集克隆任务音频，克隆段数: %d, 尾段数: %d", len(clone_task_info), len(tail_audio_tasks))

    # 使用字典按 segment_index 存储音频文件，确保顺序正确
    audio_files_dict = {}

    # 1. 等待并下载克隆成功的音频
    if clone_task_info:
        logger.info("等待并下载克隆音频，轮询间隔: %.1fs，超时: %.1fs", query_interval, max_wait_time)
        cloned_audio_files = await _wait_and_download_cloned_audios(
            task_info_list=clone_task_info,
            query_interval=query_interval,
            max_wait_time=max_wait_time,
        )
        # 检查下载的文件数量是否正确
        if len(cloned_audio_files) != len(clone_task_info):
            missing_segments = [seg_idx for _, seg_idx in clone_task_info[len(cloned_audio_files):]]
            error_msg = f"克隆音频下载不完整：期望 {len(clone_task_info)} 个文件，实际下载 {len(cloned_audio_files)} 个。缺失的段: {missing_segments}"
            logger.error(error_msg)
            raise VideoVoiceCloneError(error_msg)
        
        # 将克隆音频按 segment_index 存入字典
        # 注意：cloned_audio_files 和 clone_task_info 都是按 segment_index 排序的，顺序一致
        for i, (task_id, seg_idx) in enumerate(clone_task_info):
            audio_files_dict[seg_idx] = cloned_audio_files[i]
            logger.debug("克隆音频 segment_%d -> %s", seg_idx, cloned_audio_files[i])

    # 2. 下载或使用尾段原始音频（没有翻译文本的段，不需要克隆）
    for seg_idx, audio_path_str in tail_audio_tasks:
        audio_path = Path(audio_path_str)
        if audio_path.exists():
            audio_files_dict[seg_idx] = audio_path
            logger.debug("使用尾段原始音频 segment_%d -> %s", seg_idx, audio_path)
        else:
            logger.info("下载尾段原始音频 segment_%d: %s", seg_idx, audio_path.name)
            downloaded = await _download_segment_file(audio_path.name, base_url)
            audio_files_dict[seg_idx] = downloaded

    if not audio_files_dict:
        raise VideoVoiceCloneError("未获取到任何可用的克隆/原始音频文件")

    # 按 segment_index 排序，确保顺序正确
    sorted_segments = sorted(audio_files_dict.keys())
    cloned_audio_files = [audio_files_dict[idx] for idx in sorted_segments]

    try:
        logger.info("开始合并 %d 段音频（按 segment_index 顺序）", len(cloned_audio_files))
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


async def process_video_voice_clone_audio_only(
    video_path: Path,
    query_interval: float = 2.0,
    max_wait_time: float = 300.0,
    base_url: str = "http://localhost:8000",
) -> Dict[str, Any]:
    """
    仅进行语言翻译+音色克隆，并替换视频音轨，不裁剪、不叠字幕。

    返回替换音轨后的视频路径和克隆结果。
    """
    if not video_path.exists():
        raise VideoVoiceCloneError(f"视频文件不存在: {video_path}")

    temp_audio_path = Path(tempfile.gettempdir()) / f"{uuid.uuid4().hex}.wav"
    final_video_path = OUTPUT_DIR / f"voice_clone_{uuid.uuid4().hex}{video_path.suffix}"

    try:
        # 1. 提取音频
        logger.info("步骤1: 提取视频音频 -> %s", temp_audio_path)
        await asyncio.to_thread(extract_audio, video_path, temp_audio_path)

        # 2. 音频翻译克隆
        logger.info("步骤2: 调用音频翻译克隆流程（仅替换音轨）")
        clone_result = await process_audio_translation_clone(audio_file_path=temp_audio_path)
        logger.info("克隆任务数: %d", len(clone_result.get("tasks", [])))

        # 3. 下载并合并克隆音频
        logger.info("步骤3: 下载并合并克隆音频（仅替换音轨）")
        merged_audio_path = await _collect_and_merge_clone_audios(
            clone_result=clone_result,
            query_interval=query_interval,
            max_wait_time=max_wait_time,
            base_url=base_url,
        )

        # 4. 替换视频音轨
        logger.info("步骤4: 替换视频音轨（不裁剪，不叠字幕）")
        await _replace_video_audio(video_path, merged_audio_path, final_video_path)

        logger.info("流程完成，输出视频: %s", final_video_path)
        return {
            "video_path": final_video_path,
            "clone_result": clone_result,
        }

    except (AudioExtractionError, AudioTranslationCloneError) as e:
        raise VideoVoiceCloneError(str(e))
    except VideoVoiceCloneError:
        raise
    except Exception as e:
        raise VideoVoiceCloneError(f"处理失败: {str(e)}")
    finally:
        # 清理临时文件（保留最终视频）
        for path in [temp_audio_path, merged_audio_path if "merged_audio_path" in locals() else None]:
            if path and path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass


async def process_video_voice_clone(
    video_path: Path,
    title_text: str,
    top_cut: int = 390,
    bottom_cut: int = 430,
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

