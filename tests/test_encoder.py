#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
编码器模块测试
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.encoder import (
    calculate_target_bitrate,
    build_hw_encode_command,
    build_sw_encode_command,
)
from src.config.defaults import HW_ENCODERS, SW_ENCODERS


class TestCalculateTargetBitrate:
    """目标码率计算测试"""
    
    def test_force_bitrate(self):
        """测试强制码率"""
        result = calculate_target_bitrate(
            original_bitrate=5000000,
            width=1920,
            height=1080,
            force_bitrate=True,
            forced_value=3000000
        )
        assert result == 3000000
    
    def test_auto_bitrate_1080p(self):
        """测试 1080p 自动码率"""
        result = calculate_target_bitrate(
            original_bitrate=10000000,
            width=1920,
            height=1080,
            force_bitrate=False,
            forced_value=0
        )
        # 10M * 0.5 = 5M, 但 1080p 最大 3M
        assert result == 3000000
    
    def test_auto_bitrate_720p(self):
        """测试 720p 自动码率"""
        result = calculate_target_bitrate(
            original_bitrate=4000000,
            width=1280,
            height=720,
            force_bitrate=False,
            forced_value=0
        )
        # 4M * 0.5 = 2M, 但 720p 最大 1.5M
        assert result == 1500000
    
    def test_min_bitrate(self):
        """测试最小码率限制"""
        result = calculate_target_bitrate(
            original_bitrate=500000,
            width=1280,
            height=720,
            force_bitrate=False,
            forced_value=0
        )
        # 500k * 0.5 = 250k, 但最小 500k
        assert result == 500000


class TestBuildEncodingCommands:
    """编码命令构建测试"""
    
    def test_nvenc_hw_commands(self):
        """测试 NVENC 硬件编码命令"""
        result = build_hw_encode_command(
            filepath="/test/input.mp4",
            temp_filename="/test/output.mp4",
            bitrate=3000000,
            source_codec="h264",
            hw_accel="nvenc",
            output_codec="hevc",
            use_hw_decode=True,
        )
        
        assert result is not None
        assert "NVIDIA NVENC" in result["name"]
        assert "hevc_nvenc" in result["cmd"]
    
    def test_qsv_hw_commands(self):
        """测试 QSV 硬件编码命令"""
        result = build_hw_encode_command(
            filepath="/test/input.mp4",
            temp_filename="/test/output.mp4",
            bitrate=3000000,
            source_codec="h264",
            hw_accel="qsv",
            output_codec="hevc",
            use_hw_decode=True,
        )
        
        assert result is not None
        assert "Intel QSV" in result["name"]
    
    def test_software_commands(self):
        """测试软件编码命令"""
        result = build_sw_encode_command(
            filepath="/test/input.mp4",
            temp_filename="/test/output.mp4",
            bitrate=3000000,
            output_codec="hevc",
            limit_fps=False,
        )
        
        assert result is not None
        assert "CPU" in result["name"]
        assert "libx265" in result["cmd"]
    
    def test_software_with_fps_limit(self):
        """测试带帧率限制的软件编码"""
        result = build_sw_encode_command(
            filepath="/test/input.mp4",
            temp_filename="/test/output.mp4",
            bitrate=3000000,
            output_codec="hevc",
            limit_fps=True,
            max_fps=30,
        )
        
        assert "限30fps" in result["name"]
        assert "fps=30" in " ".join(result["cmd"])


class TestEncoderMappings:
    """编码器映射测试"""
    
    def test_hw_encoders_exist(self):
        """测试硬件编码器映射存在"""
        assert "nvenc" in HW_ENCODERS
        assert "qsv" in HW_ENCODERS
        assert "videotoolbox" in HW_ENCODERS
    
    def test_sw_encoders_exist(self):
        """测试软件编码器映射存在"""
        assert "hevc" in SW_ENCODERS
        assert "avc" in SW_ENCODERS
        assert "av1" in SW_ENCODERS
    
    def test_nvenc_codecs(self):
        """测试 NVENC 支持的编码格式"""
        nvenc = HW_ENCODERS["nvenc"]
        assert nvenc["hevc"] == "hevc_nvenc"
        assert nvenc["avc"] == "h264_nvenc"
