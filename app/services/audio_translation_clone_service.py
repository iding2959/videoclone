"""
音频翻译克隆服务
整合音频转录、翻译、切分和音色克隆的完整流程
"""
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.services.transcription_service import transcribe_audio, TranscriptionError
from app.services.translation_service import translate_text, TranslationError
from app.services.audio_segmentation_service import segment_audio, AudioSegmentationError
from app.services.tts_service import synthesize_audio_async, TTSError


class AudioTranslationCloneError(Exception):
    """音频翻译克隆错误"""
    pass


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
    
    # 步骤1: 音频转录
    try:
        transcription_result = await transcribe_audio(
            audio_file_path=audio_file_path,
            model=transcription_model,
            language=transcription_language,
            response_format=transcription_response_format,
        )
    except TranscriptionError as e:
        raise AudioTranslationCloneError(f"音频转录失败: {str(e)}")
    
    # 提取 segments 和 duration
    segments = transcription_result.get("segments", [])
    duration = transcription_result.get("duration", 0)
    
    if not segments:
        raise AudioTranslationCloneError("转录结果中 segments 为空，无法继续处理")
    
    if duration <= 0:
        raise AudioTranslationCloneError("转录结果中 duration 无效")
    
    # 步骤2: 翻译每个 segment 的文本
    translated_segments = []
    for idx, segment in enumerate(segments):
        segment_text = segment.get("text", "").strip()
        
        if not segment_text:
            # 如果 segment 没有文本，保留原始 segment，不添加翻译
            translated_segments.append({
                **segment,
                "translated_text": None,
                "translation_error": None,
            })
            continue
        
        try:
            # 调用翻译服务
            translation_result = await translate_text(
                text=segment_text,
                model=translation_model,
                system_prompt=translation_system_prompt,
            )
            
            # 从翻译结果中提取翻译文本
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
            # 翻译失败时，保留原始 segment，记录错误
            translated_segments.append({
                **segment,
                "translated_text": None,
                "translation_error": str(e),
            })
    
    # 步骤3: 音频切分
    try:
        segmented_audio_paths = segment_audio(
            audio_file_path=audio_file_path,
            segments=segments,
            duration=duration,
        )
    except AudioSegmentationError as e:
        raise AudioTranslationCloneError(f"音频切分失败: {str(e)}")
    
    # 步骤4: 对每个切分后的音频段进行音色克隆
    # 计算切分时间段（按转录段逐段 + 尾段）
    time_segments = _calculate_time_segments(segments, duration)
    
    # 按 start 时间排序 segments 和 translated_segments
    sorted_segments = sorted(segments, key=lambda x: x.get("start", 0))
    sorted_translated_segments = sorted(translated_segments, key=lambda x: x.get("start", 0))
    
    # 为每个时间段准备翻译文本：转录段有翻译，尾段无翻译
    translated_texts = []
    for seg in sorted_segments:
        seg_start = seg.get("start", 0)
        translated_seg = next(
            (s for s in sorted_translated_segments if abs(s.get("start", 0) - seg_start) < 0.01),
            None
        )
        translated_texts.append(translated_seg.get("translated_text", "") if translated_seg else "")
    
    # 尾段（原始音频，不克隆）追加空翻译文本
    last_end = sorted_segments[-1].get("end", 0) if sorted_segments else 0
    if last_end < duration:
        translated_texts.append("")
    
    task_results = []
    for idx, (segmented_audio_path, (start_time, end_time)) in enumerate(zip(segmented_audio_paths, time_segments)):
        # 获取对应的翻译文本
        translated_text = translated_texts[idx] if idx < len(translated_texts) else ""
        
        # 如果没有翻译文本（尾段或空段），跳过克隆，仅返回原始音频路径
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
            # 使用切分后的音频段本身作为音色参考
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
            
            # 尝试从不同可能的字段名中提取 task_id
            task_id = (
                result.get("task_id") or 
                result.get("taskId") or 
                result.get("id") or 
                result.get("task") or
                (result.get("data", {}).get("task_id") if isinstance(result.get("data"), dict) else None) or
                (result.get("data", {}).get("taskId") if isinstance(result.get("data"), dict) else None)
            )
            
            if not task_id:
                # 如果 task_id 为空，记录完整的响应信息以便调试
                api_message = result.get("message") or result.get("error") or ""
                # 记录完整的响应（但限制长度，避免日志过大）
                result_str = str(result)[:500]  # 只记录前500个字符
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
                    "api_response": result,  # 添加完整响应以便调试
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
    
    # 准备用于字幕的数据，保持时间轴顺序
    subtitle_segments = []
    for seg in sorted_translated_segments:
        start = float(seg.get("start", 0))
        end = float(seg.get("end", 0))
        translated_text = seg.get("translated_text")
        # 仅当有有效翻译文本时才用于字幕，避免空字幕
        if end <= start or not translated_text or not str(translated_text).strip():
            continue
        subtitle_segments.append({
            "start": start,
            "end": end,
            "text": seg.get("text", ""),
            "translated_text": translated_text,
            "translation_error": seg.get("translation_error"),
        })

    # 返回结果
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


def _calculate_time_segments(
    segments: List[Dict[str, Any]],
    duration: float
) -> List[tuple]:
    """
    计算切分时间段：逐段(start,end) + 尾段。
    尾段用于保留原始音频，不进行克隆。
    """
    time_segments = []
    
    if not segments:
        return time_segments
    
    sorted_segments = sorted(segments, key=lambda x: x.get("start", 0))
    
    # 逐段
    for seg in sorted_segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        if seg_end <= seg_start:
            continue
        time_segments.append((float(seg_start), float(seg_end)))
    
    # 尾段
    last_end = sorted_segments[-1].get("end", 0)
    if last_end < duration:
        time_segments.append((float(last_end), float(duration)))
    
    return time_segments

