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
    filepath: str,
    input_folder: str,
    output_folder: str,
    keep_structure: bool = True
) -> Tuple[str, str]:
    """
    根据输入文件和配置生成输出路径和临时路径
    
    Returns:
        (最终输出文件路径, 临时文件路径)
    """
    if keep_structure:
        relative_path = os.path.relpath(filepath, input_folder)
        output_path = Path(output_folder) / Path(relative_path).with_suffix('.mp4')
    else:
        base_name = Path(filepath).stem + ".mp4"
        output_path = Path(output_folder) / base_name
    
    new_filename = str(output_path)
    temp_filename = os.path.join(os.path.dirname(new_filename), "tmp_" + os.path.basename(new_filename))
    return new_filename, temp_filename
