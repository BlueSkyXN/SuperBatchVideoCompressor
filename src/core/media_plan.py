#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
媒体流(音频/字幕)处理策略决策

基于 ffprobe 探测到的 streams + encoding 配置，
生成显式 -map 与 per-stream 编解码参数列表。
"""

import logging
from typing import Any, Dict, List, Optional

from src.core.streams import AudioStreamInfo, SubtitleStreamInfo, probe_streams

logger = logging.getLogger(__name__)


def _parse_bitrate_to_bps(value: Any) -> Optional[int]:
    """
    解析如 "128k"/"1M"/"192000" 为 bps。
    返回 None 表示无法解析或未配置。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().lower()
    if not s or s == "null":
        return None
    try:
        if s.endswith("k"):
            return int(float(s[:-1]) * 1000)
        if s.endswith("m"):
            return int(float(s[:-1]) * 1000 * 1000)
        if s.endswith("g"):
            return int(float(s[:-1]) * 1000 * 1000 * 1000)
        return int(float(s))
    except ValueError:
        return None


def _language_matches(stream_lang: Optional[str], prefer_lang: str) -> bool:
    if not stream_lang:
        return False
    sl = stream_lang.lower()
    pl = prefer_lang.lower()
    return sl == pl or sl.startswith(pl)


def _select_audio_streams(
    audio_streams: List[AudioStreamInfo], audio_cfg: Dict[str, Any]
) -> List[AudioStreamInfo]:
    keep_mode = str(audio_cfg.get("tracks", {}).get("keep", "first")).lower()
    prefer_langs = audio_cfg.get("tracks", {}).get("prefer_language") or []
    drop_commentary = bool(audio_cfg.get("tracks", {}).get("drop_commentary", False))

    candidates = (
        [s for s in audio_streams if not s.is_commentary]
        if drop_commentary
        else list(audio_streams)
    )

    if not candidates:
        return []

    if keep_mode == "all":
        return candidates

    if keep_mode == "language_prefer":
        for lang in prefer_langs:
            for s in candidates:
                if _language_matches(s.language, str(lang)):
                    return [s]
        # 语言未命中，优先默认音轨
        defaults = [s for s in candidates if s.is_default]
        if defaults:
            return [defaults[0]]
        return [candidates[0]]

    # first / unknown
    return [candidates[0]]


def _select_subtitle_streams(
    subtitle_streams: List[SubtitleStreamInfo], subtitles_cfg: Dict[str, Any]
) -> List[SubtitleStreamInfo]:
    languages = subtitles_cfg.get("languages") or []
    if not subtitle_streams:
        return []
    if not languages:
        return list(subtitle_streams)

    selected: List[SubtitleStreamInfo] = []
    for s in subtitle_streams:
        if not s.language:
            continue
        if any(_language_matches(s.language, str(lang)) for lang in languages):
            selected.append(s)
    return selected


def _decide_audio_action(
    stream: AudioStreamInfo,
    audio_cfg: Dict[str, Any],
    target_bitrate_bps: Optional[int],
) -> str:
    policy = str(audio_cfg.get("copy_policy", "off")).lower()
    allow_codecs = [str(c).lower() for c in (audio_cfg.get("copy_allow_codecs") or [])]
    max_ratio = float(audio_cfg.get("copy_max_bitrate_ratio", 1.0))

    source_codec = (stream.codec_name or "unknown").lower()
    source_bitrate = stream.bit_rate

    if policy == "off":
        return "transcode"

    if policy == "always":
        return "copy" if source_codec in allow_codecs else "transcode"

    # 需要码率条件时的保守判定
    if target_bitrate_bps is None or source_bitrate is None:
        bitrate_ok = True if target_bitrate_bps is None else False
    else:
        bitrate_ok = source_bitrate <= target_bitrate_bps * max_ratio

    if policy == "aac_only":
        return "copy" if source_codec == "aac" and bitrate_ok else "transcode"

    if policy == "smart":
        return "copy" if source_codec in allow_codecs and bitrate_ok else "transcode"

    return "transcode"


