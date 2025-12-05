#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
编码器可用性检测

在程序启动时检测哪些硬件编码器真正可用
"""

import subprocess
import logging
import platform
from typing import Dict, List, Tuple

logger = logging.getLogger("EncoderCheck")


def check_encoder_available(encoder_name: str) -> Tuple[bool, str]:
    """
    检测单个编码器是否可用
    
    Args:
        encoder_name: ffmpeg 编码器名称 (如 hevc_nvenc, hevc_qsv)
    
    Returns:
        (是否可用, 错误信息)
    """
    try:
        # 使用 ffmpeg -encoders 查询
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if encoder_name in result.stdout:
            return True, ""
        else:
            return False, f"编码器 {encoder_name} 未在 ffmpeg 中找到"
            
    except FileNotFoundError:
        return False, "ffmpeg 未安装或不在 PATH 中"
    except subprocess.TimeoutExpired:
        return False, "ffmpeg 检测超时"
    except Exception as e:
        return False, f"检测失败: {e}"


def check_nvenc_available() -> Tuple[bool, str]:
    """
    检测 NVIDIA NVENC 是否可用
    
    检测方法:
    1. 检查 hevc_nvenc 编码器是否存在
    2. 尝试初始化 NVENC 硬件
    """
    # 先检查编码器是否存在
    available, error = check_encoder_available("hevc_nvenc")
    if not available:
        return False, error
    
    # 尝试初始化 NVENC
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
                "-c:v", "hevc_nvenc",
                "-f", "null", "-"
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        stderr = result.stderr.lower()
        
        # 检查常见错误
        if "no nvenc capable devices found" in stderr:
            return False, "未找到支持 NVENC 的 NVIDIA GPU"
        if "cannot load nvcuda.dll" in stderr:
            return False, "NVIDIA 驱动未安装或版本过低"
        if "cannot open" in stderr or "initialization failed" in stderr:
            return False, "NVENC 初始化失败"
        
        if result.returncode == 0:
            return True, ""
        else:
            return False, f"NVENC 测试失败: {result.stderr[:100]}"
            
    except subprocess.TimeoutExpired:
        return False, "NVENC 测试超时"
    except Exception as e:
        return False, f"NVENC 测试失败: {e}"


def check_qsv_available() -> Tuple[bool, str]:
    """
    检测 Intel QSV 是否可用
    
    检测方法:
    1. 检查 hevc_qsv 编码器是否存在
    2. 尝试初始化 QSV 硬件
    """
    available, error = check_encoder_available("hevc_qsv")
    if not available:
        return False, error
    
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
                "-c:v", "hevc_qsv",
                "-f", "null", "-"
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        stderr = result.stderr.lower()
        
        if "cannot open" in stderr or "initialization failed" in stderr:
            return False, "QSV 初始化失败，可能缺少 Intel GPU 或驱动"
        if "no qsv-capable device" in stderr:
            return False, "未找到支持 QSV 的 Intel GPU"
        
        if result.returncode == 0:
            return True, ""
        else:
            return False, f"QSV 测试失败: {result.stderr[:100]}"
            
    except subprocess.TimeoutExpired:
        return False, "QSV 测试超时"
    except Exception as e:
        return False, f"QSV 测试失败: {e}"


def check_videotoolbox_available() -> Tuple[bool, str]:
    """
    检测 Apple VideoToolbox 是否可用
    
    仅在 macOS 上可用
    """
    if platform.system() != "Darwin":
        return False, "VideoToolbox 仅在 macOS 上可用"
    
    available, error = check_encoder_available("hevc_videotoolbox")
    if not available:
        return False, error
    
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
                "-c:v", "hevc_videotoolbox",
                "-f", "null", "-"
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            return True, ""
        else:
            return False, f"VideoToolbox 测试失败: {result.stderr[:100]}"
            
    except subprocess.TimeoutExpired:
        return False, "VideoToolbox 测试超时"
    except Exception as e:
        return False, f"VideoToolbox 测试失败: {e}"


def check_cpu_available() -> Tuple[bool, str]:
    """
    检测 CPU 软编码是否可用
    
    理论上只要有 ffmpeg 就可用
    """
    available, error = check_encoder_available("libx265")
    if not available:
        # 回退检查 libx264
        available, error = check_encoder_available("libx264")
        if not available:
            return False, "软件编码器 (libx265/libx264) 不可用"
    
    return True, ""


def detect_available_encoders(encoder_configs: Dict[str, dict]) -> Dict[str, dict]:
    """
    检测所有启用的编码器，返回实际可用的配置
    
    Args:
        encoder_configs: 原始编码器配置
        
    Returns:
        更新后的编码器配置（不可用的会被禁用）
    """
    check_funcs = {
        "nvenc": check_nvenc_available,
        "qsv": check_qsv_available,
        "videotoolbox": check_videotoolbox_available,
        "cpu": check_cpu_available,
    }
    
    result = {}
    
    for name, config in encoder_configs.items():
        result[name] = config.copy()
        
        if not config.get("enabled", False):
            continue
        
        check_func = check_funcs.get(name)
        if not check_func:
            logger.warning(f"未知编码器类型: {name}")
            continue
        
        available, error = check_func()
        
        if available:
            logger.info(f"✓ {name.upper()} 可用")
        else:
            logger.warning(f"✗ {name.upper()} 不可用: {error}")
            result[name]["enabled"] = False
            result[name]["unavailable_reason"] = error
    
    return result


def print_encoder_status(encoder_configs: Dict[str, dict]) -> None:
    """打印编码器状态摘要"""
    hw_available = []
    hw_unavailable = []
    cpu_available = False
    
    for name, config in encoder_configs.items():
        if name == "cpu":
            cpu_available = config.get("enabled", False)
            continue
        
        if config.get("enabled", False):
            hw_available.append(name.upper())
        elif "unavailable_reason" in config:
            hw_unavailable.append(f"{name.upper()}: {config['unavailable_reason']}")
    
    print("=" * 60)
    print("编码器检测结果")
    print("=" * 60)
    
    if hw_available:
        print(f"可用硬件编码器: {', '.join(hw_available)}")
    else:
        print("可用硬件编码器: 无")
    
    if hw_unavailable:
        print("不可用:")
        for item in hw_unavailable:
            print(f"  - {item}")
    
    print(f"CPU 兜底: {'启用' if cpu_available else '禁用'}")
    print("=" * 60)
