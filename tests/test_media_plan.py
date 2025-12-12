#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
media_plan 纯逻辑测试（不依赖本地 ffprobe/ffmpeg）
"""

from src.core.media_plan import build_stream_plan
from src.core.streams import AudioStreamInfo, SubtitleStreamInfo


def test_probe_failure_degrades_to_legacy(monkeypatch):
    def fake_probe(_):
        return [], [], False

    monkeypatch.setattr("src.core.media_plan.probe_streams", fake_probe)

    plan = build_stream_plan("/test/input.mp4", {"audio_bitrate": "128k"})
    assert plan["map_args"] is None
    assert plan["audio_args"] is None
    assert plan["subtitle_args"] == ["-sn"]


def test_first_track_transcode_default(monkeypatch):
    audio_streams = [
        AudioStreamInfo(index=1, codec_name="aac", bit_rate=96000, language="eng"),
        AudioStreamInfo(index=2, codec_name="mp3", bit_rate=128000, language="zho"),
    ]

    def fake_probe(_):
        return audio_streams, [], True

    monkeypatch.setattr("src.core.media_plan.probe_streams", fake_probe)

    encoding_cfg = {
        "audio_bitrate": "128k",
        "audio": {
            "enabled": True,
            "target_codec": "aac",
            "target_bitrate": None,
            "copy_policy": "off",
            "tracks": {"keep": "first"},
        },
        "subtitles": {"keep": "none"},
    }

    plan = build_stream_plan("/test/input.mp4", encoding_cfg)
    assert plan["map_args"] is None
    assert plan["audio_args"] is None
    assert plan["used_audio_copy"] is False


def test_smart_copy_aac_under_target(monkeypatch):
    audio_streams = [
        AudioStreamInfo(index=3, codec_name="aac", bit_rate=96000, language="eng"),
    ]

    def fake_probe(_):
        return audio_streams, [], True

    monkeypatch.setattr("src.core.media_plan.probe_streams", fake_probe)

    encoding_cfg = {
        "audio_bitrate": "128k",
        "audio": {
            "enabled": True,
            "copy_policy": "smart",
            "copy_allow_codecs": ["aac"],
            "copy_max_bitrate_ratio": 1.0,
            "aac_adtstoasc": True,
            "tracks": {"keep": "first"},
        },
        "subtitles": {"keep": "none"},
    }

    plan = build_stream_plan("/test/input.mp4", encoding_cfg)
    assert plan["audio_args"][:2] == ["-c:a:0", "copy"]
    assert "aac_adtstoasc" in plan["audio_args"]
    assert plan["used_audio_copy"] is True


def test_language_prefer_selects_match(monkeypatch):
    audio_streams = [
        AudioStreamInfo(index=1, codec_name="aac", bit_rate=96000, language="zho"),
        AudioStreamInfo(index=5, codec_name="aac", bit_rate=96000, language="eng"),
    ]

    def fake_probe(_):
        return audio_streams, [], True

    monkeypatch.setattr("src.core.media_plan.probe_streams", fake_probe)

    encoding_cfg = {
        "audio_bitrate": "128k",
        "audio": {
            "enabled": True,
            "copy_policy": "off",
            "tracks": {"keep": "language_prefer", "prefer_language": ["eng"]},
        },
        "subtitles": {"keep": "none"},
    }

    plan = build_stream_plan("/test/input.mp4", encoding_cfg)
    assert plan["map_args"] == ["-map", "0:v:0", "-map", "0:5"]


def test_subtitles_mov_text_filter(monkeypatch):
    subs = [
        SubtitleStreamInfo(index=7, codec_name="subrip", language="zho"),
        SubtitleStreamInfo(index=8, codec_name="ass", language="jpn"),
    ]

    def fake_probe(_):
        return [], subs, True

    monkeypatch.setattr("src.core.media_plan.probe_streams", fake_probe)

    encoding_cfg = {
        "audio_bitrate": "128k",
        "audio": {"enabled": True, "copy_policy": "off", "tracks": {"keep": "first"}},
        "subtitles": {"keep": "mov_text", "languages": ["zho"]},
    }

    plan = build_stream_plan("/test/input.mp4", encoding_cfg)
    assert plan["map_args"] == ["-map", "0:v:0", "-map", "0:7"]
    assert plan["subtitle_args"] == ["-c:s:0", "mov_text"]
    assert plan["used_subtitle_copy"] is False
