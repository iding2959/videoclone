"""
音频合并服务
实现音频翻译克隆和合并的完整流程
"""
import asyncio
import tempfile
import time
import uuid
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
import httpx

import ffmpeg

logger = logging.getLogger(__name__)

from app.config import OUTPUT_DIR, AUDIO_CODEC, AUDIO_CHANNELS, AUDIO_SAMPLE_RATE
from app.services.audio_translation_clone_service import process_audio_translation_clone, AudioTranslationCloneError
from app.services.tts_service import query_task_status, download_audio_file, TTSError
from app.utils.ffmpeg_utils import check_ffmpeg_available, get_ffmpeg_install_hint


class AudioMergeError(Exception):
    """音频合并错误"""
    pass


async def merge_cloned_audios(
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
    query_interval: float = 2.0,
    max_wait_time: float = 300.0,
    base_url: str = "http://localhost:8000",
) -> Path:
    """
    音频翻译克隆并合并完整流程
    
    流程：
    1. 调用音频翻译克隆接口，得到任务ID和最后一段音频路径
    2. 查询所有克隆任务状态，等待完成
    3. 下载所有克隆后的音频
    4. 下载最后一段音频（没有克隆的）
    5. 合并所有音频，返回合并后的音频文件
    
    Args:
        audio_file_path: 要处理的音频文件路径
        transcription_model: 转录使用的模型（可选）
        transcription_language: 转录使用的语言代码（可选）
        transcription_response_format: 转录响应格式（可选）
        translation_model: 翻译使用的模型（可选）
        translation_system_prompt: 翻译使用的系统提示词（可选）
        emo_control_method: 情感控制方式
        emo_weight: 情感权重
        emo_text: 情感描述文本
        max_text_tokens_per_segment: 分句最大Token数
        temperature: 采样温度
        top_p: top_p采样
        top_k: top_k采样
        emo_audio_path: 情感参考音频文件路径（可选）
        query_interval: 查询任务状态的间隔时间（秒）
        max_wait_time: 最大等待时间（秒）
        base_url: API 基础URL
        
    Returns:
        合并后的音频文件路径
        
    Raises:
        AudioMergeError: 如果处理失败
    """
    if not audio_file_path.exists():
        raise AudioMergeError(f"音频文件不存在: {audio_file_path}")
    
    # 检查 FFmpeg 是否可用
    if not check_ffmpeg_available():
        raise AudioMergeError(
            f"FFmpeg 未安装或不在系统 PATH 中。{get_ffmpeg_install_hint()}"
        )
    
    try:
        # 步骤1: 调用音频翻译克隆接口
        logger.info("步骤1: 开始调用音频翻译克隆接口...")
        clone_result = await process_audio_translation_clone(
            audio_file_path=audio_file_path,
            transcription_model=transcription_model,
            transcription_language=transcription_language,
            transcription_response_format=transcription_response_format,
            translation_model=translation_model,
            translation_system_prompt=translation_system_prompt,
            emo_control_method=emo_control_method,
            emo_weight=emo_weight,
            emo_text=emo_text,
            max_text_tokens_per_segment=max_text_tokens_per_segment,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            emo_audio_path=emo_audio_path,
        )
        logger.info(f"步骤1完成: 生成了 {len(clone_result.get('tasks', []))} 个任务")
        
        tasks = clone_result.get("tasks", [])
        if not tasks:
            raise AudioMergeError("没有生成任何克隆任务")
        
        # 提取任务ID和最后一段音频路径，按 segment_index 排序
        sorted_tasks = sorted(tasks, key=lambda x: x.get("segment_index", 0))
        
        task_info_list = []  # 保存 (task_id, segment_index) 的列表
        last_segment_path = None
        
        for task in sorted_tasks:
            task_id = task.get("task_id")
            segment_index = task.get("segment_index", 0)
            
            if task_id:
                task_info_list.append((task_id, segment_index))
                logger.info(f"  任务 {segment_index}: task_id={task_id}")
            
            # 查找最后一段音频（没有克隆的）
            if task.get("error") == "该音频段没有对应的翻译文本":
                audio_path = task.get("audio_path", "")
                if audio_path:
                    last_segment_path = audio_path
                    logger.info(f"  最后一段音频: {audio_path}")
        
        if not task_info_list:
            raise AudioMergeError("没有有效的任务ID")
        
        logger.info(f"步骤2: 开始查询 {len(task_info_list)} 个克隆任务状态...")
        # 步骤2: 查询任务状态，等待完成
        cloned_audio_files = await _wait_and_download_cloned_audios(
            task_info_list=task_info_list,
            query_interval=query_interval,
            max_wait_time=max_wait_time,
        )
        logger.info(f"步骤2完成: 成功下载 {len(cloned_audio_files)} 个克隆音频文件")
        
        # 步骤3: 下载最后一段音频
        if last_segment_path:
            logger.info("步骤3: 开始下载最后一段音频...")
            # 从路径中提取文件名，例如 outputs/xxx_segment_3.wav -> xxx_segment_3.wav
            filename = Path(last_segment_path).name
            logger.info(f"  文件名: {filename}")
            last_segment_file = await _download_segment_file(filename, base_url)
            cloned_audio_files.append(last_segment_file)
            logger.info(f"步骤3完成: 最后一段音频已下载")
        
        logger.info(f"步骤4: 开始合并 {len(cloned_audio_files)} 个音频文件...")
        # 步骤4: 合并所有音频
        merged_audio_path = await _merge_audio_files(cloned_audio_files)
        logger.info(f"步骤4完成: 音频合并完成，输出文件: {merged_audio_path}")
        
        # 清理临时文件
        for temp_file in cloned_audio_files:
            if temp_file.exists() and temp_file != merged_audio_path:
                try:
                    temp_file.unlink()
                except Exception:
                    pass
        
        return merged_audio_path
    
    except AudioTranslationCloneError as e:
        raise AudioMergeError(f"音频翻译克隆失败: {str(e)}")
    except Exception as e:
        if isinstance(e, AudioMergeError):
            raise
        raise AudioMergeError(f"音频合并失败: {str(e)}")