def build_stream_plan(filepath: str, encoding_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    生成音频/字幕映射与 per-stream 参数计划。

    Returns:
        {
          "map_args": [...],
          "audio_args": [...],
          "subtitle_args": [...],
          "used_audio_copy": bool,
          "used_subtitle_copy": bool,
        }
    """
    audio_cfg = encoding_cfg.get("audio") or {}
    subtitles_cfg = encoding_cfg.get("subtitles") or {}

    # 如果未启用任何高级音频/字幕策略，直接走旧版行为，避免每个文件额外 ffprobe
    copy_policy = str(audio_cfg.get("copy_policy", "off")).lower()
    tracks_cfg = audio_cfg.get("tracks") or {}
    tracks_keep = str(tracks_cfg.get("keep", "first")).lower()
    drop_commentary = bool(tracks_cfg.get("drop_commentary", False))
    channels_cfg = str(audio_cfg.get("channels", "keep")).lower()
    sample_rate_cfg = str(audio_cfg.get("sample_rate", "keep")).lower()
    subtitles_keep = str(subtitles_cfg.get("keep", "none")).lower()
    audio_enabled = bool(audio_cfg.get("enabled", True))

    needs_probe = (
        copy_policy != "off"
        or tracks_keep != "first"
        or drop_commentary
        or channels_cfg != "keep"
        or sample_rate_cfg != "keep"
        or subtitles_keep != "none"
    )

    if not needs_probe:
        logger.debug("未启用音频/字幕高级策略，跳过 ffprobe")
        simple_audio_args = ["-an"] if not audio_enabled else None
        return {
            "map_args": None,
            "audio_args": simple_audio_args,
            "subtitle_args": ["-sn"],
            "used_audio_copy": False,
            "used_subtitle_copy": False,
        }

    audio_streams, subtitle_streams, probe_ok = probe_streams(filepath)

    # ffprobe 失败时，退化为旧版默认行为：不显式 map，按旧逻辑统一 AAC 重编码，不保留字幕
    if not probe_ok:
        logger.warning("ffprobe 失败，音频/字幕策略退化为旧版默认行为")
        return {
            "map_args": None,
            "audio_args": None,
            "subtitle_args": ["-sn"],
            "used_audio_copy": False,
            "used_subtitle_copy": False,
        }

    map_args: List[str] = ["-map", "0:v:0"]
    audio_args: List[str] = []
    subtitle_args: List[str] = []

    used_audio_copy = False
    used_subtitle_copy = False

    # --------------- 音频 ---------------
    audio_enabled = bool(audio_cfg.get("enabled", True))
    if not audio_enabled:
        audio_args.extend(["-an"])
    else:
        selected_audio = _select_audio_streams(audio_streams, audio_cfg)
        logger.debug(
            f"选中音轨: {[s.index for s in selected_audio]} (keep={tracks_keep})"
        )

        target_bitrate_str = audio_cfg.get("target_bitrate")
        if target_bitrate_str is None:
            target_bitrate_str = encoding_cfg.get("audio_bitrate")
        target_bitrate_bps = _parse_bitrate_to_bps(target_bitrate_str)
        target_codec = str(audio_cfg.get("target_codec", "aac"))

        channels_cfg = str(audio_cfg.get("channels", "keep")).lower()
        sample_rate_cfg = str(audio_cfg.get("sample_rate", "keep")).lower()
        aac_adtstoasc = bool(audio_cfg.get("aac_adtstoasc", True))

        for out_idx, stream in enumerate(selected_audio):
            # 使用全局 stream index 进行映射，避免多音轨字段相同导致的歧义
            map_args.extend(["-map", f"0:{stream.index}"])

            action = _decide_audio_action(stream, audio_cfg, target_bitrate_bps)
            if action == "copy":
                logger.debug(
                    f"音轨{out_idx} 使用 copy: {stream.codec_name}@{stream.bit_rate}bps"
                )
                audio_args.extend([f"-c:a:{out_idx}", "copy"])
                used_audio_copy = True
                if aac_adtstoasc and stream.codec_name == "aac":
                    audio_args.extend([f"-bsf:a:{out_idx}", "aac_adtstoasc"])
                continue

            # transcode
            logger.debug(
                f"音轨{out_idx} 转码为 {target_codec}@{target_bitrate_str}"
            )
            audio_args.extend([f"-c:a:{out_idx}", target_codec])
            if target_bitrate_str:
                audio_args.extend([f"-b:a:{out_idx}", str(target_bitrate_str)])

            if channels_cfg != "keep":
                ch_map = {"stereo": 2, "mono": 1, "5.1": 6}
                if channels_cfg in ch_map:
                    audio_args.extend([f"-ac:a:{out_idx}", str(ch_map[channels_cfg])])
            if sample_rate_cfg != "keep":
                if sample_rate_cfg.isdigit():
                    audio_args.extend([f"-ar:a:{out_idx}", sample_rate_cfg])

    # --------------- 字幕 ---------------
    subtitles_keep = str(subtitles_cfg.get("keep", "none")).lower()
    if subtitles_keep != "none":
        selected_subs = _select_subtitle_streams(subtitle_streams, subtitles_cfg)
        logger.debug(
            f"选中字轨: {[s.index for s in selected_subs]} (keep={subtitles_keep})"
        )
        for out_idx, s in enumerate(selected_subs):
            map_args.extend(["-map", f"0:{s.index}"])
            if subtitles_keep == "copy":
                subtitle_args.extend([f"-c:s:{out_idx}", "copy"])
                used_subtitle_copy = True
            else:
                subtitle_args.extend([f"-c:s:{out_idx}", "mov_text"])
    else:
        subtitle_args.extend(["-sn"])

    return {
        "map_args": map_args,
        "audio_args": audio_args,
        "subtitle_args": subtitle_args,
        "used_audio_copy": used_audio_copy,
        "used_subtitle_copy": used_subtitle_copy,
    }
