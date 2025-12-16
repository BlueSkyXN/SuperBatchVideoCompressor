#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频信息获取模块

提供获取视频元数据的功能
"""

import subprocess
import logging
from typing import Optional


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
            subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
            .decode("utf-8")
            .strip()
        )
        return int(output)
    except Exception as e:
        logging.warning(f"无法获取码率 {filepath}，使用默认值 3Mbps。错误: {e}")
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
            subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
            .decode("utf-8")
            .strip()
        )
        parts = output.split(",")
        return int(parts[0]), int(parts[1])
    except Exception as e:
        # 兜底到 1080p，避免分辨率缺失导致封顶不合理
        logging.warning(f"无法获取分辨率 {filepath}，使用默认值 1080p。错误: {e}")
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
            subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
            .decode("utf-8")
            .strip()
        )
        return output
    except Exception as e:
        logging.warning(f"无法获取编码格式 {filepath}。错误: {e}")
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
            subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
            .decode("utf-8")
            .strip()
        )
        return float(output)
    except Exception as e:
        logging.warning(f"无法获取时长 {filepath}。错误: {e}")
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
            subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
            .decode("utf-8")
            .strip()
        )
        # 帧率格式可能是 "30/1" 或 "30000/1001"
        if "/" in output:
            num, den = output.split("/")
            return float(num) / float(den)
        return float(output)
    except Exception as e:
        # 默认 30fps，防止异常帧率影响限帧/码率决策
        logging.warning(f"无法获取帧率 {filepath}。错误: {e}")
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
            subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
            .decode("utf-8")
            .strip()
        )
        if not output or output.upper() == "N/A":
            return None
        return int(output)
    except Exception as e:
        logging.debug(f"无法获取音频码率 {filepath}，将跳过按码率 copy 判断。错误: {e}")
        return None
