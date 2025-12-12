#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ffprobe 流信息探测模块

用于一次性读取文件内的音频/字幕(及视频) streams 元数据，
为音轨选择、copy/转码策略、字幕处理提供依据。

设计要求：
- 仅依赖 ffprobe 标准输出（JSON）
- 失败时返回空列表，不阻断主流程
- 兼容 Windows 服务器运行环境
"""

import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _to_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_language(tags: Dict[str, Any]) -> Optional[str]:
    if not tags:
        return None
    for key in ("language", "LANGUAGE"):
        lang = tags.get(key)
        if lang:
            return str(lang).lower()
    return None


@dataclass
class AudioStreamInfo:
    index: int
    codec_name: str
    bit_rate: Optional[int] = None
    channels: Optional[int] = None
    sample_rate: Optional[int] = None
    language: Optional[str] = None
    is_default: bool = False
    is_commentary: bool = False


@dataclass
class SubtitleStreamInfo:
    index: int
    codec_name: str
    language: Optional[str] = None
    is_default: bool = False
    is_commentary: bool = False


def probe_streams(
    filepath: str,
) -> Tuple[List[AudioStreamInfo], List[SubtitleStreamInfo], bool]:
    """
    使用 ffprobe 探测音频/字幕 streams。

    Args:
        filepath: 输入文件路径

    Returns:
        (audio_streams, subtitle_streams)
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-of",
        "json",
        filepath,
    ]

    try:
        raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        try:
            output = raw.decode("utf-8")
        except UnicodeDecodeError:
            import locale

            output = raw.decode(locale.getpreferredencoding(False), errors="replace")
        data = json.loads(output) if output else {}
        streams = data.get("streams", []) or []
    except Exception as e:
        logger.warning(f"ffprobe 读取 streams 失败: {filepath}, 错误: {e}")
        return [], [], False

    audio_streams: List[AudioStreamInfo] = []
    subtitle_streams: List[SubtitleStreamInfo] = []

    for s in streams:
        codec_type = s.get("codec_type")
        if codec_type not in ("audio", "subtitle"):
            continue

        index = _to_int(s.get("index"))
        if index is None:
            continue

        codec_name = str(s.get("codec_name") or "unknown").lower()
        tags = s.get("tags") or {}
        disposition = s.get("disposition") or {}

        is_default = _to_int(disposition.get("default")) == 1
        is_commentary = _to_int(disposition.get("commentary")) == 1
        language = _normalize_language(tags)

        if codec_type == "audio":
            audio_streams.append(
                AudioStreamInfo(
                    index=index,
                    codec_name=codec_name,
                    bit_rate=_to_int(s.get("bit_rate")),
                    channels=_to_int(s.get("channels")),
                    sample_rate=_to_int(s.get("sample_rate")),
                    language=language,
                    is_default=is_default,
                    is_commentary=is_commentary,
                )
            )
        else:
            subtitle_streams.append(
                SubtitleStreamInfo(
                    index=index,
                    codec_name=codec_name,
                    language=language,
                    is_default=is_default,
                    is_commentary=is_commentary,
                )
            )

    # 保持 ffprobe 的原顺序（通常即文件内顺序）
    if logger.isEnabledFor(logging.DEBUG):
        audio_desc = "; ".join(
            [
                f"{a.index}:{a.codec_name}"
                f"@{a.bit_rate or 'na'}bps"
                f" ch={a.channels or '-'}"
                f" sr={a.sample_rate or '-'}"
                f" lang={a.language or '-'}"
                f"{' default' if a.is_default else ''}"
                f"{' commentary' if a.is_commentary else ''}"
                for a in audio_streams
            ]
        )
        sub_desc = "; ".join(
            [
                f"{s.index}:{s.codec_name}"
                f" lang={s.language or '-'}"
                f"{' default' if s.is_default else ''}"
                f"{' commentary' if s.is_commentary else ''}"
                for s in subtitle_streams
            ]
        )
        logger.debug(
            f"streams 探测结果: audio[{len(audio_streams)}]=[{audio_desc}] "
            f"subtitles[{len(subtitle_streams)}]=[{sub_desc}]"
        )

    return audio_streams, subtitle_streams, True
