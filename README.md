# 视频音频分离服务

一个基于 FastAPI 的视频音频分离服务，支持从视频文件中提取音频。

## 功能特性

- ✅ 整体音频分离：上传视频文件，提取完整音频
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
├── main.py              # FastAPI 应用主文件
├── pyproject.toml       # 项目配置和依赖
├── README.md           # 项目说明
├── uploads/            # 临时存储上传的视频文件（自动创建）
└── outputs/            # 存储提取的音频文件（自动创建）
```

## 注意事项

- 上传的视频文件在处理完成后会自动清理
- 输出的音频文件格式为 MP3，采样率 44.1kHz，双声道
- 大文件处理可能需要较长时间，请耐心等待

## 后续计划

- [ ] 支持按时间段分段提取音频
- [ ] 支持多种音频格式输出
- [ ] 添加处理进度查询接口
- [ ] 支持批量处理

