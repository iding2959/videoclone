"""
视频处理服务
整合视频裁剪、文字叠加等功能
"""
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

import cv2
import numpy as np
import ffmpeg

from app.config import OUTPUT_DIR
from app.utils.ffmpeg_utils import check_ffmpeg_available, get_ffmpeg_install_hint
from app.utils.logger import logger


class VideoProcessingError(Exception):
    """视频处理错误基类"""
    pass


class VideoCropError(VideoProcessingError):
    """视频裁剪错误"""
    pass


class VideoOverlayError(VideoProcessingError):
    """视频叠加错误"""
    pass


def _sample_frames(cap: cv2.VideoCapture, sample_count: int) -> List[np.ndarray]:
    """均匀采样指定数量的帧"""
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    if frame_count <= 0:
        raise VideoCropError("无法获取视频帧数")

    indices = np.linspace(0, frame_count - 1, num=min(sample_count, frame_count), dtype=int)
    frames: List[np.ndarray] = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if ok and frame is not None:
            frames.append(frame)
    if not frames:
        raise VideoCropError("无法读取视频帧")
    return frames


def _compute_horizontal_energy(frames: List[np.ndarray]) -> np.ndarray:
    """
    计算多帧叠加的水平能量，用于定位顶部标题和底部字幕。
    使用边缘（Sobel）+ 模糊降低噪声。
    """
    energies = []
    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(grad_x, grad_y)
        mag = cv2.GaussianBlur(mag, (5, 5), 0)
        row_energy = mag.mean(axis=1)
        energies.append(row_energy)
    stacked = np.vstack(energies)
    return stacked.mean(axis=0)


def _find_bands(row_energy: np.ndarray, height: int) -> Tuple[int, int]:
    """
    根据行能量找到顶部和底部需要裁剪的高度。
    返回 (top_cut, bottom_cut)。
    """
    row = np.asarray(row_energy, dtype=float).squeeze()
    min_v = float(row.min())
    ptp_v = float(row.max() - min_v)
    norm = (row - min_v) / (ptp_v + 1e-6)

    threshold = float(norm.mean() + norm.std() * 0.6)
    mask = norm >= threshold

    def contiguous_run(binary: np.ndarray) -> List[Tuple[int, int]]:
        runs = []
        start = None
        for i, v in enumerate(binary):
            if v and start is None:
                start = i
            elif not v and start is not None:
                runs.append((start, i - 1))
                start = None
        if start is not None:
            runs.append((start, len(binary) - 1))
        return runs

    runs = contiguous_run(mask)

    max_band_ratio = 0.25
    top_cut = 0
    bottom_cut = 0

    for start, end in runs:
        band_height = end - start + 1
        if start < height * 0.35:
            top_cut = max(top_cut, min(band_height + 2, int(height * max_band_ratio)))
        if end > height * 0.65:
            bottom_cut = max(bottom_cut, min(band_height + 2, int(height * max_band_ratio)))

    remaining = height - top_cut - bottom_cut
    if remaining < height * 0.5:
        top_cut = 0
        bottom_cut = 0

    return top_cut, bottom_cut


