"""
视频文字叠加服务：在指定高度区域添加标题与逐段字幕。
"""
from pathlib import Path
import uuid
from typing import List, Optional, Dict, Any

import ffmpeg

from app.config import OUTPUT_DIR
from app.utils.ffmpeg_utils import check_ffmpeg_available, get_ffmpeg_install_hint


class VideoOverlayError(Exception):
    """视频叠加错误"""


def _build_drawtext_filter(
    text: str,
    x: str,
    y: str,
    start: float,
    end: float,
    font_size: int,
    font_color: str,
    box: bool = True,
    box_color: str = "black@0.5",
    box_border: int = 8,
    fontfile: Optional[str] = None,
) -> str:
    """
    构造 drawtext 过滤器字符串。
    """
    safe_text = text.replace(":", r"\:").replace("'", r"\'").replace(",", r"\,")
    parts = [
        f"text='{safe_text}'",
        f"x={x}",
        f"y={y}",
        f"fontsize={font_size}",
        f"fontcolor={font_color}",
        f"enable='between(t,{start:.3f},{end:.3f})'",
    ]
    if fontfile:
        safe_font = str(fontfile).replace("'", r"\'")
        parts.append(f"fontfile='{safe_font}'")
    if box:
        parts.append("box=1")
        parts.append(f"boxcolor={box_color}")
        parts.append(f"boxborderw={box_border}")
    return "drawtext=" + ":".join(parts)


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

        # 添加黑色区域：顶部和底部
        box_filters = [
            f"drawbox=x=0:y=0:w=iw:h={title_block_height}:color=black@0.6:t=fill",
            f"drawbox=x=0:y=ih-{subtitle_block_height}:w=iw:h={subtitle_block_height}:color=black@0.6:t=fill",
        ]

        # 标题字体和位置（在顶部块内垂直居中）
        title_fontsize = title_font_size or max(18, int(height * 0.04))
        title_y = max(0, (title_block_height - title_fontsize) // 2)
        title_filter = _build_drawtext_filter(
            text=title_text,
            x="(w-text_w)/2",
            y=str(title_y),
            start=0,
            end=float(video_stream.get("duration", 1e6)),
            font_size=title_fontsize,
            font_color="white",
            box=True,
            box_color="black@0.4",
            box_border=10,
            fontfile=fontfile,
        )

        # 字幕字体和位置：距底部 subtitle_block_height 内垂直居中
        subtitle_filters = []
        subtitle_fontsize = subtitle_font_size or max(16, int(height * 0.035))
        subtitle_y = f"(h-{subtitle_block_height}+({subtitle_block_height}-text_h)/2)"
        for seg in subtitle_segments:
            start = float(seg.get("start", 0))
            end = float(seg.get("end", start + 2.0))
            text = str(seg.get("translated_text") or seg.get("text") or "")
            subtitle_filters.append(
                _build_drawtext_filter(
                    text=text,
                    x="(w-text_w)/2",
                    y=subtitle_y,
                    start=start,
                    end=end,
                    font_size=subtitle_fontsize,
                    font_color="white",
                    box=True,
                    box_color="black@0.35",
                    box_border=8,
                    fontfile=fontfile,
                )
            )

        vf_chain = ",".join(box_filters + [title_filter] + subtitle_filters)
        stream = ffmpeg.input(str(video_path))
        stream = ffmpeg.output(
            stream,
            str(out_path),
            vf=vf_chain,
            vcodec="libx264",
            acodec="copy",
            preset="medium",
            crf=18,
            movflags="+faststart",
        )
        ffmpeg.run(stream, overwrite_output=True, quiet=True)
        return out_path
    except ffmpeg.Error as e:
        detail = e.stderr.decode() if e.stderr else str(e)
        raise VideoOverlayError(f"FFmpeg 叠加失败: {detail}")
    except Exception as e:
        if isinstance(e, VideoOverlayError):
            raise
        raise VideoOverlayError(f"视频叠加失败: {str(e)}")

