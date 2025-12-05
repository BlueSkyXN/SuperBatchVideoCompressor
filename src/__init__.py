# SBVC - 超级批量视频压缩器
"""
SBVC (Super Batch Video Compressor) 包

主要模块:
- config: 配置加载
- core: 核心编码逻辑
- scheduler: 多编码器调度
- utils: 工具函数
"""

__version__ = "2.2.0"
__author__ = "BlueSkyXN"

from src.config import load_config, apply_cli_overrides
from src.core import get_video_files, resolve_output_paths
from src.scheduler import AdvancedScheduler, create_advanced_scheduler

__all__ = [
    "__version__",
    "load_config",
    "apply_cli_overrides",
    "get_video_files",
    "resolve_output_paths",
    "AdvancedScheduler",
    "create_advanced_scheduler",
]
