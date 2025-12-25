# 服务层文档

本目录包含项目的核心业务逻辑服务模块，按照功能类型进行了整合和分类。

## 目录结构

```
app/services/
├── __init__.py                    # 服务模块导出
├── audio_processing_service.py    # 音频处理服务
├── text_processing_service.py     # 文本处理服务
├── video_processing_service.py    # 视频处理服务
└── workflow_service.py            # 工作流服务
```

## 服务模块说明

### 1. audio_processing_service.py - 音频处理服务

**功能描述**：整合音频提取、切分、合并等基础音频处理功能。

**主要功能**：
- 从视频中提取音频
- 根据时间段切分音频文件
- 合并多个音频文件
- 等待并下载克隆音频
- 下载切分的音频段文件

**主要函数**：

| 函数名 | 类型 | 说明 |
|--------|------|------|
| `extract_audio()` | 同步 | 从视频文件中提取音频，输出为 WAV 格式 |
| `segment_audio()` | 同步 | 根据转录结果的 segments 切分音频文件 |
| `merge_audio_files()` | 异步 | 合并多个音频文件为一个完整音频 |
| `wait_and_download_cloned_audios()` | 异步 | 等待克隆任务完成并下载音频文件 |
| `download_segment_file()` | 异步 | 从服务器下载切分的音频文件 |

**异常类**：
- `AudioProcessingError` - 音频处理错误基类
- `AudioExtractionError` - 音频提取错误
- `AudioSegmentationError` - 音频切分错误
- `AudioMergeError` - 音频合并错误

**使用示例**：
```python
from app.services.audio_processing_service import extract_audio, segment_audio, merge_audio_files

# 提取音频
audio_path = extract_audio(video_path, output_audio_path)

# 切分音频
segments = [{"start": 0, "end": 5.0}, {"start": 5.0, "end": 10.0}]
segmented_paths = segment_audio(audio_path, segments, duration=10.0)

# 合并音频
merged_path = await merge_audio_files(segmented_paths)
```

**依赖**：
- `ffmpeg` - 音频处理
- `httpx` - HTTP 请求
- `app.services.text_processing_service` - 查询任务状态和下载音频

---

### 2. text_processing_service.py - 文本处理服务

**功能描述**：整合音频转录、文本翻译、语音合成等文本和语音处理功能。

**主要功能**：
- 音频转录为文本
- 文本翻译
- 语音合成（TTS）
- 查询 TTS 任务状态
- 下载生成的音频文件

**主要函数**：

| 函数名 | 类型 | 说明 |
|--------|------|------|
| `transcribe_audio()` | 异步 | 调用音频转录 API，将音频转换为文本 |
| `translate_text()` | 异步 | 调用翻译 API，翻译文本内容 |
| `synthesize_audio_async()` | 异步 | 提交异步语音合成任务，返回 task_id |
| `query_task_status()` | 异步 | 查询 TTS 任务状态和结果 |
| `download_audio_file()` | 异步 | 从 TTS 服务器下载生成的音频文件 |
| `get_audio_media_type()` | 同步 | 根据文件扩展名返回 MIME 类型 |

**异常类**：
- `TextProcessingError` - 文本处理错误基类
- `TranscriptionError` - 音频转录错误
- `TranslationError` - 翻译错误
- `TTSError` - TTS 服务错误（包含状态码）

**使用示例**：
```python
from app.services.text_processing_service import (
    transcribe_audio, translate_text, synthesize_audio_async
)

# 转录音频
transcription_result = await transcribe_audio(audio_path)

# 翻译文本
translation_result = await translate_text("Hello, world!")

# 语音合成
tts_result = await synthesize_audio_async(
    text="Hello, world!",
    prompt_audio_path=reference_audio_path
)
```

**配置依赖**：
- `TRANSCRIPTION_API_URL` - 转录 API 地址
- `TRANSLATION_API_URL` - 翻译 API 地址
- `TTS_SYNTHESIZE_ASYNC_URL` - TTS 合成 API 地址
- `TTS_TASK_QUERY_URL` - TTS 任务查询 API 地址
- `TTS_DOWNLOAD_URL` - TTS 音频下载 API 地址

---

### 3. video_processing_service.py - 视频处理服务

**功能描述**：整合视频裁剪、文字叠加等视频处理功能。

**主要功能**：
- 自动检测并裁剪视频（去除顶部标题和底部字幕区域）
- 手动指定裁剪区域
- 在视频上叠加标题和字幕
- 文本自动换行处理

**主要函数**：

| 函数名 | 类型 | 说明 |
|--------|------|------|
| `detect_and_crop_video()` | 同步 | 检测并裁剪视频顶部和底部区域，支持自动检测或手动指定 |
| `overlay_title_and_subtitles()` | 同步 | 在视频上叠加标题（全程显示）和分段字幕（按时间显示） |
| `_sample_frames()` | 私有 | 均匀采样视频帧用于分析 |
| `_compute_horizontal_energy()` | 私有 | 计算水平能量用于检测标题和字幕区域 |
| `_find_bands()` | 私有 | 根据能量分析找到需要裁剪的区域 |
| `_wrap_text()` | 私有 | 文本自动换行处理 |

**异常类**：
- `VideoProcessingError` - 视频处理错误基类
- `VideoCropError` - 视频裁剪错误
- `VideoOverlayError` - 视频叠加错误

