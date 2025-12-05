#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置加载器

支持从 YAML 文件加载配置，并实现配置优先级合并
优先级: 命令行参数 > 配置文件 > 程序默认值
"""

import os
import logging
import copy
from pathlib import Path
from typing import Dict, Any, Optional

from src.config.defaults import (
    DEFAULT_CONFIG,
    DEFAULT_INPUT_FOLDER,
    DEFAULT_OUTPUT_FOLDER,
    DEFAULT_LOG_FOLDER,
    DEFAULT_OUTPUT_CODEC,
    DEFAULT_HW_ACCEL,
    MAX_FPS,
    MIN_FILE_SIZE_MB,
)

# 尝试导入 YAML 支持
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


def find_default_config() -> Optional[str]:
    """
    查找默认配置文件
    
    按以下顺序查找:
    1. 程序同目录下的 config.yaml
    2. 用户目录下的 .sbvc/config.yaml
    
    Returns:
        找到的配置文件路径，如果没找到返回 None
    """
    # 程序同目录（项目根目录）
    script_dir = Path(__file__).parent.parent.parent
    local_config = script_dir / "config.yaml"
    if local_config.exists():
        return str(local_config)
    
    # 用户目录
    home_config = Path.home() / ".sbvc" / "config.yaml"
    if home_config.exists():
        return str(home_config)
    
    return None


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    深度合并两个字典，override 中的值会覆盖 base 中的值
    
    Args:
        base: 基础字典
        override: 覆盖字典
        
    Returns:
        合并后的字典
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    加载配置文件
    
    Args:
        config_path: 配置文件路径，如果为 None 则使用默认路径
        
    Returns:
        配置字典
    """
    # 使用默认配置
    config = copy.deepcopy(DEFAULT_CONFIG)
    
    # 查找配置文件
    if config_path is None:
        config_path = find_default_config()
    
    if config_path and os.path.exists(config_path):
        if not YAML_AVAILABLE:
            logging.warning("未安装 PyYAML，无法加载配置文件。请运行: pip install pyyaml")
            return config
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                file_config = yaml.safe_load(f) or {}
            logging.info(f"已加载配置文件: {config_path}")
            return deep_merge(config, file_config)
        except Exception as e:
            logging.warning(f"加载配置文件失败: {e}，使用默认配置")
            return config
    
    return config


def apply_cli_overrides(config: Dict[str, Any], args) -> Dict[str, Any]:
    """
    将命令行参数覆盖到配置中
    
    优先级: 命令行参数 > 配置文件 > 程序默认值
    
    Args:
        config: 配置字典
        args: 命令行参数
        
    Returns:
        更新后的配置字典
    """
    # 路径覆盖
    if hasattr(args, 'input') and args.input != DEFAULT_INPUT_FOLDER:
        config["paths"]["input"] = args.input
    if hasattr(args, 'output') and args.output != DEFAULT_OUTPUT_FOLDER:
        config["paths"]["output"] = args.output
    if hasattr(args, 'log') and args.log != DEFAULT_LOG_FOLDER:
        config["paths"]["log"] = args.log
    
    # 编码覆盖
    if hasattr(args, 'codec') and args.codec != DEFAULT_OUTPUT_CODEC:
        config["encoding"]["codec"] = args.codec
    if hasattr(args, 'force_bitrate') and args.force_bitrate > 0:
        config["encoding"]["bitrate"]["forced"] = args.force_bitrate
    
    # 帧率覆盖
    if hasattr(args, 'max_fps') and args.max_fps != MAX_FPS:
        config["fps"]["max"] = args.max_fps
    if hasattr(args, 'no_fps_limit') and args.no_fps_limit:
        config["fps"]["limit_on_software_decode"] = False
        config["fps"]["limit_on_software_encode"] = False
    if hasattr(args, 'no_fps_limit_decode') and args.no_fps_limit_decode:
        config["fps"]["limit_on_software_decode"] = False
    if hasattr(args, 'no_fps_limit_encode') and args.no_fps_limit_encode:
        config["fps"]["limit_on_software_encode"] = False
    
    # 文件处理覆盖
    if hasattr(args, 'min_size') and args.min_size != MIN_FILE_SIZE_MB:
        config["files"]["min_size_mb"] = args.min_size
    if hasattr(args, 'no_keep_structure') and args.no_keep_structure:
        config["files"]["keep_structure"] = False
    
    # 调度器覆盖
    if hasattr(args, 'max_concurrent') and args.max_concurrent != 5:
        config["scheduler"]["max_total_concurrent"] = args.max_concurrent
    
    return config
