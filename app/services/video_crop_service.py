"""
视频自动裁剪服务：检测顶部标题和底部字幕区域后裁剪视频。
"""
from pathlib import Path
import uuid
from typing import Tuple, Optional, List

import cv2
import numpy as np
import ffmpeg

from app.config import OUTPUT_DIR
from app.utils.ffmpeg_utils import check_ffmpeg_available, get_ffmpeg_install_hint


class VideoCropError(Exception):
    """视频裁剪错误"""


def _sample_frames(cap: cv2.VideoCapture, sample_count: int) -> List[np.ndarray]:
    """均匀采样指定数量的帧。"""
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
        # 边缘增强
        grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(grad_x, grad_y)
        # 轻度模糊平滑
        mag = cv2.GaussianBlur(mag, (5, 5), 0)
        # 每行求平均得到水平能量
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
    # 归一化
    norm = (row - min_v) / (ptp_v + 1e-6)

    # 动态阈值：均值 + std * 0.6
    threshold = float(norm.mean() + norm.std() * 0.6)
    mask = norm >= threshold

    # 连续区域检测
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

    max_band_ratio = 0.25  # 单侧最多保留 25% 高度
    top_cut = 0
    bottom_cut = 0

    for start, end in runs:
        band_height = end - start + 1
        if start < height * 0.35:  # 近顶部
            top_cut = max(top_cut, min(band_height + 2, int(height * max_band_ratio)))
        if end > height * 0.65:  # 近底部
            bottom_cut = max(bottom_cut, min(band_height + 2, int(height * max_band_ratio)))

    # 保守回退：避免过度裁剪
    remaining = height - top_cut - bottom_cut
    if remaining < height * 0.5:
        top_cut = 0
        bottom_cut = 0

    return top_cut, bottom_cut


def _build_output_path(suffix: str = ".mp4") -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    return OUTPUT_DIR / f"cropped_{uuid.uuid4().hex}{suffix}"


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

        # 若未指定裁剪像素，自动检测
        if top_cut == 0 and bottom_cut == 0:
            frames = _sample_frames(cap, sample_count=12)
            row_energy = _compute_horizontal_energy(frames)
            top_cut, bottom_cut = _find_bands(row_energy, height)

        # 如果未检测到裁剪区域，则直接返回原视频
        if top_cut <= 0 and bottom_cut <= 0:
            return video_path

        crop_h = height - top_cut - bottom_cut
        if crop_h <= 0:
            raise VideoCropError("裁剪高度无效")

        out_path = output_path or _build_output_path(video_path.suffix)
        OUTPUT_DIR.mkdir(exist_ok=True)

        # 使用 ffmpeg 裁剪（保留音视频）
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
        return out_path

    except ffmpeg.Error as e:
        detail = e.stderr.decode() if e.stderr else str(e)
        raise VideoCropError(f"FFmpeg 裁剪失败: {detail}")
    except Exception as e:
        if isinstance(e, VideoCropError):
            raise
        raise VideoCropError(f"视频裁剪失败: {str(e)}")
    finally:
        cap.release()