async def _wait_and_download_cloned_audios(
    task_info_list: List[tuple],
    query_interval: float = 2.0,
    max_wait_time: float = 300.0,
) -> List[Path]:
    """
    等待克隆任务完成并下载音频文件
    
    Args:
        task_info_list: (task_id, segment_index) 元组列表，按 segment_index 排序
        query_interval: 查询间隔（秒）
        max_wait_time: 最大等待时间（秒）
        
    Returns:
        下载的音频文件路径列表，按 segment_index 顺序排列
    """
    # 创建临时目录存放下载的音频
    temp_dir = Path(tempfile.gettempdir()) / f"audio_merge_{uuid.uuid4()}"
    temp_dir.mkdir(exist_ok=True)
    
    # 使用字典保存每个 segment_index 对应的文件路径
    downloaded_files_dict = {}
    pending_tasks = {task_id: segment_index for task_id, segment_index in task_info_list}
    
    start_time = time.time()
    
    query_count = 0
    while pending_tasks and (time.time() - start_time) < max_wait_time:
        query_count += 1
        elapsed_time = time.time() - start_time
        logger.info(f"  查询轮次 {query_count}: 还有 {len(pending_tasks)} 个任务待处理，已等待 {elapsed_time:.1f} 秒")
        
        for task_id, segment_index in list(pending_tasks.items()):
            try:
                result = await query_task_status(task_id=task_id)
                
                # API返回格式: {'code': 200, 'success': True, 'data': {'status': 'completed', 'result': {...}}}
                # 需要从 data 字段中获取状态和结果
                data = result.get("data", {})
                if not data:
                    # 如果没有 data 字段，可能状态直接在顶层（兼容旧格式）
                    data = result
                    logger.debug(f"    使用顶层数据（无data字段）")
                else:
                    logger.debug(f"    从data字段获取状态")
                
                status = data.get("status", "")
                
                # 打印完整的响应以便调试
                logger.info(f"    任务 {task_id} (segment {segment_index}) 完整响应: {result}")
                logger.info(f"    任务 {task_id} (segment {segment_index}) data字段: {data}")
                logger.info(f"    任务 {task_id} (segment {segment_index}) 状态: '{status}'")
                
                # 检查多种可能的状态值
                if status in ["completed", "success", "done", "finished"]:
                    # 任务完成，下载音频
                    task_result = data.get("result", {})
                    if not task_result:
                        # 可能 result 在顶层
                        task_result = result.get("result", {})
                    
                    filename = task_result.get("filename") or task_result.get("file") or task_result.get("audio_file")
                    if filename:
                        logger.info(f"      任务完成，开始下载音频文件: {filename}")
                        audio_content = await download_audio_file(filename)
                        audio_path = temp_dir / filename
                        with open(audio_path, "wb") as f:
                            f.write(audio_content)
                        downloaded_files_dict[segment_index] = audio_path
                        del pending_tasks[task_id]
                        logger.info(f"      音频文件已下载: {audio_path}")
                    else:
                        logger.warning(f"      任务完成但未找到文件名，完整响应: {result}")
                elif status in ["failed", "error", "failure"]:
                    # 任务失败
                    error_msg = data.get("error") or data.get("message") or result.get("error") or result.get("message") or "任务失败"
                    raise AudioMergeError(f"克隆任务 {task_id} 失败: {error_msg}")
                elif status in ["processing", "pending", "running", "in_progress", "queued"]:
                    # 任务进行中，继续等待
                    logger.info(f"      任务进行中，继续等待...")
                else:
                    # 未知状态，打印出来以便调试
                    logger.warning(f"      未知状态 '{status}'，完整响应: {result}")
                
            except TTSError as e:
                # 查询失败，可能是任务不存在或网络问题
                logger.error(f"    查询任务 {task_id} 状态失败: {str(e)}")
                raise AudioMergeError(f"查询任务 {task_id} 状态失败: {str(e)}")
        
        # 如果还有待处理的任务，等待一段时间后继续查询
        if pending_tasks:
            logger.info(f"  等待 {query_interval} 秒后继续查询...")
            await asyncio.sleep(query_interval)
    
    if pending_tasks:
        raise AudioMergeError(f"等待任务完成超时，仍有 {len(pending_tasks)} 个任务未完成")
    
    # 按 segment_index 排序返回文件列表
    sorted_segments = sorted(downloaded_files_dict.keys())
    return [downloaded_files_dict[idx] for idx in sorted_segments]


