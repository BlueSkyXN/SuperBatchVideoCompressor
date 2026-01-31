# 核心模块
"""视频处理核心功能"""

from src.core.video import (
    get_bitrate,
    get_resolution,
    get_codec,
    get_video_metadata_batch,
)
from src.core.encoder import (
    execute_ffmpeg,
    calculate_target_bitrate,
    build_hw_encode_command,
    build_sw_encode_command,
    SUPPORTED_HW_DECODE_CODECS,
    ENCODER_DISPLAY_NAMES,
    CODEC_DISPLAY_NAMES,
)
from src.core.compressor import get_video_files, resolve_output_paths

__all__ = [
    "get_bitrate",
    "get_resolution",
    "get_codec",
    "get_video_metadata_batch",
    "calculate_target_bitrate",
    "execute_ffmpeg",
    "build_hw_encode_command",
    "build_sw_encode_command",
    "SUPPORTED_HW_DECODE_CODECS",
    "ENCODER_DISPLAY_NAMES",
    "CODEC_DISPLAY_NAMES",
    "get_video_files",
    "resolve_output_paths",
]
