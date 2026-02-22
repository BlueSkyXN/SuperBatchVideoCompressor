#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
编码器模块测试
"""

import sys
import os
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.encoder import (
    calculate_target_bitrate,
    build_hw_encode_command,
    build_sw_encode_command,
    SUPPORTED_HW_DECODE_CODECS,
    execute_ffmpeg,
    is_decode_corruption_error,
    add_ignore_decode_errors_flags,
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
            forced_value=3000000,
        )
        assert result == 3000000

    def test_auto_bitrate_1080p(self):
        """测试 1080p 自动码率"""
        result = calculate_target_bitrate(
            original_bitrate=10000000,
            width=1920,
            height=1080,
            force_bitrate=False,
            forced_value=0,
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
            forced_value=0,
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
            forced_value=0,
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


class TestHardwareDecodeWhitelist:
    """硬件解码白名单测试"""

    def test_whitelist_structure(self):
        """测试白名单是字典结构"""
        assert isinstance(SUPPORTED_HW_DECODE_CODECS, dict)
        assert "nvenc" in SUPPORTED_HW_DECODE_CODECS
        assert "qsv" in SUPPORTED_HW_DECODE_CODECS
        assert "videotoolbox" in SUPPORTED_HW_DECODE_CODECS

    def test_qsv_supports_wmv(self):
        """测试 QSV 支持 WMV/VC1 硬解"""
        qsv_codecs = SUPPORTED_HW_DECODE_CODECS["qsv"]
        assert "vc1" in qsv_codecs
        assert "wmv3" in qsv_codecs

    def test_nvenc_no_wmv(self):
        """测试 NVENC 不支持 WMV/VC1 硬解"""
        nvenc_codecs = SUPPORTED_HW_DECODE_CODECS["nvenc"]
        assert "vc1" not in nvenc_codecs
        assert "wmv3" not in nvenc_codecs

    def test_common_codecs_in_all(self):
        """测试常见编码格式在所有编码器中都支持"""
        for encoder, codecs in SUPPORTED_HW_DECODE_CODECS.items():
            assert "h264" in codecs, f"{encoder} 应该支持 h264"
            assert "hevc" in codecs, f"{encoder} 应该支持 hevc"

    def test_qsv_wmv_hardware_decode(self):
        """测试 QSV 对 WMV 文件使用硬解"""
        result = build_hw_encode_command(
            filepath="/test/input.wmv",
            temp_filename="/test/output.mp4",
            bitrate=3000000,
            source_codec="wmv3",
            hw_accel="qsv",
            output_codec="hevc",
            use_hw_decode=True,
        )

        assert result is not None
        assert "硬解+硬编" in result["name"]
        assert "-hwaccel" in result["cmd"]
        assert "qsv" in result["cmd"]

    def test_nvenc_wmv_software_decode(self):
        """测试 NVENC 对 WMV 文件回退到软解"""
        result = build_hw_encode_command(
            filepath="/test/input.wmv",
            temp_filename="/test/output.mp4",
            bitrate=3000000,
            source_codec="wmv3",
            hw_accel="nvenc",
            output_codec="hevc",
            use_hw_decode=True,
        )

        assert result is not None
        assert "软解+硬编" in result["name"]
        assert "-hwaccel" not in result["cmd"]

    def test_encoder_specific_codec_support(self):
        """测试不同编码器对特定编码格式的支持"""
        # QSV 支持 VC1
        assert "vc1" in SUPPORTED_HW_DECODE_CODECS["qsv"]

        # VideoToolbox 支持 ProRes
        assert "prores" in SUPPORTED_HW_DECODE_CODECS["videotoolbox"]

        # NVENC 支持 VP9
        assert "vp9" in SUPPORTED_HW_DECODE_CODECS["nvenc"]


class TestExecuteFFmpeg:
    """FFmpeg 执行测试"""

    def test_success_returns_true(self, monkeypatch):
        class DummyProcess:
            returncode = 0

            def communicate(self, timeout=None):
                return "", ""

        monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: DummyProcess())

        success, error = execute_ffmpeg(["ffmpeg", "-version"], timeout=15)
        assert success is True
        assert error is None

    def test_timeout_returns_readable_error(self, monkeypatch):
        class DummyProcess:
            returncode = 1
            killed = False

            def communicate(self, timeout=None):
                if timeout is not None:
                    raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=timeout)
                return "", ""

            def kill(self):
                self.killed = True

        process = DummyProcess()

        monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: process)

        success, error = execute_ffmpeg(["ffmpeg", "-version"], timeout=15)
        assert success is False
        assert "超时" in error
        assert "15" in error
        assert process.killed is True


class TestDecodeErrorRecoveryHelpers:
    """解码错误容错辅助函数测试"""

    def test_detect_decode_corruption_error(self):
        assert (
            is_decode_corruption_error("Invalid data found when processing input")
            is True
        )
        assert is_decode_corruption_error("Unknown encoder") is False

    def test_add_ignore_flags_before_input(self):
        cmd = ["ffmpeg", "-y", "-i", "in.mp4", "-c:v", "hevc_nvenc", "out.mp4"]
        updated = add_ignore_decode_errors_flags(cmd)
        i_idx = updated.index("-i")
        assert "-fflags" in updated[:i_idx]
        assert "+discardcorrupt" in updated[:i_idx]

    def test_add_ignore_flags_no_duplicate(self):
        cmd = [
            "ffmpeg",
            "-y",
            "-fflags",
            "+discardcorrupt",
            "-err_detect",
            "ignore_err",
            "-i",
            "in.mp4",
            "-c:v",
            "hevc_nvenc",
            "out.mp4",
        ]
        updated = add_ignore_decode_errors_flags(cmd)
        assert updated == cmd
