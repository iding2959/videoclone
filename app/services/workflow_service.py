"""
工作流服务
整合音频翻译克隆和视频音色克隆的完整流程
"""
import asyncio
import tempfile
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import ffmpeg

from app.config import OUTPUT_DIR
from app.services.audio_processing_service import (
    extract_audio,
    AudioExtractionError,
    segment_audio,
    AudioSegmentationError,
    wait_and_download_cloned_audios,
    download_segment_file,
    merge_audio_files,
    AudioMergeError,
)
from app.services.text_processing_service import (
    transcribe_audio,
    TranscriptionError,
    translate_text,
    TranslationError,
    synthesize_audio_async,
    TTSError,
)
from app.services.video_processing_service import (
    detect_and_crop_video,
    VideoCropError,
    overlay_title_and_subtitles,
    VideoOverlayError,
)
from app.utils.ffmpeg_utils import check_ffmpeg_available, get_ffmpeg_install_hint
from app.utils.logger import logger


class WorkflowError(Exception):
    """工作流错误基类"""
    pass


class AudioTranslationCloneError(WorkflowError):
    """音频翻译克隆错误"""
    pass


class VideoVoiceCloneError(WorkflowError):
    """综合视频音色克隆错误"""
    pass


def _calculate_time_segments(
    segments: List[Dict[str, Any]],
    duration: float
) -> List[Tuple[float, float]]:
    """
    计算切分时间段：逐段(start,end) + 尾段。
    尾段用于保留原始音频，不进行克隆。
    """
    time_segments = []
    
    if not segments:
        return time_segments
    
    sorted_segments = sorted(segments, key=lambda x: x.get("start", 0))
    
    for seg in sorted_segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        if seg_end <= seg_start:
            continue
        time_segments.append((float(seg_start), float(seg_end)))
    
    last_end = sorted_segments[-1].get("end", 0)
    if last_end < duration:
        time_segments.append((float(last_end), float(duration)))
    
    return time_segments


