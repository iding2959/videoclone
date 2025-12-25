# 视频音频处理服务

一个基于 FastAPI 的视频音频处理服务，支持从视频文件中提取音频、音频转录、翻译和语音合成等功能。

## 功能特性

- ✅ 整体音频分离：上传视频文件，提取完整音频
- ✅ 音频转录：支持将音频转换为文字（使用 Whisper 服务）
- ✅ 文本翻译：支持中英文翻译（使用翻译服务）
- ✅ 语音合成：支持音频克隆和语音合成（使用 IndexTTS 服务）
- 🔄 分段音频分离：后续将支持按时间段分段提取音频

## 环境要求

- Python >= 3.11
- FFmpeg（需要系统安装 FFmpeg）

### 安装 FFmpeg

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Windows:**
从 [FFmpeg 官网](https://ffmpeg.org/download.html) 下载并添加到系统 PATH

## 服务配置

⚠️ **重要提示**：本项目依赖以下外部服务，需要自行配置并确保服务可用：

### 1. Whisper 服务（音频转录）

项目使用 Whisper API 进行音频转录。需要在 `app/config.py` 中配置：

- `TRANSCRIPTION_API_URL`: Whisper 服务的 API 地址
- `TRANSCRIPTION_API_TOKEN`: API 访问令牌
- `TRANSCRIPTION_DEFAULT_MODEL`: 默认使用的模型（如 "Faster-Whisper-Large-V3"）

**配置示例：**
```python
TRANSCRIPTION_API_URL = "http://your-whisper-server/v1/audio/transcriptions"
TRANSCRIPTION_API_TOKEN = "your-api-token"
TRANSCRIPTION_DEFAULT_MODEL = "Faster-Whisper-Large-V3"
```

### 2. IndexTTS 服务（语音合成）

项目使用 IndexTTS 服务进行音频克隆和语音合成。需要在 `app/config.py` 中配置：

- `TTS_API_BASE_URL`: IndexTTS 服务的基础 URL
- 相关 API 端点会自动拼接（如 `/api/tts/synthesize-async`、`/api/tts/task`、`/api/tts/download`）

**配置示例：**
```python
TTS_API_BASE_URL = "http://your-indextts-server:8147"
```

### 3. 翻译服务（可选）

如果需要使用翻译功能，需要在 `app/config.py` 中配置：

- `TRANSLATION_API_URL`: 翻译服务的 API 地址
- `TRANSLATION_API_TOKEN`: API 访问令牌
- `TRANSLATION_DEFAULT_MODEL`: 默认使用的翻译模型

**配置示例：**
```python
TRANSLATION_API_URL = "http://your-translation-server/v1/chat/completions"
TRANSLATION_API_TOKEN = "your-api-token"
TRANSLATION_DEFAULT_MODEL = "Hunyuan-MT-Chimera-7B"
```

> 💡 **提示**：所有服务配置都在 `app/config.py` 文件中，请根据实际部署情况修改相应的配置项。

## 安装依赖

```bash
pip install -e .
```

## 运行服务

```bash
python main.py
```

或者使用 uvicorn：

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

服务启动后，访问 http://localhost:8000/docs 查看 API 文档。

## API 接口

### 1. 健康检查
```
GET /health
```

### 2. 提取音频
```
POST /extract
Content-Type: multipart/form-data

参数:
- file: 视频文件（支持常见视频格式）
```

**响应:**
- 成功：返回 MP3 格式的音频文件
- 失败：返回错误信息

## 使用示例

### 使用 curl

```bash
curl -X POST "http://localhost:8000/extract" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@your_video.mp4"
```

### 使用 Python requests

```python
import requests

url = "http://localhost:8000/extract"
files = {"file": open("your_video.mp4", "rb")}
response = requests.post(url, files=files)

if response.status_code == 200:
    with open("output.mp3", "wb") as f:
        f.write(response.content)
    print("音频提取成功！")
else:
    print(f"错误: {response.json()}")
```

## 项目结构

```
pekying/
├── main.py                    # 应用入口，负责启动服务
├── pyproject.toml             # 项目配置和依赖
├── uv.lock                    # 依赖锁定文件
├── README.md                  # 项目说明
├── app/                       # 应用主目录
│   ├── __init__.py
│   ├── app.py                 # FastAPI 应用创建和配置
│   ├── config.py              # 应用配置（包含外部服务配置）
│   ├── routers/               # API 路由模块
│   │   ├── __init__.py
│   │   ├── base.py            # 基础路由类
│   │   ├── audio_basic.py     # 基础音频处理路由
│   │   ├── audio_clone.py     # 音频克隆路由
│   │   ├── audio_workflow.py  # 音频工作流路由
│   │   ├── text.py            # 文本处理路由
│   │   ├── video.py           # 视频处理路由
│   │   └── README.md          # 路由模块说明
│   ├── services/              # 业务逻辑服务
│   │   ├── __init__.py
│   │   ├── audio_processing_service.py  # 音频处理服务
│   │   ├── text_processing_service.py   # 文本处理服务
│   │   ├── video_processing_service.py  # 视频处理服务
│   │   ├── workflow_service.py          # 工作流服务
│   │   └── README.md                    # 服务模块说明
│   └── utils/                 # 工具函数
│       ├── __init__.py
│       ├── ffmpeg_utils.py    # FFmpeg 相关工具
│       └── logger.py          # 日志工具
├── uploads/                   # 临时存储上传的视频文件（自动创建）
├── outputs/                   # 存储提取的音频文件（自动创建）
└── logs/                      # 日志文件目录（自动创建）
```

## 注意事项

- ⚠️ **必须配置外部服务**：使用前请确保已正确配置 Whisper、IndexTTS 等服务（详见"服务配置"部分）
- 上传的视频文件在处理完成后会自动清理
- 输出的音频文件格式为 WAV，采样率 44.1kHz，双声道
- 大文件处理可能需要较长时间，请耐心等待
- 确保所有外部服务正常运行且网络可达

## 后续计划

- [ ] 支持按时间段分段提取音频
- [ ] 支持多种音频格式输出
- [ ] 添加处理进度查询接口
- [ ] 支持批量处理