def detect_and_crop_video(
    video_path: Path,
    output_path: Optional[Path] = None,
    top_cut: int = 0,
    bottom_cut: int = 0,
) -> Path:
    """
    裁剪视频顶部与底部的像素高度；若未指定则自动检测。

    Args:
        video_path: 输入视频路径
        output_path: 输出视频路径（可选）
        top_cut: 需要裁剪的顶部像素数（>=0）
        bottom_cut: 需要裁剪的底部像素数（>=0）

    Returns:
        裁剪后视频路径
    """
    if not video_path.exists():
        raise VideoCropError(f"视频文件不存在: {video_path}")

    if not check_ffmpeg_available():
        raise VideoCropError(f"FFmpeg 未安装或不可用。{get_ffmpeg_install_hint()}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise VideoCropError("无法打开视频文件")

    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

        if top_cut < 0 or bottom_cut < 0:
            raise VideoCropError("裁剪像素必须为非负整数")

        if top_cut == 0 and bottom_cut == 0:
            logger.info("自动检测视频裁剪区域...")
            frames = _sample_frames(cap, sample_count=12)
            row_energy = _compute_horizontal_energy(frames)
            top_cut, bottom_cut = _find_bands(row_energy, height)
            logger.info(f"检测到裁剪区域: top={top_cut}, bottom={bottom_cut}")

        if top_cut <= 0 and bottom_cut <= 0:
            logger.info("未检测到需要裁剪的区域，返回原视频")
            return video_path

        crop_h = height - top_cut - bottom_cut
        if crop_h <= 0:
            raise VideoCropError("裁剪高度无效")

        out_path = output_path or (OUTPUT_DIR / f"cropped_{uuid.uuid4().hex}{video_path.suffix}")
        OUTPUT_DIR.mkdir(exist_ok=True)

        logger.info(f"开始裁剪视频: top={top_cut}, bottom={bottom_cut}, 输出: {out_path}")
        stream = ffmpeg.input(str(video_path))
        stream = ffmpeg.output(
            stream,
            str(out_path),
            vf=f"crop=w={width}:h={crop_h}:x=0:y={top_cut}",
            vcodec="libx264",
            acodec="copy",
            r=fps,
            preset="medium",
            crf=18,
        )
        ffmpeg.run(stream, overwrite_output=True, quiet=True)
        logger.info(f"视频裁剪完成: {out_path}")
        return out_path

    except ffmpeg.Error as e:
        detail = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"FFmpeg 裁剪失败: {detail}")
        raise VideoCropError(f"FFmpeg 裁剪失败: {detail}")
    except Exception as e:
        if isinstance(e, VideoCropError):
            raise
        logger.error(f"视频裁剪异常: {str(e)}")
        raise VideoCropError(f"视频裁剪失败: {str(e)}")
    finally:
        cap.release()


def _wrap_text(text: str, max_chars: int) -> str:
    """
    根据最大字符数粗略换行，优先按空格/标点拆分，否则硬切。
    """
    if max_chars <= 0:
        return text
    words = []
    current = ""
    for ch in text:
        if len(current) >= max_chars:
            words.append(current)
            current = ""
        if ch in [" ", ",", ".", "，", "。", "！", "？", "!", "?", ";", "；"]:
            current += ch
            words.append(current)
            current = ""
        else:
            current += ch
    if current:
        words.append(current)

    lines = []
    line = ""
    for token in words:
        if len(line) + len(token) <= max_chars:
            line += token
        else:
            if line:
                lines.append(line)
            line = token
    if line:
        lines.append(line)
    return "\n".join(lines)


