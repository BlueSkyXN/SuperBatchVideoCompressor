#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音频码率探测与解析测试
"""

import sys
import os
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.encoder import parse_bitrate_to_bps
from src.core.video import get_audio_bitrate


class TestParseBitrateToBps:
    def test_parse_common_units(self):
        assert parse_bitrate_to_bps("128k") == 128000
        assert parse_bitrate_to_bps("128kbps") == 128000
        assert parse_bitrate_to_bps("1M") == 1000000
        assert parse_bitrate_to_bps("2m") == 2000000
        assert parse_bitrate_to_bps("64000") == 64000
        assert parse_bitrate_to_bps(128000) == 128000

    def test_parse_empty_or_invalid(self):
        assert parse_bitrate_to_bps(None) is None
        assert parse_bitrate_to_bps("") is None
        assert parse_bitrate_to_bps("null") is None
        assert parse_bitrate_to_bps("bad") is None


class TestGetAudioBitrate:
    def test_returns_int_value(self, monkeypatch):
        captured = {}

        def fake_check_output(cmd, stderr=None, timeout=None):
            captured["cmd"] = cmd
            return b"128000\n"

        monkeypatch.setattr(
            "src.core.video.subprocess.check_output",
            fake_check_output,
        )

        result = get_audio_bitrate("dummy.mp4")
        assert result == 128000
        assert "ffprobe" in captured["cmd"][0]
        assert "a:0" in captured["cmd"]

    def test_returns_none_on_na(self, monkeypatch):
        def fake_check_output(cmd, stderr=None, timeout=None):
            return b"N/A\n"

        monkeypatch.setattr(
            "src.core.video.subprocess.check_output",
            fake_check_output,
        )

        assert get_audio_bitrate("dummy.mp4") is None

    def test_returns_none_on_error(self, monkeypatch):
        def fake_check_output(cmd, stderr=None, timeout=None):
            raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(
            "src.core.video.subprocess.check_output",
            fake_check_output,
        )

        assert get_audio_bitrate("dummy.mp4") is None
