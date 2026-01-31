#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FFmpeg 编码器模块

构建和执行 FFmpeg 编码命令
"""

import subprocess
import logging
from typing import Dict, Any, Tuple, Optional, List

from src.config.defaults import (
    HW_ENCODERS,
    SW_ENCODERS,
    AUDIO_BITRATE,
    MIN_BITRATE,
    BITRATE_RATIO,
)


def parse_bitrate_to_bps(value: Any) -> Optional[int]:
    """
    将 FFmpeg 风格的码率值解析为 bps（bit/s）。

    支持示例：
    - "128k" / "128kbps"
    - "1M"
    - "64000"
    - 128000

    无法解析或未设置时返回 None。
    """
    if value is None or value is False or value is True:
        return None

    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    text = str(value).strip()
    if not text:
        return None

    lowered = text.lower().replace(" ", "")
    if lowered in ("null", "none"):
        return None

    if lowered.endswith("bps"):
        lowered = lowered[:-3]

    multiplier = 1
    if lowered.endswith("k"):
        multiplier = 1000
        lowered = lowered[:-1]
    elif lowered.endswith("m"):
        multiplier = 1000_000
        lowered = lowered[:-1]
    elif lowered.endswith("g"):
        multiplier = 1000_000_000
        lowered = lowered[:-1]

    try:
        return int(float(lowered) * multiplier)
    except ValueError:
        return None


def execute_ffmpeg(cmd: list, duration: float = 0.0) -> Tuple[bool, str]:
    """
    执行 FFmpeg 命令并检查错误

    Args:
        cmd: FFmpeg 命令列表
        duration: 视频时长（秒），用于计算超时

    Returns:
        (成功标志, 错误信息)
    """
    from src.utils.process import (
        register_process,
        unregister_process,
        is_shutdown_requested,
    )

    if is_shutdown_requested():
        return False, "程序正在退出"

    # 打印完整的 ffmpeg 命令（便于调试）
    cmd_str = " ".join(f'"{arg}"' if " " in str(arg) else str(arg) for arg in cmd)
    logging.debug(f"FFmpeg 命令: {cmd_str}")

    # 根据视频时长计算合理超时（假设编码速度至少 0.1x）
    # 即10分钟视频最多编码100分钟
    min_timeout = 300  # 最少5分钟
    max_timeout = 7200  # 最多2小时
    if duration > 0:
        timeout = max(min_timeout, min(duration * 10, max_timeout))
    else:
        timeout = 3600  # 默认1小时

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace",
        )
        register_process(process)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            unregister_process(process)
            return False, f"编码超时（{timeout:.0f}秒），可能文件过大或系统过载"
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
            # 其他未知错误，返回摘要而非完整错误（防止信息泄露）
            if len(stderr) > 500:
                return False, "编码失败，请查看详细日志"
            return False, stderr

        return True, None
    except Exception as e:
        return False, str(e)


def calculate_target_bitrate(
    original_bitrate: int,
    width: int,
    height: int,
    force_bitrate: bool = False,
    forced_value: int = 0,
    max_bitrate_by_resolution: dict = None,
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

# 按编码器分类的硬件解码支持列表
# 策略：列出每个编码器理论上支持的格式，尝试硬解失败时调度器会自动回退到软解
SUPPORTED_HW_DECODE_CODECS = {
    # NVIDIA NVENC 支持的硬件解码格式
    "nvenc": [
        "h264",  # H.264/AVC - 完全支持
        "hevc",  # HEVC/H.265 - 完全支持
        "av1",  # AV1 - RTX 30 系及以上支持
        "vp9",  # VP9 - 部分支持
        "vp8",  # VP8 - 部分支持
        "mpeg2video",  # MPEG-2 - 支持
        "mpeg4",  # MPEG-4 Part 2 - 尝试（可能失败）
    ],
    # Intel QSV 支持的硬件解码格式
    "qsv": [
        "h264",  # H.264/AVC - 完全支持
        "hevc",  # HEVC/H.265 - 完全支持
        "av1",  # AV1 - 11代酷睿及以上支持
        "vp9",  # VP9 - 支持
        "vp8",  # VP8 - 支持
        "mpeg2video",  # MPEG-2 - 完全支持
        "vc1",  # VC-1 - 完全支持（WMV高级档次）
        "wmv3",  # WMV9/VC-1简单/主档次 - 完全支持
        "mjpeg",  # Motion JPEG - 支持
    ],
    # Apple VideoToolbox 支持的硬件解码格式
    "videotoolbox": [
        "h264",  # H.264/AVC - 完全支持
        "hevc",  # HEVC/H.265 - 完全支持
        "mpeg2video",  # MPEG-2 - 支持
        "mpeg4",  # MPEG-4 - 部分支持
        "mjpeg",  # Motion JPEG - 支持
        "prores",  # ProRes - 完全支持
    ],
}

# 向后兼容：保留旧的列表变量（取所有编码器支持格式的并集）
SUPPORTED_HW_DECODE_CODECS_LEGACY = list(
    set(codec for codecs in SUPPORTED_HW_DECODE_CODECS.values() for codec in codecs)
)

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
    max_fps: int = 30,
    audio_bitrate: Optional[str] = None,
    map_args: Optional[List[str]] = None,
    audio_args: Optional[List[str]] = None,
    subtitle_args: Optional[List[str]] = None,
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
    if audio_bitrate is None:
        audio_bitrate = AUDIO_BITRATE

    hw_config = HW_ENCODERS.get(hw_accel, {})
    hw_encoder = hw_config.get(output_codec)

    if not hw_encoder:
        return None

    hw_display = ENCODER_DISPLAY_NAMES.get(hw_accel, hw_accel)
    codec_display = CODEC_DISPLAY_NAMES.get(output_codec, output_codec.upper())

    # 获取该编码器支持的硬件解码格式列表
    supported_codecs = SUPPORTED_HW_DECODE_CODECS.get(hw_accel, [])

    cmd = ["ffmpeg", "-y", "-hide_banner"]

    # 硬解模式：检查源编码是否在该编码器的支持列表中
    if use_hw_decode and source_codec in supported_codecs:
        hwaccel = hw_config.get("hwaccel")
        hwaccel_output_format = hw_config.get("hwaccel_output_format")

        if hwaccel:
            logging.debug(
                f"尝试硬解: {hw_accel} 编码器支持 {source_codec} 格式的硬件解码"
            )
            cmd.extend(["-hwaccel", hwaccel])
            if hwaccel_output_format:
                cmd.extend(["-hwaccel_output_format", hwaccel_output_format])
            cmd.extend(["-i", filepath])
            if map_args:
                cmd.extend(map_args)
            cmd.extend(["-c:v", hw_encoder, "-b:v", str(bitrate)])
            if audio_args is not None:
                cmd.extend(audio_args)
            else:
                cmd.extend(["-c:a", "aac", "-b:a", audio_bitrate])
            if subtitle_args:
                cmd.extend(subtitle_args)
            cmd.append(temp_filename)
            return {
                "name": f"{hw_display} ({codec_display}, 硬解+硬编)",
                "cmd": cmd,
                "encoder": hw_accel,
            }
    elif use_hw_decode:
        logging.debug(
            f"跳过硬解: {hw_accel} 编码器不支持 {source_codec} 格式的硬件解码，"
            f"支持的格式: {', '.join(supported_codecs)}"
        )

    # 软解模式（硬解不支持或未启用）
    cmd = ["ffmpeg", "-y", "-hide_banner", "-i", filepath]
    if map_args:
        cmd.extend(map_args)

    if limit_fps:
        cmd.extend(["-vf", f"fps={max_fps}"])
        name = f"{hw_display} ({codec_display}, 软解+硬编, 限{max_fps}fps)"
    else:
        name = f"{hw_display} ({codec_display}, 软解+硬编)"

    cmd.extend(["-c:v", hw_encoder, "-b:v", str(bitrate)])
    if audio_args is not None:
        cmd.extend(audio_args)
    else:
        cmd.extend(["-c:a", "aac", "-b:a", audio_bitrate])
    if subtitle_args:
        cmd.extend(subtitle_args)
    cmd.append(temp_filename)

    return {"name": name, "cmd": cmd, "encoder": hw_accel}


def build_sw_encode_command(
    filepath: str,
    temp_filename: str,
    bitrate: int,
    output_codec: str = "hevc",
    limit_fps: bool = False,
    max_fps: int = 30,
    preset: str = "medium",
    audio_bitrate: Optional[str] = None,
    map_args: Optional[List[str]] = None,
    audio_args: Optional[List[str]] = None,
    subtitle_args: Optional[List[str]] = None,
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
    if audio_bitrate is None:
        audio_bitrate = AUDIO_BITRATE

    sw_encoder = SW_ENCODERS.get(output_codec, "libx264")

    cmd = ["ffmpeg", "-y", "-hide_banner", "-i", filepath]
    if map_args:
        cmd.extend(map_args)

    if limit_fps:
        cmd.extend(["-vf", f"fps={max_fps}"])
        name = f"CPU ({sw_encoder}, 限{max_fps}fps)"
    else:
        name = f"CPU ({sw_encoder})"

    cmd.extend(["-c:v", sw_encoder])

    # 编码器特定参数
    if sw_encoder in ("libx265", "libx264"):
        cmd.extend(["-preset", preset])
    elif sw_encoder == "libsvtav1":
        cmd.extend(["-preset", "6"])

    cmd.extend(["-b:v", str(bitrate)])
    if audio_args is not None:
        cmd.extend(audio_args)
    else:
        cmd.extend(["-c:a", "aac", "-b:a", audio_bitrate])
    if subtitle_args:
        cmd.extend(subtitle_args)
    cmd.append(temp_filename)

    return {"name": name, "cmd": cmd, "encoder": "cpu"}
