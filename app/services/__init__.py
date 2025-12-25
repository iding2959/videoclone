"""
业务逻辑服务模块
"""
from app.services.audio_processing_service import (
    extract_audio,
    segment_audio,
    merge_audio_files,
    wait_and_download_cloned_audios,
    download_segment_file,
    AudioExtractionError,
    AudioSegmentationError,
    AudioMergeError,
    AudioProcessingError,
)
from app.services.text_processing_service import (
    transcribe_audio,
    translate_text,
    synthesize_audio_async,
    query_task_status,
    download_audio_file,
    TranscriptionError,
    TranslationError,
    TTSError,
    TextProcessingError,
)
from app.services.video_processing_service import (
    detect_and_crop_video,
    overlay_title_and_subtitles,
    VideoCropError,
    VideoOverlayError,
    VideoProcessingError,
)
from app.services.workflow_service import (
    process_audio_translation_clone,
    process_video_voice_clone,
    process_video_voice_clone_audio_only,
    merge_cloned_audios,
    AudioTranslationCloneError,
    VideoVoiceCloneError,
    WorkflowError,
)

__all__ = [
    # 音频处理
    "extract_audio",
    "segment_audio",
    "merge_audio_files",
    "wait_and_download_cloned_audios",
    "download_segment_file",
    "AudioExtractionError",
    "AudioSegmentationError",
    "AudioMergeError",
    "AudioProcessingError",
    # 文本处理
    "transcribe_audio",
    "translate_text",
    "synthesize_audio_async",
    "query_task_status",
    "download_audio_file",
    "TranscriptionError",
    "TranslationError",
    "TTSError",
    "TextProcessingError",
    # 视频处理
    "detect_and_crop_video",
    "overlay_title_and_subtitles",
    "VideoCropError",
    "VideoOverlayError",
    "VideoProcessingError",
    # 工作流
    "process_audio_translation_clone",
    "process_video_voice_clone",
    "process_video_voice_clone_audio_only",
    "merge_cloned_audios",
    "AudioTranslationCloneError",
    "VideoVoiceCloneError",
    "WorkflowError",
]
