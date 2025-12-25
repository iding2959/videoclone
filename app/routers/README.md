# 路由层文档

本文档描述了路由层的组织结构和使用说明。

## 目录结构

路由层按功能类型进行了模块化组织，每个模块包含相关的路由端点：

```
app/routers/
├── __init__.py          # 路由模块初始化
├── base.py              # 基础路由（根路径、健康检查）
├── audio_basic.py       # 音频基础处理（提取、转录、切分）
├── audio_clone.py       # 音频克隆（TTS 音色克隆）
├── audio_workflow.py    # 音频工作流（翻译克隆、合并）
├── text.py              # 文本处理（翻译）
├── video.py             # 视频处理（裁剪、叠加、音色克隆）
└── README.md           # 本文档
```

## 路由模块说明

### 1. base.py - 基础路由

提供应用的基础功能路由。

#### 路由端点

- `GET /` - 根路径，返回服务信息和可用端点
- `GET /health` - 健康检查，检查服务状态和 FFmpeg 可用性

---

### 2. audio_basic.py - 音频基础处理

提供音频的基础处理功能，包括音频提取、转录和切分。

#### 路由端点

- `POST /extract` - 从视频文件提取音频
  - 参数：`file` (视频文件)
  - 返回：提取的音频文件（WAV格式）

- `POST /transcribe` - 音频转录
  - 参数：`file` (音频文件), `model` (可选), `language` (可选), `response_format` (可选)
  - 返回：转录结果（JSON）

- `POST /segment` - 音频切分
  - 参数：`file` (音频文件), `transcription_result` (可选), `model` (可选), `language` (可选), `response_format` (可选), `download` (可选)
  - 返回：切分后的音频文件信息或 ZIP 压缩包

- `GET /segment/download/{filename}` - 下载单个切分后的音频文件
  - 参数：`filename` (文件名)
  - 返回：音频文件

- `POST /segment/download` - 下载多个切分后的音频文件（打包成 ZIP）
  - 参数：`file_paths` (文件路径列表的 JSON 字符串)
  - 返回：ZIP 压缩包文件

- `POST /transcribe-and-translate` - 音频转录并翻译
  - 参数：`file` (音频文件), `transcription_model` (可选), `transcription_language` (可选), `transcription_response_format` (可选), `translation_model` (可选), `translation_system_prompt` (可选)
  - 返回：包含转录结果和按段翻译结果的字典

---

### 3. audio_clone.py - 音频克隆

提供 TTS 音色克隆相关功能。

#### 路由端点

- `POST /api/tts/synthesize-async` - 异步语音合成
  - 参数：`text` (要合成的文本), `prompt_audio` (音色参考音频), `emo_control_method` (情感控制方式), `emo_weight` (情感权重), `emo_text` (情感描述文本), `max_text_tokens_per_segment` (分句最大Token数), `temperature` (采样温度), `top_p` (top_p采样), `top_k` (top_k采样), `emo_audio` (可选，情感参考音频)
  - 返回：包含 `task_id` 的响应

- `GET /api/tts/task/{task_id}` - 查询 TTS 任务状态
  - 参数：`task_id` (任务ID)
  - 返回：任务状态和结果

- `GET /api/tts/download/{filename}` - 下载生成的音频文件
  - 参数：`filename` (音频文件名)
  - 返回：音频文件

---

### 4. audio_workflow.py - 音频工作流

提供音频翻译克隆和合并等完整工作流功能。

#### 路由端点

- `POST /api/audio/translation-clone` - 音频翻译克隆完整流程
  - 参数：`audio_file` (音频文件), `transcription_model` (可选), `transcription_language` (可选), `transcription_response_format` (可选), `translation_model` (可选), `translation_system_prompt` (可选), `emo_control_method` (情感控制方式), `emo_weight` (情感权重), `emo_text` (情感描述文本), `max_text_tokens_per_segment` (分句最大Token数), `temperature` (采样温度), `top_p` (top_p采样), `top_k` (top_k采样), `emo_audio` (可选)
  - 返回：包含任务ID列表的响应