**使用示例**：
```python
from app.services.video_processing_service import (
    detect_and_crop_video, overlay_title_and_subtitles
)

# 自动检测并裁剪
cropped_path = detect_and_crop_video(video_path)

# 手动指定裁剪区域
cropped_path = detect_and_crop_video(
    video_path, 
    output_path=output_path,
    top_cut=390,
    bottom_cut=430
)

# 叠加标题和字幕
subtitle_segments = [
    {"start": 0.0, "end": 5.0, "translated_text": "Hello"},
    {"start": 5.0, "end": 10.0, "translated_text": "World"}
]
overlayed_path = overlay_title_and_subtitles(
    video_path,
    output_path,
    title_text="My Video",
    subtitle_segments=subtitle_segments,
    title_block_height=120,
    subtitle_block_height=160
)
```

**依赖**：
- `ffmpeg` - 视频处理
- `cv2` (OpenCV) - 视频帧分析和处理
- `numpy` - 数值计算

---

### 4. workflow_service.py - 工作流服务

**功能描述**：整合音频翻译克隆和视频音色克隆的完整业务流程。

**主要功能**：
- 音频翻译克隆完整流程（转录 → 翻译 → 切分 → 音色克隆）
- 视频音色克隆完整流程（提取音频 → 翻译克隆 → 替换音轨 → 裁剪 → 叠加字幕）
- 仅替换视频音轨（不裁剪、不叠加字幕）
- 音频翻译克隆并合并

**主要函数**：

| 函数名 | 类型 | 说明 |
|--------|------|------|
| `process_audio_translation_clone()` | 异步 | 音频翻译克隆完整流程，返回任务列表和字幕段 |
| `process_video_voice_clone()` | 异步 | 视频音色克隆完整流程（包含裁剪和字幕叠加） |
| `process_video_voice_clone_audio_only()` | 异步 | 仅替换视频音轨，不裁剪、不叠加字幕 |
| `merge_cloned_audios()` | 异步 | 音频翻译克隆并合并完整流程 |
| `_replace_video_audio()` | 异步 | 替换视频音轨，自动调整音频速度以匹配视频时长 |
| `_collect_and_merge_clone_audios()` | 异步 | 收集并合并克隆音频（内部函数） |
| `_calculate_time_segments()` | 私有 | 计算音频切分时间段 |

**异常类**：
- `WorkflowError` - 工作流错误基类
- `AudioTranslationCloneError` - 音频翻译克隆错误
- `VideoVoiceCloneError` - 视频音色克隆错误

**使用示例**：
```python
from app.services.workflow_service import (
    process_audio_translation_clone,
    process_video_voice_clone
)

# 音频翻译克隆
result = await process_audio_translation_clone(
    audio_file_path=audio_path,
    transcription_model="Faster-Whisper-Large-V3",
    translation_model="Hunyuan-MT-Chimera-7B"
)
tasks = result["tasks"]  # 获取克隆任务列表
subtitle_segments = result["subtitle_segments"]  # 获取字幕段

# 视频音色克隆完整流程
result = await process_video_voice_clone(
    video_path=video_path,
    title_text="My Video Title",
    top_cut=390,
    bottom_cut=430
)
final_video = result["video_path"]  # 最终视频路径
```

**流程说明**：

1. **音频翻译克隆流程**：
   - 音频转录 → 文本翻译 → 音频切分 → 音色克隆（每个音频段）

2. **视频音色克隆完整流程**：
   - 提取视频音频
   - 调用音频翻译克隆流程
   - 下载并合并克隆音频
   - 叠加字幕到原始视频
   - 替换视频音轨（自动调整速度）
   - 裁剪视频
   - 重新叠加字幕

3. **仅替换音轨流程**：
   - 提取视频音频
   - 调用音频翻译克隆流程
   - 下载并合并克隆音频
   - 替换视频音轨

**依赖**：
- `app.services.audio_processing_service` - 音频处理
- `app.services.text_processing_service` - 文本处理
- `app.services.video_processing_service` - 视频处理

---

## 服务模块关系图

```
workflow_service.py (工作流服务)
    ├── audio_processing_service.py (音频处理)
    │   └── text_processing_service.py (文本处理 - 查询任务)
    ├── text_processing_service.py (文本处理)
    └── video_processing_service.py (视频处理)
```

## 日志系统

所有服务统一使用 `loguru` 日志系统（通过 `app.utils.logger`），日志配置：
- 控制台输出：INFO 级别
- 文件输出：DEBUG 级别
- 日志文件：按日期切分，保留 30 天

使用方式：
```python
from app.utils.logger import logger

logger.info("处理开始")
logger.error("处理失败")
logger.debug("调试信息")
```

## 错误处理

所有服务都定义了相应的异常类，采用分层异常设计：
- 基类异常（如 `AudioProcessingError`）
- 具体异常（如 `AudioExtractionError`）

建议在调用服务时捕获具体异常，以便进行精确的错误处理。

## 注意事项

1. **循环导入**：已解决 `audio_processing_service` 和 `workflow_service` 之间的循环导入问题，`merge_cloned_audios` 函数已移至 `workflow_service`。

2. **异步函数**：大部分涉及网络请求的函数都是异步的，需要使用 `await` 调用。

3. **文件路径**：所有函数都使用 `pathlib.Path` 类型处理文件路径，确保跨平台兼容性。

4. **临时文件清理**：工作流函数会自动清理临时文件，但建议在调用后也进行清理。

5. **FFmpeg 依赖**：音频和视频处理功能需要系统安装 FFmpeg，函数会自动检查并提示。

## 更新日志

- **2025-12-25**: 整合服务层代码，统一日志系统，解决循环导入问题
  - 整合音频处理服务（提取、切分、合并）
  - 整合文本处理服务（转录、翻译、TTS）
  - 整合视频处理服务（裁剪、叠加）
  - 整合工作流服务（完整业务流程）

