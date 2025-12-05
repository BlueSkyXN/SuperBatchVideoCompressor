# 工具模块
"""通用工具函数"""

from src.utils.logging import setup_logging
from src.utils.files import get_video_files, detect_hw_accel, get_hw_accel_type
from src.utils.encoder_check import (
    detect_available_encoders,
    check_nvenc_available,
    check_qsv_available,
    check_videotoolbox_available,
    check_cpu_available,
    print_encoder_status,
)
from src.utils.process import (
    register_process,
    unregister_process,
    is_shutdown_requested,
    terminate_all_ffmpeg,
    cleanup_temp_files,
    cleanup_pycache,
    setup_signal_handlers,
)

__all__ = [
    "setup_logging",
    "get_video_files",
    "detect_hw_accel",
    "get_hw_accel_type",
    "detect_available_encoders",
    "check_nvenc_available",
    "check_qsv_available",
    "check_videotoolbox_available",
    "check_cpu_available",
    "print_encoder_status",
    "register_process",
    "unregister_process",
    "is_shutdown_requested",
    "terminate_all_ffmpeg",
    "cleanup_temp_files",
    "cleanup_pycache",
    "setup_signal_handlers",
]