- `POST /api/audio/translation-clone/query-tasks` - 批量查询音色克隆任务状态
  - 参数：`request` (包含 `tasks`、`task_ids` 或 `task_id` 的请求体)
  - 返回：包含所有任务状态和结果的字典

- `GET /api/audio/translation-clone/task/{task_id}` - 查询单个音色克隆任务状态
  - 参数：`task_id` (任务ID)
  - 返回：任务状态和结果

- `POST /api/audio/merge-cloned` - 音频翻译克隆并合并完整流程
  - 参数：`audio_file` (音频文件), `transcription_model` (可选), `transcription_language` (可选), `transcription_response_format` (可选), `translation_model` (可选), `translation_system_prompt` (可选), `emo_control_method` (情感控制方式), `emo_weight` (情感权重), `emo_text` (情感描述文本), `max_text_tokens_per_segment` (分句最大Token数), `temperature` (采样温度), `top_p` (top_p采样), `top_k` (top_k采样), `emo_audio` (可选), `query_interval` (查询间隔), `max_wait_time` (最大等待时间), `base_url` (API基础URL)
  - 返回：合并后的音频文件（WAV格式）

---

### 5. text.py - 文本处理

提供文本翻译功能。

#### 路由端点

- `POST /translate` - 翻译文本
  - 参数：`request` (包含 `text`、`model` (可选)、`system_prompt` (可选) 的请求体)
  - 返回：翻译结果（完整的 chat completion 响应）

---

### 6. video.py - 视频处理

提供视频处理功能，包括裁剪、叠加字幕和音色克隆。

#### 路由端点

- `POST /video/crop` - 视频裁剪
  - 参数：`file` (视频文件), `top_cut` (顶部裁剪像素数，默认0), `bottom_cut` (底部裁剪像素数，默认0)
  - 返回：裁剪后的视频文件

- `POST /video/overlay` - 视频叠加标题和字幕
  - 参数：`file` (视频文件), `title_text` (顶部标题文本), `title_block_height` (标题区域高度), `subtitle_block_height` (字幕区域高度), `title_font_size` (可选), `subtitle_font_size` (可选), `segments` (字幕分段，可选), `payload` (可选), `fontfile` (可选)
  - 返回：叠加后的视频文件

- `POST /video/voice-clone-overlay` - 视频音色克隆、裁剪和叠加完整流程
  - 参数：`file` (视频文件), `title_text` (顶部标题文本)
  - 返回：处理后的视频文件（包含音色克隆、固定裁剪和字幕叠加）

- `POST /video/voice-clone` - 视频音色克隆（仅音频替换）
  - 参数：`file` (视频文件)
  - 返回：处理后的视频文件（仅进行音色克隆，不裁剪、不叠字幕）

---

## 设计原则

1. **按功能类型组织**：相同类型的路由放在同一个文件中，便于维护和理解
2. **文件大小控制**：单个文件原则上不超过 500 行，保持代码可读性
3. **功能完整性**：所有原有路由功能均已保留，确保向后兼容
4. **命名规范**：文件名清晰反映其功能内容

## 路由注册

所有路由在 `app/app.py` 中统一注册：

```python
from app.routers import (
    base,
    audio_basic,
    audio_clone,
    audio_workflow,
    text,
    video,
)

# 注册路由
app.include_router(base.router)
app.include_router(audio_basic.router)
app.include_router(audio_clone.router)
app.include_router(audio_workflow.router)
app.include_router(text.router)
app.include_router(video.router)
```

## 重构说明

本次重构将原有的 11 个路由文件整合为 6 个模块化文件：

- **base.py**: 合并了 `root.py` 和 `health.py`
- **audio_basic.py**: 合并了 `extract.py` 和 `transcription.py`
- **audio_clone.py**: 合并了 `tts.py`
- **audio_workflow.py**: 合并了 `audio_translation_clone.py` 和 `audio_merge.py`
- **text.py**: 保留了 `translation.py` 的功能
- **video.py**: 合并了 `video_crop.py`、`video_overlay.py` 和 `video_voice_clone.py`

所有原有路由端点均保持不变，确保 API 的向后兼容性。

