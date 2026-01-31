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
from typing import Dict, Any, Optional, Tuple, List

from src.config.defaults import (
    DEFAULT_CONFIG,
    DEFAULT_INPUT_FOLDER,
    DEFAULT_OUTPUT_FOLDER,
    DEFAULT_LOG_FOLDER,
    DEFAULT_OUTPUT_CODEC,
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
        
    Raises:
        ValueError: 如果配置验证失败
    """
    # 使用默认配置
    config = copy.deepcopy(DEFAULT_CONFIG)

    # 查找配置文件
    if config_path is None:
        config_path = find_default_config()

    if config_path and os.path.exists(config_path):
        if not YAML_AVAILABLE:
            logging.warning(
                "未安装 PyYAML，无法加载配置文件。请运行: pip install pyyaml"
            )
            return config

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                file_config = yaml.safe_load(f) or {}
            logging.info(f"已加载配置文件: {config_path}")
            merged_config = deep_merge(config, file_config)
            
            # 验证配置
            is_valid, errors = validate_config(merged_config)
            if not is_valid:
                logging.error("配置验证失败:")
                for error in errors:
                    logging.error(f"  - {error}")
                raise ValueError(f"配置文件验证失败: {'; '.join(errors)}")
            
            return merged_config
        except yaml.YAMLError as e:
            logging.error(f"YAML 解析失败: {e}，使用默认配置")
            return config
        except ValueError:
            raise  # 重新抛出验证错误
        except Exception as e:
            logging.warning(f"加载配置文件失败: {e}，使用默认配置")
            return config

    return config


def validate_config(config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    验证配置项的合法性

    Args:
        config: 配置字典

    Returns:
        (是否有效, 错误列表)
    """
    errors = []

    # 验证路径配置
    paths = config.get("paths", {})
    for key in ["input", "output", "log"]:
        path = paths.get(key)
        if not path or not isinstance(path, str):
            errors.append(f"paths.{key} 必须是非空字符串")
        elif not path.strip():
            errors.append(f"paths.{key} 不能只包含空白字符")

    # 验证编码器配置
    encoders = config.get("encoders", {})
    for enc_name in ["nvenc", "qsv", "videotoolbox", "cpu"]:
        enc_config = encoders.get(enc_name, {})
        if not isinstance(enc_config, dict):
            errors.append(f"encoders.{enc_name} 必须是字典类型")
            continue
        
        # 验证并发数
        max_concurrent = enc_config.get("max_concurrent")
        if max_concurrent is not None:
            if not isinstance(max_concurrent, int):
                errors.append(f"encoders.{enc_name}.max_concurrent 必须是整数")
            elif max_concurrent < 1 or max_concurrent > 100:
                errors.append(f"encoders.{enc_name}.max_concurrent 必须在 1-100 之间")

    # 验证调度器配置
    scheduler = config.get("scheduler", {})
    max_total = scheduler.get("max_total_concurrent")
    if max_total is not None:
        if not isinstance(max_total, int):
            errors.append("scheduler.max_total_concurrent 必须是整数")
        elif max_total < 1 or max_total > 100:
            errors.append("scheduler.max_total_concurrent 必须在 1-100 之间")

    # 验证编码配置
    encoding = config.get("encoding", {})
    codec = encoding.get("codec")
    if codec and codec not in ["hevc", "avc", "av1"]:
        errors.append(f"encoding.codec 必须是 hevc, avc 或 av1，当前值: {codec}")
    
    bitrate_cfg = encoding.get("bitrate", {})
    forced_bitrate = bitrate_cfg.get("forced")
    if forced_bitrate is not None:
        if not isinstance(forced_bitrate, int):
            errors.append("encoding.bitrate.forced 必须是整数")
        elif forced_bitrate < 0:
            errors.append("encoding.bitrate.forced 不能为负数")

    # 验证帧率配置
    fps_cfg = config.get("fps", {})
    max_fps = fps_cfg.get("max")
    if max_fps is not None:
        if not isinstance(max_fps, int):
            errors.append("fps.max 必须是整数")
        elif max_fps < 1 or max_fps > 240:
            errors.append("fps.max 必须在 1-240 之间")

    # 验证文件配置
    files_cfg = config.get("files", {})
    min_size = files_cfg.get("min_size_mb")
    if min_size is not None:
        if not isinstance(min_size, (int, float)):
            errors.append("files.min_size_mb 必须是数字")
        elif min_size < 0:
            errors.append("files.min_size_mb 不能为负数")

    return len(errors) == 0, errors


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
    if hasattr(args, "input") and args.input != DEFAULT_INPUT_FOLDER:
        config["paths"]["input"] = args.input
    if hasattr(args, "output") and args.output != DEFAULT_OUTPUT_FOLDER:
        config["paths"]["output"] = args.output
    if hasattr(args, "log") and args.log != DEFAULT_LOG_FOLDER:
        config["paths"]["log"] = args.log

    # 编码覆盖
    if hasattr(args, "codec") and args.codec != DEFAULT_OUTPUT_CODEC:
        config["encoding"]["codec"] = args.codec
    if hasattr(args, "force_bitrate") and args.force_bitrate > 0:
        config["encoding"]["bitrate"]["forced"] = args.force_bitrate

    # 帧率覆盖
    if hasattr(args, "max_fps") and args.max_fps != MAX_FPS:
        config["fps"]["max"] = args.max_fps
    if hasattr(args, "no_fps_limit") and args.no_fps_limit:
        config["fps"]["limit_on_software_decode"] = False
        config["fps"]["limit_on_software_encode"] = False
    if hasattr(args, "no_fps_limit_decode") and args.no_fps_limit_decode:
        config["fps"]["limit_on_software_decode"] = False
    if hasattr(args, "no_fps_limit_encode") and args.no_fps_limit_encode:
        config["fps"]["limit_on_software_encode"] = False

    # 文件处理覆盖
    if hasattr(args, "min_size") and args.min_size != MIN_FILE_SIZE_MB:
        config["files"]["min_size_mb"] = args.min_size
    if hasattr(args, "no_keep_structure") and args.no_keep_structure:
        config["files"]["keep_structure"] = False

    # 调度器覆盖
    if hasattr(args, "max_concurrent") and args.max_concurrent != 5:
        config["scheduler"]["max_total_concurrent"] = args.max_concurrent

    # 运行模式覆盖
    if hasattr(args, "dry_run"):
        config["dry_run"] = args.dry_run
    else:
        config["dry_run"] = False

    # 日志/控制台输出
    config.setdefault("logging", {})
    log_cfg = config["logging"]

    if hasattr(args, "verbose") and args.verbose:
        log_cfg["level"] = "DEBUG"
    if hasattr(args, "quiet") and args.quiet:
        log_cfg["level"] = "WARNING" if args.quiet == 1 else "ERROR"
    if hasattr(args, "plain") and args.plain:
        log_cfg["plain"] = True
    if hasattr(args, "json_logs") and args.json_logs:
        log_cfg["json_console"] = True
    if hasattr(args, "no_progress") and args.no_progress:
        log_cfg["show_progress"] = False
    if hasattr(args, "print_cmd") and args.print_cmd:
        log_cfg["print_cmd"] = True

    return config
