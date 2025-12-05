#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FFmpeg 编码器模块

构建和执行 FFmpeg 编码命令
"""

import subprocess
import logging
from typing import List, Dict, Any, Tuple

from src.config.defaults import (
    HW_ENCODERS,
    SW_ENCODERS,
    AUDIO_BITRATE,
    MIN_BITRATE,
    BITRATE_RATIO,
)


def execute_ffmpeg(cmd: list) -> Tuple[bool, str]:
    """
    执行 FFmpeg 命令并检查错误
    
    Args:
        cmd: FFmpeg 命令列表
        
    Returns:
        (成功标志, 错误信息)
    """
    from src.utils.process import register_process, unregister_process, is_shutdown_requested
    
    if is_shutdown_requested():
        return False, "程序正在退出"
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace"
        )
        register_process(process)
        try:
            stdout, stderr = process.communicate()
        finally:
            unregister_process(process)
        
        # 检查是否有特定错误模式
        known_errors = [
            "Impossible to convert between the formats",
            "No such filter:",
            "Unknown encoder",
            "Cannot load nvcuda.dll",
            "No NVENC capable devices found",
            "Cannot load",
            "Driver does not support",
        ]
        
        if process.returncode != 0:
            for error_pattern in known_errors:
                if error_pattern in stderr:
                    return False, error_pattern
            # 其他未知错误
            return False, stderr[-500:] if len(stderr) > 500 else stderr
        
        return True, None
    except Exception as e:
        return False, str(e)


def calculate_target_bitrate(
    original_bitrate: int,
    width: int,
    height: int,
    force_bitrate: bool = False,
    forced_value: int = 0,
    max_bitrate_by_resolution: dict = None
) -> int:
    """
    计算目标码率

    Args:
        original_bitrate: 原始码率
        width: 视频宽度
        height: 视频高度
        force_bitrate: 是否强制使用指定码率
        forced_value: 强制码率值
        max_bitrate_by_resolution: 根据分辨率的最大码率配置字典

    Returns:
        目标码率
    """
    if force_bitrate:
        return forced_value

    if max_bitrate_by_resolution is None:
        from src.config.defaults import MAX_BITRATE_BY_RESOLUTION
        max_bitrate_by_resolution = MAX_BITRATE_BY_RESOLUTION

    # 根据分辨率确定最大码率上限（短边分档封顶）
    short_side = min(width, height)

    max_bitrate = None
    for resolution_threshold in sorted(max_bitrate_by_resolution.keys()):
        if short_side <= resolution_threshold:
            max_bitrate = max_bitrate_by_resolution[resolution_threshold]
            break

    if max_bitrate is None and max_bitrate_by_resolution:
        max_bitrate = max_bitrate_by_resolution[max(max_bitrate_by_resolution.keys())]

    if max_bitrate is None:
        max_bitrate = 9000000

    # 自动码率 = 原始码率 * 压缩比例
    new_bitrate = int(original_bitrate * BITRATE_RATIO)

    # 在最低码率与分辨率封顶之间夹紧
    new_bitrate = max(MIN_BITRATE, min(new_bitrate, max_bitrate))

    return new_bitrate


# ============================================================
# 编码命令构建 - 统一接口
# ============================================================

# 支持硬件解码的编解码器
SUPPORTED_HW_DECODE_CODECS = ["h264", "hevc", "av1", "vp9", "mpeg2video"]

# 编码器友好名称
ENCODER_DISPLAY_NAMES = {
    "nvenc": "NVIDIA NVENC",
    "videotoolbox": "Apple VideoToolbox",
    "qsv": "Intel QSV",
    "cpu": "CPU",
    "none": "CPU",
}

# 编解码格式友好名称
CODEC_DISPLAY_NAMES = {
    "hevc": "HEVC",
    "avc": "H.264",
    "av1": "AV1",
}


def build_hw_encode_command(
    filepath: str,
    temp_filename: str,
    bitrate: int,
    source_codec: str,
    hw_accel: str,
    output_codec: str = "hevc",
    use_hw_decode: bool = True,
    limit_fps: bool = False,
    max_fps: int = 30
) -> Dict[str, Any]:
    """
    构建硬件编码命令
    
    Args:
        filepath: 输入文件路径
        temp_filename: 临时输出文件路径
        bitrate: 目标码率
        source_codec: 源视频编码格式
        hw_accel: 硬件加速类型 (nvenc/qsv/videotoolbox)
        output_codec: 输出视频编码格式
        use_hw_decode: 是否使用硬件解码
        limit_fps: 是否限制帧率（仅软解时有效）
        max_fps: 最大帧率
        
    Returns:
        {"name": str, "cmd": list, "encoder": str} 或 None（如果不支持）
    """
    hw_config = HW_ENCODERS.get(hw_accel, {})
    hw_encoder = hw_config.get(output_codec)
    
    if not hw_encoder:
        return None
    
    hw_display = ENCODER_DISPLAY_NAMES.get(hw_accel, hw_accel)
    codec_display = CODEC_DISPLAY_NAMES.get(output_codec, output_codec.upper())
    
    cmd = ['ffmpeg', '-y', '-hide_banner']
    
    # 硬解模式
    if use_hw_decode and source_codec in SUPPORTED_HW_DECODE_CODECS:
        hwaccel = hw_config.get("hwaccel")
        hwaccel_output_format = hw_config.get("hwaccel_output_format")
        
        if hwaccel:
            cmd.extend(['-hwaccel', hwaccel])
            if hwaccel_output_format:
                cmd.extend(['-hwaccel_output_format', hwaccel_output_format])
            cmd.extend(['-i', filepath])
            cmd.extend(['-c:v', hw_encoder, '-b:v', str(bitrate)])
            cmd.extend(['-c:a', 'aac', '-b:a', AUDIO_BITRATE, temp_filename])
            return {
                "name": f"{hw_display} ({codec_display}, 硬解+硬编)",
                "cmd": cmd,
                "encoder": hw_accel
            }
    
    # 软解模式
    cmd = ['ffmpeg', '-y', '-hide_banner', '-i', filepath]
    
    if limit_fps:
        cmd.extend(['-vf', f'fps={max_fps}'])
        name = f"{hw_display} ({codec_display}, 软解+硬编, 限{max_fps}fps)"
    else:
        name = f"{hw_display} ({codec_display}, 软解+硬编)"
    
    cmd.extend(['-c:v', hw_encoder, '-b:v', str(bitrate)])
    cmd.extend(['-c:a', 'aac', '-b:a', AUDIO_BITRATE, temp_filename])
    
    return {"name": name, "cmd": cmd, "encoder": hw_accel}


def build_sw_encode_command(
    filepath: str,
    temp_filename: str,
    bitrate: int,
    output_codec: str = "hevc",
    limit_fps: bool = False,
    max_fps: int = 30,
    preset: str = "medium"
) -> Dict[str, Any]:
    """
    构建软件编码命令（CPU）
    
    Args:
        filepath: 输入文件路径
        temp_filename: 临时输出文件路径
        bitrate: 目标码率
        output_codec: 输出视频编码格式
        limit_fps: 是否限制帧率
        max_fps: 最大帧率
        preset: 编码预设
        
    Returns:
        {"name": str, "cmd": list, "encoder": str}
    """
    sw_encoder = SW_ENCODERS.get(output_codec, "libx264")
    
    cmd = ['ffmpeg', '-y', '-hide_banner', '-i', filepath]
    
    if limit_fps:
        cmd.extend(['-vf', f'fps={max_fps}'])
        name = f"CPU ({sw_encoder}, 限{max_fps}fps)"
    else:
        name = f"CPU ({sw_encoder})"
    
    cmd.extend(['-c:v', sw_encoder])
    
    # 编码器特定参数
    if sw_encoder in ("libx265", "libx264"):
        cmd.extend(['-preset', preset])
    elif sw_encoder == "libsvtav1":
        cmd.extend(['-preset', '6'])
    
    cmd.extend(['-b:v', str(bitrate), '-c:a', 'aac', '-b:a', AUDIO_BITRATE, temp_filename])
    
    return {"name": name, "cmd": cmd, "encoder": "cpu"}