def overlay_title_and_subtitles(
    video_path: Path,
    output_path: Optional[Path],
    title_text: str,
    subtitle_segments: List[Dict[str, Any]],
    title_block_height: int,
    subtitle_block_height: int,
    title_font_size: Optional[int] = None,
    subtitle_font_size: Optional[int] = None,
    fontfile: Optional[str] = None,
) -> Path:
    """
    在视频上添加标题（全程显示）与分段字幕（按 segments 时间显示），并允许指定块高度与字体大小。

    Args:
        video_path: 输入视频
        output_path: 输出视频，可为 None 自动生成
        title_text: 顶部标题文本
        subtitle_segments: 分段字幕数据，包含 start/end/text
        title_block_height: 标题区域高度（像素），从顶部向下占用
        subtitle_block_height: 字幕区域高度（像素），从底部向上占用
        title_font_size: 标题字体大小（可选），未指定则按视频高度自适应
        subtitle_font_size: 字幕字体大小（可选），未指定则按视频高度自适应
        fontfile: 字体路径（可选）。若不指定，使用系统默认字体。
    """
    if not video_path.exists():
        raise VideoOverlayError(f"视频文件不存在: {video_path}")
    if not check_ffmpeg_available():
        raise VideoOverlayError(f"FFmpeg 未安装或不可用。{get_ffmpeg_install_hint()}")

    out_path = output_path or (OUTPUT_DIR / f"overlay_{uuid.uuid4().hex}{video_path.suffix}")
    OUTPUT_DIR.mkdir(exist_ok=True)

    try:
        probe = ffmpeg.probe(str(video_path))
        video_stream = next((s for s in probe["streams"] if s["codec_type"] == "video"), None)
        if not video_stream:
            raise VideoOverlayError("未找到视频流")
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        if width <= 0 or height <= 0:
            raise VideoOverlayError("无法获取视频分辨率")

        if title_block_height <= 0 or subtitle_block_height <= 0:
            raise VideoOverlayError("标题/字幕块高度必须大于 0")

        title_fontsize = title_font_size or max(18, int(height * 0.04))
        max_title_chars = max(8, int(width / max(1, title_fontsize * 0.55)))
        wrapped_title = _wrap_text(title_text, max_title_chars)
        title_y = max(0, (title_block_height - title_fontsize) // 2)
        
        subtitle_fontsize = subtitle_font_size or max(16, int(height * 0.035))
        subtitle_y = f"(h-{subtitle_block_height}+({subtitle_block_height}-text_h)/2)"
        
        stream = ffmpeg.input(str(video_path))
        video = stream["v"]
        audio = stream["a"]
        
        video_duration = float(video_stream.get("duration", 1e6))
        safe_title = (
            wrapped_title
            .replace(":", r"\:")
            .replace("'", r"\'")
            .replace(",", r"\,")
            .replace("\n", r"\n")
        )
        video = video.filter("drawtext", 
            text=safe_title,
            x="(w-text_w)/2",
            y=str(title_y),
            fontsize=title_fontsize,
            fontcolor="white",
            box=1,
            boxcolor="black@0.4",
            boxborderw=10,
            enable=f"between(t,0,{video_duration:.3f})",
            **({"fontfile": fontfile} if fontfile else {})
        )
        
        logger.info(f"开始叠加字幕，共 {len(subtitle_segments)} 个字幕段")
        subtitle_count = 0
        for idx, seg in enumerate(subtitle_segments, 1):
            start = float(seg.get("start", 0))
            end = float(seg.get("end", start + 2.0))
            text = str(seg.get("translated_text") or seg.get("text") or "")
            if not text.strip():
                logger.warning(f"字幕段 {idx} [{start:.2f}-{end:.2f}] 文本为空，跳过")
                continue
            max_sub_chars = max(8, int(width / max(1, subtitle_fontsize * 0.55)))
            wrapped_text = _wrap_text(text, max_sub_chars)
            
            safe_text = (
                wrapped_text
                .replace(":", r"\:")
                .replace("'", r"\'")
                .replace(",", r"\,")
                .replace("\n", r"\n")
            )
            
            logger.debug(f"添加字幕段 {idx}: [{start:.2f}-{end:.2f}] {text[:50]}")
            video = video.filter("drawtext",
                text=safe_text,
                x="(w-text_w)/2",
                y=subtitle_y,
                fontsize=subtitle_fontsize,
                fontcolor="white",
                box=1,
                boxcolor="black@0.35",
                boxborderw=8,
                enable=f"between(t,{start:.3f},{end:.3f})",
                **({"fontfile": fontfile} if fontfile else {})
            )
            subtitle_count += 1
        logger.info(f"字幕叠加完成，共添加 {subtitle_count + 1} 个过滤器（标题 + {subtitle_count} 个字幕）")
        
        stream = ffmpeg.output(
            video,
            audio,
            str(out_path),
            vcodec="libx264",
            acodec="copy",
            preset="medium",
            crf=18,
            movflags="+faststart",
        )
        ffmpeg.run(stream, overwrite_output=True, quiet=True)
        logger.info(f"视频叠加完成: {out_path}")
        return out_path
    except ffmpeg.Error as e:
        detail = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"FFmpeg 叠加失败: {detail}")
        raise VideoOverlayError(f"FFmpeg 叠加失败: {detail}")
    except Exception as e:
        if isinstance(e, VideoOverlayError):
            raise
        logger.error(f"视频叠加异常: {str(e)}")
        raise VideoOverlayError(f"视频叠加失败: {str(e)}")