async def process_audio_translation_clone(
    audio_file_path: Path,
    transcription_model: Optional[str] = None,
    transcription_language: Optional[str] = None,
    transcription_response_format: Optional[str] = None,
    translation_model: Optional[str] = None,
    translation_system_prompt: Optional[str] = None,
    emo_control_method: int = 0,
    emo_weight: float = 0.65,
    emo_text: str = "",
    max_text_tokens_per_segment: int = 120,
    temperature: float = 0.8,
    top_p: float = 0.8,
    top_k: int = 30,
    emo_audio_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    音频翻译克隆完整流程
    
    流程：
    1. 音频转录 - 将音频转录为文本，得到 segments 和 duration
    2. 翻译文本 - 对每个 segment 的文本进行翻译
    3. 音频切分 - 根据 segments 切分音频，得到对应的音频段（包括最后多余的一段）
    4. 音色克隆 - 对每个切分后的音频段，使用该音频段本身作为音色参考，使用对应的翻译文本进行音色克隆
    
    Args:
        audio_file_path: 要处理的音频文件路径
        transcription_model: 转录使用的模型（可选，默认使用配置中的模型）
        transcription_language: 转录使用的语言代码（可选，默认使用配置中的语言）
        transcription_response_format: 转录响应格式（可选，默认使用配置中的格式）
        translation_model: 翻译使用的模型（可选，默认使用配置中的模型）
        translation_system_prompt: 翻译使用的系统提示词（可选，默认使用配置中的提示词）
        emo_control_method: 情感控制方式: 0-与音色相同, 1-情感参考音频, 2-情感向量, 3-情感文本
        emo_weight: 情感权重
        emo_text: 情感描述文本(当emo_control_method=3时使用)
        max_text_tokens_per_segment: 分句最大Token数
        temperature: 采样温度
        top_p: top_p采样
        top_k: top_k采样
        emo_audio_path: 情感参考音频文件路径（可选）
        
    Returns:
        包含任务ID列表的响应，每个任务对应一个音频段的克隆
        
    Raises:
        AudioTranslationCloneError: 如果处理失败
    """
    if not audio_file_path.exists():
        raise AudioTranslationCloneError(f"音频文件不存在: {audio_file_path}")
    
    if emo_audio_path and not emo_audio_path.exists():
        raise AudioTranslationCloneError(f"情感参考音频文件不存在: {emo_audio_path}")
    
    try:
        logger.info("步骤1: 开始音频转录...")
        transcription_result = await transcribe_audio(
            audio_file_path=audio_file_path,
            model=transcription_model,
            language=transcription_language,
            response_format=transcription_response_format,
        )
    except TranscriptionError as e:
        raise AudioTranslationCloneError(f"音频转录失败: {str(e)}")
    
    segments = transcription_result.get("segments", [])
    duration = transcription_result.get("duration", 0)
    
    if not segments:
        raise AudioTranslationCloneError("转录结果中 segments 为空，无法继续处理")
    
    if duration <= 0:
        raise AudioTranslationCloneError("转录结果中 duration 无效")
    
    logger.info("步骤2: 开始翻译文本...")
    translated_segments = []
    for idx, segment in enumerate(segments):
        segment_text = segment.get("text", "").strip()
        
        if not segment_text:
            translated_segments.append({
                **segment,
                "translated_text": None,
                "translation_error": None,
            })
            continue
        
        try:
            translation_result = await translate_text(
                text=segment_text,
                model=translation_model,
                system_prompt=translation_system_prompt,
            )
            
            translated_text = None
            if translation_result.get("choices") and len(translation_result["choices"]) > 0:
                message = translation_result["choices"][0].get("message", {})
                translated_text = message.get("content", "").strip()
            
            translated_segments.append({
                **segment,
                "translated_text": translated_text,
                "translation_error": None,
            })
        
        except TranslationError as e:
            translated_segments.append({
                **segment,
                "translated_text": None,
                "translation_error": str(e),
            })
    
    logger.debug("=" * 80)
    logger.debug("转录翻译完成，结果如下：")
    logger.debug("转录总文本: {}", transcription_result.get("text", ""))
    logger.debug("语言: {}, 时长: {:.2f}秒, 模型: {}", 
                transcription_result.get("language", ""),
                transcription_result.get("duration", 0),
                transcription_result.get("model", ""))
    logger.debug("总段数: {}, 已翻译段数: {}", 
                len(segments),
                len([s for s in translated_segments if s.get("translated_text")]))
    logger.debug("-" * 80)
    logger.debug("分段详情:")
    for idx, seg in enumerate(translated_segments, 1):
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        text = seg.get("text", "")
        translated_text = seg.get("translated_text", "")
        translation_error = seg.get("translation_error")
        
        logger.debug("  段 {}: [{:.2f} - {:.2f}]", idx, start, end)
        logger.debug("    原文: {}", text)
        if translated_text:
            logger.debug("    翻译: {}", translated_text)
        else:
            logger.debug("    翻译: (无) {}", f"错误: {translation_error}" if translation_error else "")
    logger.debug("=" * 80)
    
    try:
        logger.info("步骤3: 开始音频切分...")
        segmented_audio_paths = segment_audio(
            audio_file_path=audio_file_path,
            segments=segments,
            duration=duration,
        )
    except AudioSegmentationError as e:
        raise AudioTranslationCloneError(f"音频切分失败: {str(e)}")
    
    logger.info("步骤4: 开始音色克隆...")
    time_segments = _calculate_time_segments(segments, duration)
    
    sorted_segments = sorted(segments, key=lambda x: x.get("start", 0))
    sorted_translated_segments = sorted(translated_segments, key=lambda x: x.get("start", 0))
    
    translated_texts = []
    for seg in sorted_segments:
        seg_start = seg.get("start", 0)
        translated_seg = next(
            (s for s in sorted_translated_segments if abs(s.get("start", 0) - seg_start) < 0.01),
            None
        )
        translated_texts.append(translated_seg.get("translated_text", "") if translated_seg else "")
    
    last_end = sorted_segments[-1].get("end", 0) if sorted_segments else 0
    if last_end < duration:
        translated_texts.append("")
    
    task_results = []
    for idx, (segmented_audio_path, (start_time, end_time)) in enumerate(zip(segmented_audio_paths, time_segments)):
        translated_text = translated_texts[idx] if idx < len(translated_texts) else ""
        
        if not translated_text or not translated_text.strip():
            task_results.append({
                "segment_index": idx + 1,
                "time_range": f"{start_time:.2f}-{end_time:.2f}",
                "task_id": None,
                "error": "该音频段没有对应的翻译文本（尾段或空翻译）",
                "audio_path": str(segmented_audio_path),
            })
            continue
        
        try:
            result = await synthesize_audio_async(
                text=translated_text,
                prompt_audio_path=segmented_audio_path,
                emo_control_method=emo_control_method,
                emo_weight=emo_weight,
                emo_text=emo_text,
                max_text_tokens_per_segment=max_text_tokens_per_segment,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                emo_audio_path=emo_audio_path,
            )
            
            task_id = (
                result.get("task_id") or 
                result.get("taskId") or 
                result.get("id") or 
                result.get("task") or
                (result.get("data", {}).get("task_id") if isinstance(result.get("data"), dict) else None) or
                (result.get("data", {}).get("taskId") if isinstance(result.get("data"), dict) else None)
            )
            
            if not task_id:
                api_message = result.get("message") or result.get("error") or ""
                result_str = str(result)[:500]
                if api_message and "成功" in api_message:
                    error_msg = f"音色克隆API返回成功但task_id为空。响应内容: {result_str}"
                else:
                    error_msg = api_message or f"音色克隆API返回的task_id为空。响应内容: {result_str}"
                task_results.append({
                    "segment_index": idx + 1,
                    "time_range": f"{start_time:.2f}-{end_time:.2f}",
                    "task_id": None,
                    "translated_text": translated_text,
                    "error": error_msg,
                    "audio_path": str(segmented_audio_path),
                    "api_response": result,
                })
            else:
                task_results.append({
                    "segment_index": idx + 1,
                    "time_range": f"{start_time:.2f}-{end_time:.2f}",
                    "task_id": task_id,
                    "translated_text": translated_text,
                    "error": None,
                    "audio_path": str(segmented_audio_path),
                })
        
        except TTSError as e:
            task_results.append({
                "segment_index": idx + 1,
                "time_range": f"{start_time:.2f}-{end_time:.2f}",
                "task_id": None,
                "translated_text": translated_text,
                "error": f"音色克隆失败: {str(e)}",
                "audio_path": str(segmented_audio_path),
            })
        except Exception as e:
            task_results.append({
                "segment_index": idx + 1,
                "time_range": f"{start_time:.2f}-{end_time:.2f}",
                "task_id": None,
                "translated_text": translated_text,
                "error": f"音色克隆异常: {str(e)}",
                "audio_path": str(segmented_audio_path),
            })
    
    subtitle_segments = []
    for seg in sorted_translated_segments:
        start = float(seg.get("start", 0))
        end = float(seg.get("end", 0))
        translated_text = seg.get("translated_text")
        
        if end <= start:
            continue
        if not translated_text or not str(translated_text).strip():
            continue
        
        subtitle_segments.append({
            "start": start,
            "end": end,
            "text": seg.get("text", ""),
            "translated_text": translated_text,
            "translation_error": seg.get("translation_error"),
        })
    
    subtitle_segments.sort(key=lambda x: x.get("start", 0))
    
    logger.debug(
        "字幕段生成完成: 从 {} 个翻译段中提取了 {} 个字幕段（总转录段数: {}）",
        len(sorted_translated_segments),
        len(subtitle_segments),
        len(segments)
    )

    return {
        "message": "音频翻译克隆流程完成",
        "transcription": {
            "text": transcription_result.get("text"),
            "language": transcription_result.get("language"),
            "duration": transcription_result.get("duration"),
            "model": transcription_result.get("model"),
        },
        "total_segments": len(segments),
        "translated_segments": len([s for s in translated_segments if s.get("translated_text")]),
        "cloned_segments": len([r for r in task_results if r.get("task_id")]),
        "tasks": task_results,
        "subtitle_segments": subtitle_segments,
    }


async def _replace_video_audio(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Tuple[Path, float]:
    """
    使用 ffmpeg 将视频音轨替换为新的音频，确保音频长度与视频长度匹配。
    
    返回: (输出视频路径, 速度调整比例)
    速度调整比例 = 音频时长 / 视频时长
    """
    if not video_path.exists():
        raise VideoVoiceCloneError(f"视频文件不存在: {video_path}")
    if not audio_path.exists():
        raise VideoVoiceCloneError(f"音频文件不存在: {audio_path}")
    if not check_ffmpeg_available():
        raise VideoVoiceCloneError(f"FFmpeg 未安装或不可用。{get_ffmpeg_install_hint()}")

    try:
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
        
        logger.debug("视频时长: {:.2f}秒, 音频时长: {:.2f}秒", video_duration, audio_duration)
        
        video_input = ffmpeg.input(str(video_path))
        audio_input = ffmpeg.input(str(audio_path))
        
        if abs(audio_duration - video_duration) < 0.1:
            logger.debug("音频和视频时长匹配，无需调整")
            processed_audio = audio_input["a"]
            tempo_ratio = 1.0
        else:
            tempo_ratio = audio_duration / video_duration
            
            if tempo_ratio > 1.0:
                logger.debug("音频比视频长 {:.2f}秒，加速音频 {:.2f}x 倍", audio_duration - video_duration, tempo_ratio)
            else:
                logger.debug("音频比视频短 {:.2f}秒，减速音频 {:.2f}x 倍", video_duration - audio_duration, tempo_ratio)
            
            processed_audio = audio_input["a"]
            
            if tempo_ratio >= 0.5 and tempo_ratio <= 2.0:
                processed_audio = processed_audio.filter("atempo", tempo_ratio)
            elif tempo_ratio > 2.0:
                remaining = tempo_ratio
                while remaining > 2.0:
                    processed_audio = processed_audio.filter("atempo", 2.0)
                    remaining /= 2.0
                if abs(remaining - 1.0) > 0.01:
                    processed_audio = processed_audio.filter("atempo", remaining)
            else:
                remaining = tempo_ratio
                while remaining < 0.5:
                    processed_audio = processed_audio.filter("atempo", 0.5)
                    remaining /= 0.5
                if abs(remaining - 1.0) > 0.01:
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
        logger.debug("音轨替换完成 -> 输出: {}, 速度调整比例: {:.4f}", output_path, tempo_ratio)
        return output_path, tempo_ratio
    except ffmpeg.Error as e:
        detail = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"音频替换失败: {detail}")
        raise VideoVoiceCloneError(f"音频替换失败: {detail}")
    except Exception as e:
        if isinstance(e, VideoVoiceCloneError):
            raise
        logger.error(f"音频替换异常: {str(e)}")
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

    sorted_tasks = sorted(tasks, key=lambda x: x.get("segment_index", 0))

    clone_task_info = []
    tail_audio_tasks = []
    clone_failed_tasks = []
    
    for task in sorted_tasks:
        task_id = task.get("task_id")
        error = task.get("error") or ""
        audio_path_str = task.get("audio_path")
        translated_text = task.get("translated_text", "")
        seg_idx = task.get("segment_index", 0)

        if task_id:
            clone_task_info.append((task_id, seg_idx))
        elif "没有对应的翻译文本" in error or "尾段" in error:
            if audio_path_str:
                tail_audio_tasks.append((seg_idx, audio_path_str))
            else:
                logger.warning("尾段 segment_{} 没有 audio_path", seg_idx)
        elif translated_text and translated_text.strip():
            clone_failed_tasks.append((seg_idx, error or "克隆失败：未获取到 task_id"))
        elif audio_path_str:
            logger.warning("segment_{} 没有 task_id 也没有明确的错误信息，使用原始音频", seg_idx)
            tail_audio_tasks.append((seg_idx, audio_path_str))

    if clone_failed_tasks:
        failed_segments = [f"segment_{idx}: {err}" for idx, err in clone_failed_tasks]
        error_msg = f"以下音频段克隆失败，必须克隆成功才能继续：\n" + "\n".join(failed_segments)
        logger.error(error_msg)
        raise VideoVoiceCloneError(error_msg)

    logger.debug("开始收集克隆任务音频，克隆段数: {}, 尾段数: {}", len(clone_task_info), len(tail_audio_tasks))

    audio_files_dict = {}

    if clone_task_info:
        logger.debug("等待并下载克隆音频，轮询间隔: {:.1f}s，超时: {:.1f}s", query_interval, max_wait_time)
        cloned_audio_files = await wait_and_download_cloned_audios(
            task_info_list=clone_task_info,
            query_interval=query_interval,
            max_wait_time=max_wait_time,
        )
        if len(cloned_audio_files) != len(clone_task_info):
            missing_segments = [seg_idx for _, seg_idx in clone_task_info[len(cloned_audio_files):]]
            error_msg = f"克隆音频下载不完整：期望 {len(clone_task_info)} 个文件，实际下载 {len(cloned_audio_files)} 个。缺失的段: {missing_segments}"
            logger.error(error_msg)
            raise VideoVoiceCloneError(error_msg)
        
        for i, (task_id, seg_idx) in enumerate(clone_task_info):
            audio_files_dict[seg_idx] = cloned_audio_files[i]
            logger.debug("克隆音频 segment_{} -> {}", seg_idx, cloned_audio_files[i])

    for seg_idx, audio_path_str in tail_audio_tasks:
        audio_path = Path(audio_path_str)
        if audio_path.exists():
            audio_files_dict[seg_idx] = audio_path
            logger.debug("使用尾段原始音频 segment_{} -> {}", seg_idx, audio_path)
        else:
            logger.debug("下载尾段原始音频 segment_{}: {}", seg_idx, audio_path.name)
            downloaded = await download_segment_file(audio_path.name, base_url)
            audio_files_dict[seg_idx] = downloaded

    if not audio_files_dict:
        raise VideoVoiceCloneError("未获取到任何可用的克隆/原始音频文件")

    sorted_segments = sorted(audio_files_dict.keys())
    cloned_audio_files = [audio_files_dict[idx] for idx in sorted_segments]

    try:
        logger.debug("开始合并 {} 段音频（按 segment_index 顺序）", len(cloned_audio_files))
        merged_audio_path = await merge_audio_files(cloned_audio_files)
        logger.debug("音频合并完成 -> {}", merged_audio_path)
    except AudioMergeError as e:
        raise VideoVoiceCloneError(str(e))

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
        logger.info("步骤1: 提取视频音频 -> {}", temp_audio_path)
        await asyncio.to_thread(extract_audio, video_path, temp_audio_path)

        logger.info("步骤2: 调用音频翻译克隆流程（仅替换音轨）")
        clone_result = await process_audio_translation_clone(audio_file_path=temp_audio_path)
        logger.info("克隆任务数: {}", len(clone_result.get("tasks", [])))

        logger.info("步骤3: 下载并合并克隆音频（仅替换音轨）")
        merged_audio_path = await _collect_and_merge_clone_audios(
            clone_result=clone_result,
            query_interval=query_interval,
            max_wait_time=max_wait_time,
            base_url=base_url,
        )

        logger.info("步骤4: 替换视频音轨（不裁剪，不叠字幕）")
        _, tempo_ratio = await _replace_video_audio(video_path, merged_audio_path, final_video_path)

        logger.info("流程完成，输出视频: {}", final_video_path)
        return {
            "video_path": final_video_path,
            "clone_result": clone_result,
        }

    except (AudioExtractionError, AudioTranslationCloneError) as e:
        raise VideoVoiceCloneError(str(e))
    except VideoVoiceCloneError:
        raise
    except Exception as e:
        logger.error(f"处理失败: {str(e)}")
        raise VideoVoiceCloneError(f"处理失败: {str(e)}")
    finally:
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
    
    流程说明：
    1. 先叠加字幕到原始视频（使用原始字幕时间，基于转录翻译返回的时间）
    2. 替换音轨并调整速度（如果音频和视频时长不匹配，音频会被加速/减速以匹配视频时长）
    3. 字幕时间保持原始时间不变（因为音频被调整以匹配视频时长，视频时长保持不变）
    4. 裁剪视频
    5. 重新叠加字幕（使用原始字幕时间）

    返回最终视频路径及字幕数据（字幕时间与原始时间相同）。
    """
    if not video_path.exists():
        raise VideoVoiceCloneError(f"视频文件不存在: {video_path}")

    temp_audio_path = Path(tempfile.gettempdir()) / f"{uuid.uuid4().hex}.wav"
    subtitled_video_path = OUTPUT_DIR / f"subtitled_{uuid.uuid4().hex}{video_path.suffix}"
    replaced_video_path = OUTPUT_DIR / f"voice_replaced_{uuid.uuid4().hex}{video_path.suffix}"
    cropped_video_path = OUTPUT_DIR / f"cropped_{uuid.uuid4().hex}{video_path.suffix}"
    final_video_path = OUTPUT_DIR / f"voice_clone_overlay_{uuid.uuid4().hex}{video_path.suffix}"

    try:
        logger.info("步骤1: 提取视频音频 -> {}", temp_audio_path)
        await asyncio.to_thread(extract_audio, video_path, temp_audio_path)

        logger.info("步骤2: 调用音频翻译克隆流程（转录+翻译）")
        clone_result = await process_audio_translation_clone(audio_file_path=temp_audio_path)
        original_subtitle_segments = clone_result.get("subtitle_segments", [])
        logger.info("步骤2完成: 克隆任务数: {}，字幕段数: {}", len(clone_result.get("tasks", [])), len(original_subtitle_segments))
        
        logger.debug("字幕段详情:")
        for idx, seg in enumerate(original_subtitle_segments, 1):
            logger.debug("  字幕段 {}: [{:.2f} - {:.2f}] {}", 
                       idx, seg.get("start", 0), seg.get("end", 0), seg.get("translated_text", ""))

        logger.info("步骤3: 下载并合并克隆音频")
        merged_audio_path = await _collect_and_merge_clone_audios(
            clone_result=clone_result,
            query_interval=query_interval,
            max_wait_time=max_wait_time,
            base_url=base_url,
        )

        logger.info("步骤4: 先叠加字幕到原始视频（使用原始字幕时间）")
        await asyncio.to_thread(
            overlay_title_and_subtitles,
            video_path,
            subtitled_video_path,
            title_text,
            original_subtitle_segments,
            title_block_height,
            subtitle_block_height,
            title_font_size,
            subtitle_font_size,
            fontfile,
        )

        logger.info("步骤5: 替换视频音轨（在已叠加字幕的视频上）")
        _, tempo_ratio = await _replace_video_audio(subtitled_video_path, merged_audio_path, replaced_video_path)

        logger.info("步骤6: 音频已调整以匹配视频时长，字幕时间保持原始时间不变")
        adjusted_subtitle_segments = original_subtitle_segments
        logger.debug("保持原字幕段数: {}", len(adjusted_subtitle_segments))

        logger.info("步骤7: 固定裁剪视频 top={} bottom={}", top_cut, bottom_cut)
        await asyncio.to_thread(
            detect_and_crop_video,
            replaced_video_path,
            cropped_video_path,
            top_cut,
            bottom_cut,
        )

        logger.info("步骤8: 重新叠加标题与字幕（使用原始字幕时间），标题: {}", title_text)
        await asyncio.to_thread(
            overlay_title_and_subtitles,
            cropped_video_path,
            final_video_path,
            title_text,
            adjusted_subtitle_segments,
            title_block_height,
            subtitle_block_height,
            title_font_size,
            subtitle_font_size,
            fontfile,
        )

        logger.info("流程完成，输出视频: {}", final_video_path)
        return {
            "video_path": final_video_path,
            "subtitle_segments": adjusted_subtitle_segments,
            "original_subtitle_segments": original_subtitle_segments,
            "tempo_ratio": tempo_ratio,
            "clone_result": clone_result,
        }

    except (AudioExtractionError, AudioTranslationCloneError, VideoCropError, VideoOverlayError) as e:
        raise VideoVoiceCloneError(str(e))
    except VideoVoiceCloneError:
        raise
    except Exception as e:
        logger.error(f"处理失败: {str(e)}")
        raise VideoVoiceCloneError(f"处理失败: {str(e)}")
    finally:
        for path in [
            temp_audio_path,
            merged_audio_path if "merged_audio_path" in locals() else None,
            subtitled_video_path if subtitled_video_path.exists() and final_video_path != subtitled_video_path else None,
            replaced_video_path if replaced_video_path.exists() and final_video_path != replaced_video_path else None,
            cropped_video_path if cropped_video_path.exists() and final_video_path != cropped_video_path else None,
        ]:
            if path and path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass


async def merge_cloned_audios(
    audio_file_path: Path,
    transcription_model: Optional[str] = None,
    transcription_language: Optional[str] = None,
    transcription_response_format: Optional[str] = None,
    translation_model: Optional[str] = None,
    translation_system_prompt: Optional[str] = None,
    emo_control_method: int = 0,
    emo_weight: float = 0.65,
    emo_text: str = "",
    max_text_tokens_per_segment: int = 120,
    temperature: float = 0.8,
    top_p: float = 0.8,
    top_k: int = 30,
    emo_audio_path: Optional[Path] = None,
    query_interval: float = 2.0,
    max_wait_time: float = 300.0,
    base_url: str = "http://localhost:8000",
) -> Path:
    """
    音频翻译克隆并合并完整流程
    
    流程：
    1. 调用音频翻译克隆接口，得到任务ID和最后一段音频路径
    2. 查询所有克隆任务状态，等待完成
    3. 下载所有克隆后的音频
    4. 下载最后一段音频（没有克隆的）
    5. 合并所有音频，返回合并后的音频文件
    
    Args:
        audio_file_path: 要处理的音频文件路径
        transcription_model: 转录使用的模型（可选）
        transcription_language: 转录使用的语言代码（可选）
        transcription_response_format: 转录响应格式（可选）
        translation_model: 翻译使用的模型（可选）
        translation_system_prompt: 翻译使用的系统提示词（可选）
        emo_control_method: 情感控制方式
        emo_weight: 情感权重
        emo_text: 情感描述文本
        max_text_tokens_per_segment: 分句最大Token数
        temperature: 采样温度
        top_p: top_p采样
        top_k: top_k采样
        emo_audio_path: 情感参考音频文件路径（可选）
        query_interval: 查询任务状态的间隔时间（秒）
        max_wait_time: 最大等待时间（秒）
        base_url: API 基础URL
        
    Returns:
        合并后的音频文件路径
        
    Raises:
        AudioMergeError: 如果处理失败
    """
    if not audio_file_path.exists():
        raise AudioMergeError(f"音频文件不存在: {audio_file_path}")
    
    if not check_ffmpeg_available():
        raise AudioMergeError(
            f"FFmpeg 未安装或不在系统 PATH 中。{get_ffmpeg_install_hint()}"
        )
    
    try:
        logger.info("步骤1: 开始调用音频翻译克隆接口...")
        clone_result = await process_audio_translation_clone(
            audio_file_path=audio_file_path,
            transcription_model=transcription_model,
            transcription_language=transcription_language,
            transcription_response_format=transcription_response_format,
            translation_model=translation_model,
            translation_system_prompt=translation_system_prompt,
            emo_control_method=emo_control_method,
            emo_weight=emo_weight,
            emo_text=emo_text,
            max_text_tokens_per_segment=max_text_tokens_per_segment,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            emo_audio_path=emo_audio_path,
        )
        logger.info(f"步骤1完成: 生成了 {len(clone_result.get('tasks', []))} 个任务")
        
        tasks = clone_result.get("tasks", [])
        if not tasks:
            raise AudioMergeError("没有生成任何克隆任务")
        
        sorted_tasks = sorted(tasks, key=lambda x: x.get("segment_index", 0))
        
        task_info_list = []
        last_segment_path = None
        
        for task in sorted_tasks:
            task_id = task.get("task_id")
            segment_index = task.get("segment_index", 0)
            
            if task_id:
                task_info_list.append((task_id, segment_index))
                logger.info(f"任务 {segment_index}: task_id={task_id}")
            
            if task.get("error") == "该音频段没有对应的翻译文本":
                audio_path = task.get("audio_path", "")
                if audio_path:
                    last_segment_path = audio_path
                    logger.info(f"最后一段音频: {audio_path}")
        
        if not task_info_list:
            raise AudioMergeError("没有有效的任务ID")
        
        logger.info(f"步骤2: 开始查询 {len(task_info_list)} 个克隆任务状态...")
        cloned_audio_files = await wait_and_download_cloned_audios(
            task_info_list=task_info_list,
            query_interval=query_interval,
            max_wait_time=max_wait_time,
        )
        logger.info(f"步骤2完成: 成功下载 {len(cloned_audio_files)} 个克隆音频文件")
        
        if last_segment_path:
            logger.info("步骤3: 开始下载最后一段音频...")
            filename = Path(last_segment_path).name
            logger.info(f"文件名: {filename}")
            last_segment_file = await download_segment_file(filename, base_url)
            cloned_audio_files.append(last_segment_file)
            logger.info("步骤3完成: 最后一段音频已下载")
        
        logger.info(f"步骤4: 开始合并 {len(cloned_audio_files)} 个音频文件...")
        merged_audio_path = await merge_audio_files(cloned_audio_files)
        logger.info(f"步骤4完成: 音频合并完成，输出文件: {merged_audio_path}")
        
        # 清理临时文件
        for temp_file in cloned_audio_files:
            if temp_file.exists() and temp_file != merged_audio_path:
                try:
                    temp_file.unlink()
                except Exception:
                    pass
        
        return merged_audio_path
    
    except AudioTranslationCloneError as e:
        raise AudioMergeError(f"音频翻译克隆失败: {str(e)}")
    except Exception as e:
        if isinstance(e, AudioMergeError):
            raise
        logger.error(f"音频合并流程异常: {str(e)}")
        raise AudioMergeError(f"音频合并失败: {str(e)}")