async def _download_segment_file(filename: str, base_url: str) -> Path:
    """
    从服务器下载切分的音频文件
    
    Args:
        filename: 文件名
        base_url: API 基础URL
        
    Returns:
        下载的音频文件路径
    """
    download_url = f"{base_url}/segment/download/{filename}"
    
    # 使用临时文件而不是临时目录
    temp_file_id = str(uuid.uuid4())
    file_extension = Path(filename).suffix
    audio_path = Path(tempfile.gettempdir()) / f"audio_merge_{temp_file_id}{file_extension}"
    
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(download_url)
            response.raise_for_status()
            
            with open(audio_path, "wb") as f:
                f.write(response.content)
            
            return audio_path
    except httpx.HTTPStatusError as e:
        raise AudioMergeError(f"下载音频文件失败 (状态码 {e.response.status_code}): {e.response.text}")
    except httpx.RequestError as e:
        raise AudioMergeError(f"下载音频文件请求错误: {str(e)}")
    except Exception as e:
        raise AudioMergeError(f"下载音频文件失败: {str(e)}")


async def _merge_audio_files(audio_files: List[Path]) -> Path:
    """
    合并多个音频文件
    
    Args:
        audio_files: 音频文件路径列表
        
    Returns:
        合并后的音频文件路径
    """
    if not audio_files:
        raise AudioMergeError("没有音频文件需要合并")
    
    if len(audio_files) == 1:
        # 只有一个文件，直接返回
        return audio_files[0]
    
    # 生成输出文件路径
    output_id = str(uuid.uuid4())
    output_path = OUTPUT_DIR / f"merged_{output_id}.wav"
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    try:
        # 使用 ffmpeg 合并音频文件
        # 创建输入流列表
        inputs = [ffmpeg.input(str(audio_file)) for audio_file in audio_files]
        
        # 使用 concat filter 合并音频
        merged = ffmpeg.concat(*inputs, v=0, a=1)
        
        # 输出为 WAV 格式
        stream = ffmpeg.output(
            merged,
            str(output_path),
            acodec=AUDIO_CODEC,
            ac=AUDIO_CHANNELS,
            ar=AUDIO_SAMPLE_RATE
        )
        
        ffmpeg.run(stream, overwrite_output=True, quiet=True)
        
        return output_path
    
    except FileNotFoundError as e:
        raise AudioMergeError(f"FFmpeg 未找到: {str(e)}。{get_ffmpeg_install_hint()}")
    except ffmpeg.Error as e:
        error_message = e.stderr.decode() if e.stderr else str(e)
        raise AudioMergeError(f"音频合并失败: {error_message}")
    except Exception as e:
        if "No such file or directory" in str(e) or "ffmpeg" in str(e).lower():
            raise AudioMergeError(f"FFmpeg 未找到: {str(e)}。{get_ffmpeg_install_hint()}")
        raise AudioMergeError(f"音频合并失败: {str(e)}")

