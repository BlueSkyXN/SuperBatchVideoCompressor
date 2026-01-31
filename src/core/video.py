#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频信息获取模块

提供获取视频元数据的功能
"""

import subprocess
import logging
import json
from typing import Optional, Dict, Any


def get_bitrate(filepath: str) -> int:
    """
    获取视频文件的码率

    Args:
        filepath: 视频文件路径

    Returns:
        码率（bps）
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=bit_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            filepath,
        ]
        output = (
            subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=10)
            .decode("utf-8")
            .strip()
        )
        return int(output)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as e:
        logging.warning(f"无法获取码率 {filepath}，使用默认值 3Mbps。错误: {e}")
        return 3000000
    except Exception as e:
        logging.error(f"获取码率时发生未预期错误 {filepath}: {e}", exc_info=True)
        return 3000000


def get_resolution(filepath: str) -> tuple:
    """
    获取视频文件的分辨率

    Args:
        filepath: 视频文件路径

    Returns:
        (宽度, 高度) 元组
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            filepath,
        ]
        output = (
            subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=10)
            .decode("utf-8")
            .strip()
        )
        parts = output.split(",")
        return int(parts[0]), int(parts[1])
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, IndexError) as e:
        # 兜底到 1080p，避免分辨率缺失导致封顶不合理
        logging.warning(f"无法获取分辨率 {filepath}，使用默认值 1080p。错误: {e}")
        return 1920, 1080
    except Exception as e:
        logging.error(f"获取分辨率时发生未预期错误 {filepath}: {e}", exc_info=True)
        return 1920, 1080


def get_codec(filepath: str) -> str:
    """
    获取视频文件的编码格式

    Args:
        filepath: 视频文件路径

    Returns:
        编码格式名称
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            filepath,
        ]
        output = (
            subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=10)
            .decode("utf-8")
            .strip()
        )
        return output
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logging.warning(f"无法获取编码格式 {filepath}。错误: {e}")
        return "unknown"
    except Exception as e:
        logging.error(f"获取编码格式时发生未预期错误 {filepath}: {e}", exc_info=True)
        return "unknown"


def get_duration(filepath: str) -> float:
    """
    获取视频时长（秒）

    Args:
        filepath: 视频文件路径

    Returns:
        时长（秒）
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            filepath,
        ]
        output = (
            subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=10)
            .decode("utf-8")
            .strip()
        )
        return float(output)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as e:
        logging.warning(f"无法获取时长 {filepath}。错误: {e}")
        return 0.0
    except Exception as e:
        logging.error(f"获取时长时发生未预期错误 {filepath}: {e}", exc_info=True)
        return 0.0


def get_fps(filepath: str) -> float:
    """
    获取视频帧率

    Args:
        filepath: 视频文件路径

    Returns:
        帧率 (fps)
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            filepath,
        ]
        output = (
            subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=10)
            .decode("utf-8")
            .strip()
        )
        # 帧率格式可能是 "30/1" 或 "30000/1001"
        if "/" in output:
            num, den = output.split("/")
            return float(num) / float(den)
        return float(output)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, ZeroDivisionError) as e:
        # 默认 30fps，防止异常帧率影响限帧/码率决策
        logging.warning(f"无法获取帧率 {filepath}。错误: {e}")
        return 30.0
    except Exception as e:
        logging.error(f"获取帧率时发生未预期错误 {filepath}: {e}", exc_info=True)
        return 30.0


def get_audio_bitrate(filepath: str) -> Optional[int]:
    """
    获取文件第一条音频流的码率（bps）。

    说明：
    - 仅用于“音频目标码率”场景的预检查，避免源音频码率低于目标码率时反向增大体积。
    - 若无音频流或无法探测码率，返回 None。
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=bit_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            filepath,
        ]
        output = (
            subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=10)
            .decode("utf-8")
            .strip()
        )
        if not output or output.upper() == "N/A":
            return None
        return int(output)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as e:
        logging.debug(f"无法获取音频码率 {filepath}，将跳过按码率 copy 判断。错误: {e}")
        return None
    except Exception as e:
        logging.error(f"获取音频码率时发生未预期错误 {filepath}: {e}", exc_info=True)
        return None


def get_video_metadata_batch(filepath: str) -> Dict[str, Any]:
    """
    一次性获取所有视频元数据（性能优化：避免多次调用 ffprobe）

    Args:
        filepath: 视频文件路径

    Returns:
        包含所有元数据的字典:
        - bitrate: 码率（bps）
        - duration: 时长（秒）
        - width: 宽度
        - height: 高度
        - codec: 编码格式
        - fps: 帧率
        - audio_bitrate: 音频码率（bps），无音频时为 None
    """
    default_metadata = {
        "bitrate": 3000000,
        "duration": 0.0,
        "width": 1920,
        "height": 1080,
        "codec": "unknown",
        "fps": 30.0,
        "audio_bitrate": None,
    }

    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=bit_rate,duration:stream=codec_name,codec_type,width,height,r_frame_rate,bit_rate",
            "-of",
            "json",
            filepath,
        ]
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=10)
        data = json.loads(output.decode("utf-8"))

        # 解析视频流和音频流
        video_stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
            {},
        )
        audio_stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
            {},
        )
        format_info = data.get("format", {})

        # 计算帧率
        fps_str = video_stream.get("r_frame_rate", "30/1")
        if "/" in fps_str:
            try:
                num, den = map(float, fps_str.split("/"))
                fps = num / den if den != 0 else 30.0
            except (ValueError, ZeroDivisionError):
                fps = 30.0
        else:
            try:
                fps = float(fps_str)
            except ValueError:
                fps = 30.0

        # 构建元数据字典
        metadata = {
            "bitrate": int(format_info.get("bit_rate", default_metadata["bitrate"])),
            "duration": float(format_info.get("duration", default_metadata["duration"])),
            "width": int(video_stream.get("width", default_metadata["width"])),
            "height": int(video_stream.get("height", default_metadata["height"])),
            "codec": video_stream.get("codec_name", default_metadata["codec"]),
            "fps": fps,
            "audio_bitrate": (
                int(audio_stream.get("bit_rate", 0)) if audio_stream.get("bit_rate") else None
            ),
        }

        logging.debug(f"获取视频元数据成功 {filepath}: {metadata}")
        return metadata

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logging.warning(f"获取视频元数据失败 {filepath}，使用默认值。错误: {e}")
        return default_metadata
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        logging.warning(f"解析视频元数据失败 {filepath}，使用默认值。错误: {e}")
        return default_metadata
    except Exception as e:
        logging.error(f"获取视频元数据时发生未预期错误 {filepath}: {e}", exc_info=True)
        return default_metadata
