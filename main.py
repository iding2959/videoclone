"""
视频音频分离 FastAPI 应用
"""
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

import ffmpeg
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="视频音频分离服务", version="0.1.0")

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 创建必要的目录
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


def check_ffmpeg_available() -> bool:
    """
    检查系统是否安装了 FFmpeg
    
    Returns:
        True 如果 FFmpeg 可用，False 否则
    """
    return shutil.which("ffmpeg") is not None


def get_ffmpeg_install_hint() -> str:
    """
    根据操作系统返回 FFmpeg 安装提示
    
    Returns:
        安装提示信息
    """
    import platform
    system = platform.system().lower()
    
    if system == "linux":
        return "请运行: sudo apt update && sudo apt install ffmpeg"
    elif system == "darwin":
        return "请运行: brew install ffmpeg"
    elif system == "windows":
        return "请从 https://ffmpeg.org/download.html 下载并添加到系统 PATH"
    else:
        return "请安装 FFmpeg 并确保它在系统 PATH 中"


def extract_audio(video_path: Path, output_path: Path) -> Path:
    """
    从视频文件中提取音频
    
    Args:
        video_path: 视频文件路径
        output_path: 输出音频文件路径
        
    Returns:
        输出音频文件路径
        
    Raises:
        Exception: 如果提取失败
    """
    # 检查 FFmpeg 是否可用
    if not check_ffmpeg_available():
        raise Exception(
            f"FFmpeg 未安装或不在系统 PATH 中。{get_ffmpeg_install_hint()}"
        )
    
    try:
        # 使用 ffmpeg 提取音频，输出为 MP3 格式
        stream = ffmpeg.input(str(video_path))
        stream = ffmpeg.output(stream, str(output_path), acodec="libmp3lame", ac=2, ar="44100")
        ffmpeg.run(stream, overwrite_output=True, quiet=True)
        return output_path
    except FileNotFoundError as e:
        raise Exception(
            f"FFmpeg 未找到: {str(e)}。{get_ffmpeg_install_hint()}"
        )
    except ffmpeg.Error as e:
        error_message = e.stderr.decode() if e.stderr else str(e)
        raise Exception(f"音频提取失败: {error_message}")
    except Exception as e:
        # 捕获其他可能的异常（如 OSError）
        if "No such file or directory" in str(e) or "ffmpeg" in str(e).lower():
            raise Exception(
                f"FFmpeg 未找到: {str(e)}。{get_ffmpeg_install_hint()}"
            )
        raise


@app.get("/")
async def root():
    """根路径，返回服务信息"""
    return {
        "service": "视频音频分离服务",
        "version": "0.1.0",
        "endpoints": {
            "POST /extract": "上传视频文件，提取音频",
            "GET /health": "健康检查"
        }
    }


@app.get("/health")
async def health():
    """
    健康检查接口
    
    检查服务状态和 FFmpeg 可用性
    """
    ffmpeg_available = check_ffmpeg_available()
    status = "healthy" if ffmpeg_available else "degraded"
    
    return {
        "status": status,
        "ffmpeg_available": ffmpeg_available,
        "message": "服务正常" if ffmpeg_available else f"FFmpeg 不可用。{get_ffmpeg_install_hint()}"
    }


@app.post("/extract")
async def extract_audio_from_video(file: UploadFile = File(...)):
    """
    上传视频文件并提取音频
    
    Args:
        file: 上传的视频文件
        
    Returns:
        提取的音频文件
    """
    # 验证文件类型
    if not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="请上传视频文件")
    
    # 生成唯一文件名
    file_id = str(uuid.uuid4())
    video_extension = Path(file.filename).suffix if file.filename else ".mp4"
    video_path = UPLOAD_DIR / f"{file_id}{video_extension}"
    audio_path = OUTPUT_DIR / f"{file_id}.mp3"
    
    try:
        # 保存上传的视频文件
        with open(video_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # 提取音频
        extract_audio(video_path, audio_path)
        
        # 检查输出文件是否存在
        if not audio_path.exists():
            raise HTTPException(status_code=500, detail="音频提取失败，输出文件未生成")
        
        # 返回音频文件
        return FileResponse(
            path=str(audio_path),
            media_type="audio/mpeg",
            filename=f"{Path(file.filename).stem if file.filename else 'audio'}.mp3"
        )
    
    except Exception as e:
        # 清理已创建的文件
        if video_path.exists():
            video_path.unlink()
        if audio_path.exists():
            audio_path.unlink()
        
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
    
    finally:
        # 清理上传的视频文件（可选，根据需求决定是否保留）
        if video_path.exists():
            video_path.unlink()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
