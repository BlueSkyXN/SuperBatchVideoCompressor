#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频文件处理模块

文件枚举和路径处理
"""

import os
from pathlib import Path
from typing import Tuple

from src.config.defaults import SUPPORTED_VIDEO_EXTENSIONS


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


def resolve_output_paths(
    filepath: str, input_folder: str, output_folder: str, keep_structure: bool = True
) -> Tuple[str, str]:
    """
    根据输入文件和配置生成输出路径和临时路径

    Returns:
        (最终输出文件路径, 临时文件路径)
    
    Raises:
        ValueError: 如果文件路径不在输入文件夹内或输出路径越界
    """
    # 对于 Windows 下的 "/input" 这类 POSIX 风格绝对路径，避免 resolve() 注入盘符
    use_lexical_paths = all(str(p).startswith("/") for p in (filepath, input_folder, output_folder))

    # 解析为规范路径并验证（防止路径遍历攻击）
    if use_lexical_paths:
        abs_filepath = Path(os.path.normpath(filepath))
        abs_input = Path(os.path.normpath(input_folder))
        abs_output = Path(os.path.normpath(output_folder))
    else:
        abs_filepath = Path(filepath).resolve()
        abs_input = Path(input_folder).resolve()
        abs_output = Path(output_folder).resolve()

    # 验证文件确实在 input_folder 内
    try:
        abs_filepath.relative_to(abs_input)
    except ValueError:
        raise ValueError(
            f"安全错误：文件 {filepath} 不在输入文件夹 {input_folder} 内"
        )

    if keep_structure:
        relative_path = abs_filepath.relative_to(abs_input)
        output_path = (abs_output / relative_path).with_suffix(".mp4")
    else:
        base_name = f"{abs_filepath.stem}.mp4"
        output_path = abs_output / base_name

    # 解析输出路径并进行最终验证（防止符号链接或其他方式越界）
    output_path = (
        Path(os.path.normpath(str(output_path)))
        if use_lexical_paths
        else output_path.resolve()
    )
    try:
        output_path.relative_to(abs_output)
    except ValueError:
        raise ValueError(
            f"安全错误：计算的输出路径 {output_path} 超出了输出文件夹 {abs_output}"
        )

    # 统一使用 POSIX 风格路径，避免 Windows 下反斜杠导致路径对比或日志不一致
    new_filename = output_path.as_posix()
    temp_filename = (output_path.parent / f"tmp_{output_path.name}").as_posix()
    return new_filename, temp_filename
