#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SBVC (Super Batch Video Compressor) - 超级批量视频压缩器

功能特性:
- 批量处理多种视频格式
- 智能码率计算（基于分辨率自动调整）
- NVIDIA GPU 硬件加速 (NVENC)
- 自动降级机制（GPU -> CPU 回退）
- 多线程并发处理
- 保持目录结构
- 详细的日志记录与进度显示
- 命令行参数支持
"""

import os
import sys
import subprocess
import concurrent.futures
import logging
import datetime
import argparse
from pathlib import Path

# ============================================================
# 默认配置（可通过命令行参数覆盖）
# ============================================================

# 路径配置
DEFAULT_INPUT_FOLDER = r"F:\lada\output"
DEFAULT_OUTPUT_FOLDER = r"F:\lada\pre"
DEFAULT_LOG_FOLDER = r"I:\BVC"

# 强制输出码率开关及赋值
FORCE_BITRATE_FLAG = False
FORCED_BITRATE = 8000000  # 单位：bps

# 保持文件关系的开关
KEEP_STRUCTURE_FLAG = True

# 定义跳过文件的大小阈值（以MB为单位）
MIN_FILE_SIZE_MB = 100

# 码率限制
MIN_BITRATE = 500000  # 最小码率 500kbps，防止质量过低
BITRATE_RATIO = 0.5   # 压缩比例

# 音频质量
AUDIO_BITRATE = "128k"

# 并发线程数
MAX_WORKERS = 3

# 软件编码回退开关（默认关闭，仅使用硬件编码）
ENABLE_SOFTWARE_ENCODING = False

# 帧率限制配置
MAX_FPS = 30  # 最大帧率
LIMIT_FPS_ON_SOFTWARE_DECODE = True   # 软件解码时限制帧率
LIMIT_FPS_ON_SOFTWARE_ENCODE = True   # 软件编码时限制帧率

# ============================================================
# 硬件加速配置
# ============================================================

# 硬件加速类型: auto, nvenc, videotoolbox, qsv, none
# - auto: 自动检测平台选择
# - nvenc: NVIDIA GPU (CUDA + NVENC)
# - videotoolbox: Apple Mac (VideoToolbox)
# - qsv: Intel 集成显卡 (Quick Sync Video)
# - none: 仅使用软件编码
DEFAULT_HW_ACCEL = "auto"

# 输出视频编码: hevc, avc, av1
# - hevc: H.265/HEVC (推荐，压缩率高)
# - avc: H.264/AVC (兼容性最好)
# - av1: AV1 (最新，压缩率最高，但编码较慢)
DEFAULT_OUTPUT_CODEC = "hevc"

# 硬件编码器映射表
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

# 软件编码器映射表
SW_ENCODERS = {
    "hevc": "libx265",
    "avc": "libx264",
    "av1": "libsvtav1",  # 或 libaom-av1，但 svtav1 更快
}

# 支持的视频格式
SUPPORTED_VIDEO_EXTENSIONS = (
    '.mp4', '.mkv', '.ts', '.avi', '.rm', '.rmvb', '.wmv', 
    '.m2ts', '.mpeg', '.mpg', '.mov', '.flv', '.3gp', 
    '.webm', '.m4v', '.vob', '.ogv', '.f4v'
)

# ============================================================
# 返回值常量
# ============================================================
RESULT_SUCCESS = None
RESULT_SKIP_SIZE = "SKIP_SIZE"
RESULT_SKIP_EXISTS = "SKIP_EXISTS"


# ============================================================
# 命令行参数解析
# ============================================================

def parse_arguments():
    """
    解析命令行参数
    
    使用示例:
        python SBVC.py -i /path/to/input -o /path/to/output
        python SBVC.py -i ./videos -o ./compressed --codec avc
        python SBVC.py -i ./input -o ./output --hw-accel videotoolbox
        python SBVC.py --help
    """
    parser = argparse.ArgumentParser(
        description='SBVC (Super Batch Video Compressor) - 超级批量视频压缩器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
使用示例:
  # 基本用法
  python SBVC.py -i /path/to/input -o /path/to/output
  
  # 使用 Mac VideoToolbox 硬件加速
  python SBVC.py -i ./input -o ./output --hw-accel videotoolbox
  
  # 使用 Intel QSV 硬件加速
  python SBVC.py -i ./input -o ./output --hw-accel qsv
  
  # 输出 H.264/AVC 编码（兼容性最好）
  python SBVC.py -i ./input -o ./output --codec avc
  
  # 输出 AV1 编码（压缩率最高）
  python SBVC.py -i ./input -o ./output --codec av1
  
  # 启用 CPU 编码回退
  python SBVC.py -i ./input -o ./output --cpu-fallback
  
  # 自定义帧率限制
  python SBVC.py -i ./input -o ./output --max-fps 24

硬件加速类型:
  auto         - 自动检测平台选择（默认）
  nvenc        - NVIDIA GPU (CUDA + NVENC)
  videotoolbox - Apple Mac (VideoToolbox)
  qsv          - Intel 集成显卡 (Quick Sync Video)
  none         - 仅使用软件编码

输出编码格式:
  hevc - H.265/HEVC（默认，压缩率高）
  avc  - H.264/AVC（兼容性最好）
  av1  - AV1（最新，压缩率最高，但编码较慢）
        '''
    )
    
    # ==================== 基本路径参数 ====================
    parser.add_argument('-i', '--input', 
                        default=DEFAULT_INPUT_FOLDER,
                        help=f'输入文件夹路径 (默认: {DEFAULT_INPUT_FOLDER})')
    
    parser.add_argument('-o', '--output',
                        default=DEFAULT_OUTPUT_FOLDER,
                        help=f'输出文件夹路径 (默认: {DEFAULT_OUTPUT_FOLDER})')
    
    parser.add_argument('-l', '--log',
                        default=DEFAULT_LOG_FOLDER,
                        help=f'日志文件夹路径 (默认: {DEFAULT_LOG_FOLDER})')
    
    # ==================== 编码格式选项 ====================
    parser.add_argument('--hw-accel', '--hardware',
                        choices=['auto', 'nvenc', 'videotoolbox', 'qsv', 'none'],
                        default=DEFAULT_HW_ACCEL,
                        help=f'硬件加速类型 (默认: {DEFAULT_HW_ACCEL})')
    
    parser.add_argument('-c', '--codec',
                        choices=['hevc', 'avc', 'av1'],
                        default=DEFAULT_OUTPUT_CODEC,
                        help=f'输出视频编码格式 (默认: {DEFAULT_OUTPUT_CODEC})')
    
    # ==================== 处理选项 ====================
    parser.add_argument('--min-size',
                        type=int,
                        default=MIN_FILE_SIZE_MB,
                        help=f'最小文件大小阈值(MB)，小于此值的文件将被跳过 (默认: {MIN_FILE_SIZE_MB})')
    
    parser.add_argument('--force-bitrate',
                        type=int,
                        default=0,
                        help='强制使用指定码率(bps)，0 表示自动计算')
    
    parser.add_argument('--no-keep-structure',
                        action='store_true',
                        help='不保持原始目录结构，所有文件输出到同一目录')
    
    parser.add_argument('-w', '--workers',
                        type=int,
                        default=MAX_WORKERS,
                        help=f'并发处理线程数 (默认: {MAX_WORKERS})')
    
    # ==================== 编码回退选项 ====================
    parser.add_argument('--enable-software-fallback',
                        action='store_true',
                        help='启用软件编码回退（默认仅使用硬件编码）')
    
    parser.add_argument('--cpu-fallback',
                        action='store_true',
                        help='启用 CPU 编码回退（等同于 --enable-software-fallback）')
    
    # ==================== 帧率限制选项 ====================
    parser.add_argument('--no-fps-limit',
                        action='store_true',
                        help='禁用所有帧率限制')
    
    parser.add_argument('--no-fps-limit-decode',
                        action='store_true',
                        help='软件解码时不限制帧率')
    
    parser.add_argument('--no-fps-limit-encode',
                        action='store_true',
                        help='软件编码时不限制帧率')
    
    parser.add_argument('--max-fps',
                        type=int,
                        default=MAX_FPS,
                        help=f'最大帧率限制 (默认: {MAX_FPS})')
    
    return parser.parse_args()


# ============================================================
# 工具函数
# ============================================================

def detect_hw_accel() -> str:
    """
    自动检测当前平台支持的硬件加速类型
    
    Returns:
        硬件加速类型: nvenc, videotoolbox, qsv, 或 none
    """
    import platform
    system = platform.system()
    
    # Mac 优先使用 VideoToolbox
    if system == "Darwin":
        return "videotoolbox"
    
    # Windows/Linux 尝试检测 NVIDIA GPU
    if system in ("Windows", "Linux"):
        try:
            # 尝试检测 NVIDIA GPU
            result = subprocess.run(
                ['nvidia-smi'], 
                capture_output=True, 
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return "nvenc"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        # 尝试检测 Intel QSV (通过 vainfo 或检测 Intel GPU)
        try:
            # Windows 上可能没有 vainfo，但可以尝试
            if system == "Linux":
                result = subprocess.run(
                    ['vainfo'], 
                    capture_output=True, 
                    text=True,
                    timeout=5
                )
                if result.returncode == 0 and "Intel" in result.stdout:
                    return "qsv"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    
    # 默认回退到无硬件加速
    return "none"


def get_hw_accel_type(hw_accel_arg: str) -> str:
    """
    获取实际使用的硬件加速类型
    
    Args:
        hw_accel_arg: 命令行参数值 (auto/nvenc/videotoolbox/qsv/none)
        
    Returns:
        实际硬件加速类型
    """
    if hw_accel_arg == "auto":
        detected = detect_hw_accel()
        logging.info(f"自动检测硬件加速: {detected}")
        return detected
    return hw_accel_arg

def setup_logging(log_folder: str) -> str:
    """
    配置日志记录器，同时输出到文件和控制台
    
    Args:
        log_folder: 日志文件夹路径
        
    Returns:
        日志文件路径
    """
    # 确保日志文件夹存在
    os.makedirs(log_folder, exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    log_file = os.path.join(log_folder, f'transcoding_{timestamp}.log')
    
    # 创建格式化器
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # 配置根日志记录器
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # 清除已有的处理器
    logger.handlers.clear()
    
    # 文件处理器
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return log_file


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
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=bit_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            filepath
        ]
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode('utf-8').strip()
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
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0',
            filepath
        ]
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode('utf-8').strip()
        parts = output.split(',')
        return int(parts[0]), int(parts[1])
    except Exception as e:
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
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            filepath
        ]
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode('utf-8').strip()
        return output
    except Exception as e:
        logging.warning(f"无法获取编码格式 {filepath}。错误: {e}")
        return "unknown"


def execute_ffmpeg(cmd: list) -> tuple:
    """
    执行 FFmpeg 命令并检查错误
    
    Args:
        cmd: FFmpeg 命令列表
        
    Returns:
        (成功标志, 错误信息)
    """
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace"
        )
        stdout, stderr = process.communicate()
        
        # 检查是否有特定错误模式
        known_errors = [
            "Impossible to convert between the formats",
            "No such filter:",
            "Unknown encoder",
            "Cannot load nvcuda.dll",
            "No NVENC capable devices found"
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


def calculate_target_bitrate(original_bitrate: int, width: int, height: int, 
                              force_bitrate: bool = False, forced_value: int = 0) -> int:
    """
    计算目标码率
    
    Args:
        original_bitrate: 原始码率
        width: 视频宽度
        height: 视频高度
        force_bitrate: 是否强制使用指定码率
        forced_value: 强制码率值
        
    Returns:
        目标码率
    """
    if force_bitrate:
        return forced_value
    
    # 根据分辨率确定最大码率
    short_side = min(width, height)
    if short_side <= 720:
        max_bitrate = 1500000
    elif short_side <= 1080:
        max_bitrate = 3000000
    elif short_side <= 1440:
        max_bitrate = 5000000
    else:
        max_bitrate = 9000000
    
    # 计算目标码率
    new_bitrate = int(original_bitrate * BITRATE_RATIO)
    
    # 限制在最小和最大值之间
    new_bitrate = max(MIN_BITRATE, min(new_bitrate, max_bitrate))
    
    return new_bitrate


def build_encoding_commands(filepath: str, temp_filename: str, 
                             bitrate: int, source_codec: str,
                             hw_accel: str = "auto",
                             output_codec: str = "hevc",
                             enable_software_encoding: bool = False,
                             limit_fps_software_decode: bool = True,
                             limit_fps_software_encode: bool = True,
                             max_fps: int = 30) -> list:
    """
    构建编码命令列表（按优先级排序）
    
    编码策略（按优先级）：
    1. 硬件全加速模式：硬件解码 + 硬件编码
    2. 混合模式：软件解码 + 硬件编码（可限帧率）
    3. [可选] 纯软件模式：软件解码 + 软件编码（可限帧率）
    
    支持的硬件加速:
    - nvenc: NVIDIA CUDA + NVENC
    - videotoolbox: Apple VideoToolbox
    - qsv: Intel Quick Sync Video
    
    支持的输出编码:
    - hevc: H.265/HEVC
    - avc: H.264/AVC
    - av1: AV1
    
    Args:
        filepath: 输入文件路径
        temp_filename: 临时输出文件路径
        bitrate: 目标码率
        source_codec: 源视频编码格式
        hw_accel: 硬件加速类型
        output_codec: 输出视频编码格式
        enable_software_encoding: 是否启用软件编码回退
        limit_fps_software_decode: 软件解码时是否限制帧率
        limit_fps_software_encode: 软件编码时是否限制帧率
        max_fps: 最大帧率
        
    Returns:
        编码命令列表
    """
    commands = []
    supported_hw_decode_codecs = ["h264", "hevc", "av1", "vp9", "mpeg2video"]
    
    # 获取硬件编码器配置
    hw_config = HW_ENCODERS.get(hw_accel, {})
    hw_encoder = hw_config.get(output_codec)
    hwaccel = hw_config.get("hwaccel")
    hwaccel_output_format = hw_config.get("hwaccel_output_format")
    
    # 获取软件编码器
    sw_encoder = SW_ENCODERS.get(output_codec, "libx264")
    
    # 编码器友好名称
    codec_names = {
        "hevc": "HEVC/H.265",
        "avc": "AVC/H.264", 
        "av1": "AV1"
    }
    codec_display = codec_names.get(output_codec, output_codec.upper())
    
    # 硬件加速友好名称
    hw_names = {
        "nvenc": "NVIDIA NVENC",
        "videotoolbox": "Apple VideoToolbox",
        "qsv": "Intel QSV",
        "none": "软件"
    }
    hw_display = hw_names.get(hw_accel, hw_accel)
    
    # ========================================
    # 1. 硬件全加速模式（硬件解码 + 硬件编码）
    # ========================================
    if hw_encoder and source_codec in supported_hw_decode_codecs:
        cmd = ['ffmpeg', '-y', '-hide_banner']
        
        # 添加硬件解码参数
        if hwaccel:
            cmd.extend(['-hwaccel', hwaccel])
            if hwaccel_output_format:
                cmd.extend(['-hwaccel_output_format', hwaccel_output_format])
        
        cmd.extend([
            '-i', filepath,
            '-c:v', hw_encoder, '-b:v', str(bitrate),
            '-c:a', 'aac', '-b:a', AUDIO_BITRATE,
            temp_filename
        ])
        
        commands.append({
            "name": f"{hw_display} 全加速 ({codec_display}, 硬件解码+编码)",
            "cmd": cmd
        })
    
    # ========================================
    # 2. 混合模式（软件解码 + 硬件编码）
    # ========================================
    if hw_encoder:
        # 2a. 限制帧率版本
        if limit_fps_software_decode:
            commands.append({
                "name": f"{hw_display} 编码 ({codec_display}, 软件解码, 限{max_fps}fps)",
                "cmd": [
                    'ffmpeg', '-y', '-hide_banner',
                    '-i', filepath,
                    '-vf', f'fps={max_fps}',
                    '-c:v', hw_encoder, '-b:v', str(bitrate),
                    '-c:a', 'aac', '-b:a', AUDIO_BITRATE,
                    temp_filename
                ]
            })
        
        # 2b. 不限帧率版本（备用）
        commands.append({
            "name": f"{hw_display} 编码 ({codec_display}, 软件解码)",
            "cmd": [
                'ffmpeg', '-y', '-hide_banner',
                '-i', filepath,
                '-c:v', hw_encoder, '-b:v', str(bitrate),
                '-c:a', 'aac', '-b:a', AUDIO_BITRATE,
                temp_filename
            ]
        })
    
    # ========================================
    # 3. [可选] 纯软件编码模式
    # ========================================
    if enable_software_encoding or hw_accel == "none":
        # 编码器特定参数
        encoder_params = []
        if sw_encoder in ("libx265", "libx264"):
            encoder_params = ['-preset', 'medium']
        elif sw_encoder == "libsvtav1":
            encoder_params = ['-preset', '6']  # SVT-AV1 preset 0-13, 6 是平衡点
        
        # 3a. 限制帧率版本
        if limit_fps_software_encode:
            cmd = [
                'ffmpeg', '-y', '-hide_banner',
                '-i', filepath,
                '-vf', f'fps={max_fps}',
                '-c:v', sw_encoder
            ]
            cmd.extend(encoder_params)
            cmd.extend([
                '-b:v', str(bitrate),
                '-c:a', 'aac', '-b:a', AUDIO_BITRATE,
                temp_filename
            ])
            commands.append({
                "name": f"CPU 编码 ({sw_encoder}, 限{max_fps}fps)",
                "cmd": cmd
            })
        
        # 3b. 不限帧率版本
        cmd = [
            'ffmpeg', '-y', '-hide_banner',
            '-i', filepath,
            '-c:v', sw_encoder
        ]
        cmd.extend(encoder_params)
        cmd.extend([
            '-b:v', str(bitrate),
            '-c:a', 'aac', '-b:a', AUDIO_BITRATE,
            temp_filename
        ])
        commands.append({
            "name": f"CPU 编码 ({sw_encoder})",
            "cmd": cmd
        })
        
        # 3c. 如果输出不是 AVC，添加 libx264 作为最终回退
        if output_codec != "avc":
            commands.append({
                "name": "CPU 编码 (libx264, 最大兼容回退)",
                "cmd": [
                    'ffmpeg', '-y', '-hide_banner',
                    '-i', filepath,
                    '-c:v', 'libx264', '-preset', 'medium', '-b:v', str(bitrate),
                    '-c:a', 'aac', '-b:a', AUDIO_BITRATE,
                    temp_filename
                ]
            })
    
    return commands


def compress_video(filepath: str, input_folder: str, output_folder: str,
                   keep_structure: bool = True, force_bitrate: bool = False,
                   forced_bitrate: int = 0, min_file_size_mb: int = 100,
                   hw_accel: str = "auto",
                   output_codec: str = "hevc",
                   enable_software_encoding: bool = False,
                   limit_fps_software_decode: bool = True,
                   limit_fps_software_encode: bool = True,
                   max_fps: int = 30) -> tuple:
    """
    压缩单个视频文件
    
    Args:
        filepath: 输入文件路径
        input_folder: 输入文件夹根路径
        output_folder: 输出文件夹根路径
        keep_structure: 是否保持目录结构
        force_bitrate: 是否强制码率
        forced_bitrate: 强制码率值
        min_file_size_mb: 最小文件大小阈值（MB）
        hw_accel: 硬件加速类型
        output_codec: 输出视频编码格式
        enable_software_encoding: 是否启用软件编码回退
        limit_fps_software_decode: 软件解码时是否限制帧率
        limit_fps_software_encode: 软件编码时是否限制帧率
        max_fps: 最大帧率
        
    Returns:
        (结果状态, 错误信息, 统计信息字典)
    """
    stats = {
        "original_size": 0,
        "new_size": 0,
        "original_bitrate": 0,
        "new_bitrate": 0
    }
    
    try:
        # 检查文件大小
        file_size = os.path.getsize(filepath)
        stats["original_size"] = file_size
        
        if file_size < min_file_size_mb * 1024 * 1024:
            logging.info(f"[跳过] 文件小于 {min_file_size_mb}MB: {filepath}")
            return RESULT_SKIP_SIZE, None, stats
        
        # 获取视频信息
        original_bitrate = get_bitrate(filepath)
        width, height = get_resolution(filepath)
        source_codec = get_codec(filepath)
        stats["original_bitrate"] = original_bitrate
        
        # 计算目标码率
        new_bitrate = calculate_target_bitrate(
            original_bitrate, width, height, 
            force_bitrate, forced_bitrate
        )
        stats["new_bitrate"] = new_bitrate
        
        # 确定输出文件路径
        if keep_structure:
            relative_path = os.path.relpath(filepath, input_folder)
            # 使用 Path 正确处理扩展名
            output_path = Path(output_folder) / Path(relative_path).with_suffix('.mp4')
            new_filename = str(output_path)
        else:
            # 正确去除原扩展名后添加 .mp4
            base_name = Path(filepath).stem + ".mp4"
            new_filename = os.path.join(output_folder, base_name)
        
        # 生成临时文件名
        new_dirname = os.path.dirname(new_filename)
        temp_filename = os.path.join(new_dirname, "tmp_" + os.path.basename(new_filename))
        os.makedirs(new_dirname, exist_ok=True)
        
        # 检查输出文件是否已存在
        if os.path.exists(new_filename):
            logging.info(f"[跳过] 输出文件已存在: {new_filename}")
            return RESULT_SKIP_EXISTS, None, stats
        
        # 构建编码命令
        encoding_commands = build_encoding_commands(
            filepath, temp_filename, new_bitrate, source_codec,
            hw_accel=hw_accel,
            output_codec=output_codec,
            enable_software_encoding=enable_software_encoding,
            limit_fps_software_decode=limit_fps_software_decode,
            limit_fps_software_encode=limit_fps_software_encode,
            max_fps=max_fps
        )
        
        # 逐一尝试编码命令
        success = False
        last_error = None
        
        for i, cmd_info in enumerate(encoding_commands):
            logging.info(f"[尝试] 方法 {i+1}/{len(encoding_commands)} ({cmd_info['name']}): {os.path.basename(filepath)}")
            success, error = execute_ffmpeg(cmd_info["cmd"])
            
            if success:
                logging.info(f"[成功] 使用 {cmd_info['name']} 完成压缩")
                break
            else:
                last_error = error
                logging.warning(f"[失败] {cmd_info['name']}: {error}")
                
                # 清理临时文件
                if os.path.exists(temp_filename):
                    try:
                        os.remove(temp_filename)
                    except Exception as e:
                        logging.error(f"删除临时文件失败: {e}")
        
        if not success:
            error_msg = f"所有编码方法均失败。最后错误: {last_error}"
            logging.error(f"[错误] {filepath}: {error_msg}")
            return error_msg, last_error, stats
        
        # 压缩成功，重命名临时文件
        os.rename(temp_filename, new_filename)
        
        # 获取新文件大小
        new_size = os.path.getsize(new_filename)
        stats["new_size"] = new_size
        
        # 计算压缩率
        compression_ratio = (1 - new_size / file_size) * 100 if file_size > 0 else 0
        
        logging.info(
            f"[完成] {os.path.basename(filepath)} | "
            f"码率: {original_bitrate/1000:.0f}k -> {new_bitrate/1000:.0f}k | "
            f"大小: {file_size/1024/1024:.1f}MB -> {new_size/1024/1024:.1f}MB | "
            f"压缩率: {compression_ratio:.1f}%"
        )
        
        return RESULT_SUCCESS, None, stats
        
    except Exception as e:
        logging.error(f"[异常] 处理 {filepath} 时发生错误: {e}")
        
        # 清理临时文件
        if 'temp_filename' in locals() and os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
            except:
                pass
        
        return str(e), str(e), stats


def get_video_files(input_folder: str) -> list:
    """
    获取输入文件夹中的所有视频文件
    
    Args:
        input_folder: 输入文件夹路径
        
    Returns:
        视频文件路径列表
    """
    video_files = []
    for root, _, files in os.walk(input_folder):
        for file in files:
            if file.lower().endswith(SUPPORTED_VIDEO_EXTENSIONS):
                video_files.append(os.path.join(root, file))
    return video_files


# ============================================================
# 主函数
# ============================================================
def main():
    """主函数"""
    # 解析命令行参数
    args = parse_arguments()
    
    # 配置变量
    input_folder = args.input
    output_folder = args.output
    log_folder = args.log
    min_file_size = args.min_size
    force_bitrate = args.force_bitrate > 0
    forced_bitrate = args.force_bitrate
    keep_structure = not args.no_keep_structure
    max_workers = args.workers
    output_codec = args.codec
    
    # 软件编码回退（默认关闭）
    enable_software_encoding = args.enable_software_fallback or args.cpu_fallback
    
    # 帧率限制
    limit_fps_software_decode = not (args.no_fps_limit or args.no_fps_limit_decode)
    limit_fps_software_encode = not (args.no_fps_limit or args.no_fps_limit_encode)
    max_fps = args.max_fps
    
    # 设置日志
    log_file = setup_logging(log_folder)
    
    # 获取硬件加速类型（需要在日志设置后调用，以便输出检测结果）
    hw_accel = get_hw_accel_type(args.hw_accel)
    
    # 编码格式友好名称
    codec_names = {"hevc": "HEVC/H.265", "avc": "AVC/H.264", "av1": "AV1"}
    hw_names = {"nvenc": "NVIDIA NVENC", "videotoolbox": "Apple VideoToolbox", 
                "qsv": "Intel QSV", "none": "仅软件"}
    
    try:
        # 记录开始信息
        logging.info("=" * 60)
        logging.info("SBVC - 超级批量视频压缩器")
        logging.info("=" * 60)
        logging.info(f"输入目录: {input_folder}")
        logging.info(f"输出目录: {output_folder}")
        logging.info(f"日志文件: {log_file}")
        logging.info(f"最小文件大小: {min_file_size} MB")
        logging.info(f"保持目录结构: {'是' if keep_structure else '否'}")
        logging.info(f"强制码率: {forced_bitrate/1000:.0f}kbps" if force_bitrate else "强制码率: 自动")
        logging.info(f"并发线程数: {max_workers}")
        logging.info(f"硬件加速: {hw_names.get(hw_accel, hw_accel)}")
        logging.info(f"输出编码: {codec_names.get(output_codec, output_codec)}")
        logging.info(f"软件编码回退: {'启用' if enable_software_encoding else '禁用'}")
        logging.info(f"软件解码限帧: {f'{max_fps}fps' if limit_fps_software_decode else '无限制'}")
        logging.info(f"软件编码限帧: {f'{max_fps}fps' if limit_fps_software_encode else '无限制'}")
        logging.info("-" * 60)
        
        # 检查输入目录
        if not os.path.exists(input_folder):
            logging.error(f"输入目录不存在: {input_folder}")
            return 1
        
        # 确保输出目录存在
        os.makedirs(output_folder, exist_ok=True)
        
        # 获取视频文件列表
        video_files = get_video_files(input_folder)
        total_files = len(video_files)
        
        if total_files == 0:
            logging.warning("未发现任何视频文件")
            return 0
        
        logging.info(f"发现 {total_files} 个视频文件")
        logging.info("-" * 60)
        
        # 创建处理函数的包装器
        def process_file(filepath):
            return compress_video(
                filepath=filepath,
                input_folder=input_folder,
                output_folder=output_folder,
                keep_structure=keep_structure,
                force_bitrate=force_bitrate,
                forced_bitrate=forced_bitrate,
                min_file_size_mb=min_file_size,
                hw_accel=hw_accel,
                output_codec=output_codec,
                enable_software_encoding=enable_software_encoding,
                limit_fps_software_decode=limit_fps_software_decode,
                limit_fps_software_encode=limit_fps_software_encode,
                max_fps=max_fps
            )
        
        # 使用线程池处理
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {executor.submit(process_file, f): f for f in video_files}
            
            for i, future in enumerate(concurrent.futures.as_completed(future_to_file)):
                filepath = future_to_file[future]
                try:
                    result = future.result()
                    results.append((filepath, result))
                except Exception as e:
                    results.append((filepath, (str(e), str(e), {})))
                
                # 显示进度
                logging.info(f"[进度] {i+1}/{total_files} ({(i+1)/total_files*100:.1f}%)")
        
        # 统计结果
        success_count = 0
        skip_size_count = 0
        skip_exists_count = 0
        fail_count = 0
        total_original_size = 0
        total_new_size = 0
        
        for filepath, (status, error, stats) in results:
            if status == RESULT_SUCCESS:
                success_count += 1
                total_original_size += stats.get("original_size", 0)
                total_new_size += stats.get("new_size", 0)
            elif status == RESULT_SKIP_SIZE:
                skip_size_count += 1
            elif status == RESULT_SKIP_EXISTS:
                skip_exists_count += 1
            else:
                fail_count += 1
        
        # 记录总结
        logging.info("=" * 60)
        logging.info("任务完成统计")
        logging.info("=" * 60)
        logging.info(f"总文件数: {total_files}")
        logging.info(f"成功压缩: {success_count}")
        logging.info(f"跳过(文件过小): {skip_size_count}")
        logging.info(f"跳过(已存在): {skip_exists_count}")
        logging.info(f"失败: {fail_count}")
        
        if success_count > 0 and total_original_size > 0:
            total_saved = total_original_size - total_new_size
            compression_ratio = (1 - total_new_size / total_original_size) * 100
            logging.info("-" * 60)
            logging.info(f"原始总大小: {total_original_size/1024/1024/1024:.2f} GB")
            logging.info(f"压缩后大小: {total_new_size/1024/1024/1024:.2f} GB")
            logging.info(f"节省空间: {total_saved/1024/1024/1024:.2f} GB ({compression_ratio:.1f}%)")
        
        logging.info("=" * 60)
        
        return 0 if fail_count == 0 else 1
        
    except KeyboardInterrupt:
        logging.warning("用户中断操作")
        return 130
    except Exception as e:
        logging.critical(f"程序执行过程中发生严重错误: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())