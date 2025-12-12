#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
默认配置常量

定义程序的默认配置值和编码器映射表
"""

# ============================================================
# 路径配置
# ============================================================
DEFAULT_INPUT_FOLDER = "./input"
DEFAULT_OUTPUT_FOLDER = "./output"
DEFAULT_LOG_FOLDER = "./logs"

# ============================================================
# 码率配置
# ============================================================
MIN_BITRATE = 500000  # 最小码率 500kbps
BITRATE_RATIO = 0.5  # 压缩比例

# 根据分辨率的最大码率封顶（bps）
# 键为短边像素数，值为最大码率
MAX_BITRATE_BY_RESOLUTION = {
    720: 1500000,  # 720p: 1.5 Mbps
    1080: 3000000,  # 1080p: 3 Mbps
    1440: 5000000,  # 1440p (2K): 5 Mbps
    2160: 9000000,  # 4K: 9 Mbps
}

# ============================================================
# 音频配置
# ============================================================
AUDIO_BITRATE = "128k"

# ============================================================
# 文件配置
# ============================================================
MIN_FILE_SIZE_MB = 100
KEEP_STRUCTURE_FLAG = True

# ============================================================
# 并发配置
# ============================================================
MAX_WORKERS = 3

# ============================================================
# 帧率配置
# ============================================================
MAX_FPS = 30
LIMIT_FPS_ON_SOFTWARE_DECODE = True
LIMIT_FPS_ON_SOFTWARE_ENCODE = True

# ============================================================
# 硬件加速配置
# ============================================================
DEFAULT_HW_ACCEL = "auto"
DEFAULT_OUTPUT_CODEC = "hevc"

# ============================================================
# 硬件编码器映射表
# ============================================================
HW_ENCODERS = {
    # NVIDIA NVENC
    "nvenc": {
        "hevc": "hevc_nvenc",
        "avc": "h264_nvenc",
        "av1": "av1_nvenc",
        "hwaccel": "cuda",
        "hwaccel_output_format": "cuda",
    },
    # Apple VideoToolbox
    "videotoolbox": {
        "hevc": "hevc_videotoolbox",
        "avc": "h264_videotoolbox",
        "av1": None,  # VideoToolbox 暂不支持 AV1
        "hwaccel": "videotoolbox",
        "hwaccel_output_format": None,
    },
    # Intel Quick Sync Video
    "qsv": {
        "hevc": "hevc_qsv",
        "avc": "h264_qsv",
        "av1": "av1_qsv",
        "hwaccel": "qsv",
        "hwaccel_output_format": "qsv",
    },
}

# ============================================================
# 软件编码器映射表
# ============================================================
SW_ENCODERS = {
    "hevc": "libx265",
    "avc": "libx264",
    "av1": "libsvtav1",
}

# ============================================================
# 支持的视频格式
# ============================================================
SUPPORTED_VIDEO_EXTENSIONS = (
    ".mp4",
    ".mkv",
    ".ts",
    ".avi",
    ".rm",
    ".rmvb",
    ".wmv",
    ".m2ts",
    ".mpeg",
    ".mpg",
    ".mov",
    ".flv",
    ".3gp",
    ".webm",
    ".m4v",
    ".vob",
    ".ogv",
    ".f4v",
)

# ============================================================
# 返回值常量
# ============================================================
RESULT_SUCCESS = "SUCCESS"
RESULT_SKIP_SIZE = "SKIP_SIZE"
RESULT_SKIP_EXISTS = "SKIP_EXISTS"
RESULT_ERROR = "ERROR"

# ============================================================
# 默认配置字典（用于配置加载）
# ============================================================
DEFAULT_CONFIG = {
    "paths": {
        "input": DEFAULT_INPUT_FOLDER,
        "output": DEFAULT_OUTPUT_FOLDER,
        "log": DEFAULT_LOG_FOLDER,
    },
    "logging": {
        "level": "INFO",
        "plain": False,
        "json_console": False,
        "show_progress": True,
        "print_cmd": False,
    },
    "encoding": {
        "codec": DEFAULT_OUTPUT_CODEC,
        "audio_bitrate": AUDIO_BITRATE,
        # 音频处理高级配置（可选）
        # 不配置时，默认行为与旧版一致：第一音轨 → AAC@audio_bitrate，且不保留字幕
        "audio": {
            "enabled": True,
            "target_codec": "aac",
            "target_bitrate": None,  # None 表示沿用 audio_bitrate
            "channels": "keep",  # keep|stereo|mono|5.1
            "sample_rate": "keep",  # keep|44100|48000
            "copy_policy": "off",  # off|aac_only|smart|always
            "copy_allow_codecs": ["aac", "mp3"],
            "copy_max_bitrate_ratio": 1.0,
            "aac_adtstoasc": True,
                "tracks": {
                    "keep": "first",  # first|all|language_prefer
                    "prefer_language": ["zho", "chi", "eng"],
                    "drop_commentary": False,
                },
            },
        # 字幕处理高级配置（可选）
        "subtitles": {
            "keep": "none",  # none|mov_text|copy
            "languages": ["zho", "eng"],
        },
        "bitrate": {
            "forced": 0,
            "ratio": BITRATE_RATIO,
            "min": MIN_BITRATE,
            "max_by_resolution": MAX_BITRATE_BY_RESOLUTION,
        },
    },
    "fps": {
        "max": MAX_FPS,
        "limit_on_software_decode": LIMIT_FPS_ON_SOFTWARE_DECODE,
        "limit_on_software_encode": LIMIT_FPS_ON_SOFTWARE_ENCODE,
    },
    "encoders": {
        "nvenc": {
            "enabled": True,
            "max_concurrent": 3,
        },
        "qsv": {
            "enabled": True,
            "max_concurrent": 2,
        },
        "videotoolbox": {
            "enabled": False,
            "max_concurrent": 3,
        },
        "cpu": {
            "enabled": True,
            "max_concurrent": 4,
            "preset": "medium",
        },
    },
    "scheduler": {
        "max_total_concurrent": 5,
    },
    "files": {
        "min_size_mb": MIN_FILE_SIZE_MB,
        "keep_structure": KEEP_STRUCTURE_FLAG,
        "skip_existing": True,
    },
}
