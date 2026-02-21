#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务层

提供可被 CLI/GUI/API 复用的批量压缩执行入口。
"""

import os
import logging
import concurrent.futures
from typing import Dict, Any, Optional, List

from src.core import (
    get_video_files,
    resolve_output_paths,
    get_bitrate,
    get_codec,
    get_video_metadata_batch,
    execute_ffmpeg,
    calculate_target_bitrate,
    build_hw_encode_command,
    build_sw_encode_command,
    is_decode_corruption_error,
    add_ignore_decode_errors_flags,
)
from src.config.defaults import (
    RESULT_SUCCESS,
    RESULT_SKIP_SIZE,
    RESULT_SKIP_EXISTS,
)
from src.scheduler.advanced import (
    DecodeMode,
    EncoderType,
    create_advanced_scheduler,
    TaskResult,
)

logger = logging.getLogger(__name__)


def sanitize_for_log(value: Any) -> str:
    """移除换行/制表符，避免日志注入。"""
    return str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")


def run_batch(config: Dict[str, Any]) -> int:
    """
    执行批量压缩任务，行为与原 CLI run 保持一致。

    Args:
        config: 已准备好的配置（含编码器检测结果、CLI覆盖、运行模式）

    Returns:
        进程退出码：0 成功，非 0 表示存在失败任务
    """
    import threading

    input_folder = config["paths"]["input"]
    output_folder = config["paths"]["output"]
    min_file_size = config["files"]["min_size_mb"]
    force_bitrate = config["encoding"]["bitrate"]["forced"] > 0
    forced_bitrate = config["encoding"]["bitrate"]["forced"]
    keep_structure = config["files"]["keep_structure"]
    skip_existing = config["files"].get("skip_existing", True)
    output_codec = config["encoding"]["codec"]
    audio_bitrate = config["encoding"]["audio_bitrate"]
    max_fps = config["fps"]["max"]
    limit_fps_software_decode = config["fps"]["limit_on_software_decode"]
    limit_fps_software_encode = config["fps"]["limit_on_software_encode"]
    max_bitrate_by_resolution = config["encoding"]["bitrate"].get("max_by_resolution")
    error_recovery_cfg = config.get("error_recovery", {})
    retry_decode_errors_with_ignore = error_recovery_cfg.get(
        "retry_decode_errors_with_ignore", True
    )
    max_ignore_retries_per_method = error_recovery_cfg.get(
        "max_ignore_retries_per_method", 1
    )
    try:
        max_ignore_retries_per_method = int(max_ignore_retries_per_method)
    except (TypeError, ValueError):
        max_ignore_retries_per_method = 1
    max_ignore_retries_per_method = max(0, max_ignore_retries_per_method)

    cpu_preset = config.get("encoders", {}).get("cpu", {}).get("preset", "medium")
    dry_run = config.get("dry_run", False)
    logging_cfg = config.get("logging", {})
    show_progress = logging_cfg.get("show_progress", True)
    print_cmd = logging_cfg.get("print_cmd", False)
    log_file_path = logging_cfg.get("log_file")
    level_value = logging_cfg.get("level", "INFO")
    if isinstance(level_value, int):
        verbose_logging = level_value <= logging.DEBUG
    else:
        verbose_logging = str(level_value).upper() == "DEBUG"

    # 创建高级调度器
    scheduler = create_advanced_scheduler(config)

    logger.info("=" * 60)
    logger.info("SBVC - 超级批量视频压缩器")
    logger.info("=" * 60)

    # 显示路径配置
    logger.info(f"输入目录: {sanitize_for_log(input_folder)}")
    logger.info(f"输出目录: {sanitize_for_log(output_folder)}")
    logger.info(f"保持目录结构: {'是' if keep_structure else '否'}")
    logger.info(f"输出编码: {output_codec}")
    logger.info("-" * 60)

    stats = scheduler.get_stats()
    logger.info(f"总并发上限: {stats['max_total_concurrent']}")
    hw_encoders = stats["enabled_hw_encoders"]
    if hw_encoders:
        logger.info(f"硬件编码器: {hw_encoders}")
    logger.info(f"CPU 兜底: {'启用' if stats['cpu_fallback'] else '禁用'}")
    if retry_decode_errors_with_ignore and max_ignore_retries_per_method > 0:
        logger.info(
            "解码错误容错: 启用 "
            f"(每种编码方法最多重试 {max_ignore_retries_per_method} 次)"
        )
    else:
        logger.info("解码错误容错: 禁用")
    for enc_name, enc_stats in stats["encoder_slots"].items():
        logger.info(f"  - {enc_name}: 最大并发 {enc_stats['max']}")
    logger.info("回退策略: 硬解+硬编 → 软解+硬编 → 其他编码器 → CPU")
    logger.info("-" * 60)

    if not os.path.exists(input_folder):
        logger.error(f"输入目录不存在: {sanitize_for_log(input_folder)}")
        return 1
    if not os.path.isdir(input_folder):
        logger.error(f"输入路径不是目录: {sanitize_for_log(input_folder)}")
        return 1
    if not os.access(input_folder, os.R_OK | os.X_OK):
        logger.error(f"输入目录无读取权限: {sanitize_for_log(input_folder)}")
        return 1
    if os.path.islink(input_folder):
        logger.warning(f"输入目录是符号链接: {sanitize_for_log(input_folder)}")

    # 预扫描任务列表
    video_files = get_video_files(input_folder)
    total_files = len(video_files)

    if total_files == 0:
        logger.warning("未发现任何视频文件")
        return 0

    logger.info(f"发现 {total_files} 个视频文件")

    # 显示路径映射示例（帮助用户确认目录结构）
    if total_files > 0:
        if keep_structure:
            logger.info("路径映射示例（保持目录结构）:")
            for i, sample_file in enumerate(video_files[:3], 1):
                sample_output, _ = resolve_output_paths(
                    sample_file, input_folder, output_folder, keep_structure
                )
                rel_path = os.path.relpath(sample_file, input_folder)
                logger.info(
                    f"  {i}. {rel_path} → "
                    f"{os.path.relpath(sample_output, output_folder)}"
                )
            if total_files > 3:
                logger.info(f"  ... 还有 {total_files - 3} 个文件")
        else:
            logger.warning("注意：未保持目录结构，所有文件将输出到同一目录")
            logger.info("路径映射示例（扁平化输出）:")
            for i, sample_file in enumerate(video_files[:3], 1):
                sample_output, _ = resolve_output_paths(
                    sample_file, input_folder, output_folder, keep_structure
                )
                logger.info(
                    f"  {i}. {os.path.basename(sample_file)} → "
                    f"{os.path.basename(sample_output)}"
                )
            if total_files > 3:
                logger.info(f"  ... 还有 {total_files - 3} 个文件")
            logger.warning(
                "如需保持目录结构，请在配置文件中设置 keep_structure: true 或移除 --no-keep-structure 参数"
            )

    if dry_run:
        logger.info("[DRY RUN] 预览模式，不实际执行")
        for i, f in enumerate(video_files[:10], 1):
            logger.info(f"  {i}. {os.path.basename(f)}")
        if total_files > 10:
            logger.info(f"  ... 还有 {total_files - 10} 个文件")
        return 0

    os.makedirs(output_folder, mode=0o755, exist_ok=True)

    results = []
    files_to_process = []
    completed = 0
    skipped_count = 0
    overwrite_count = 0
    lock = threading.Lock()

    # 预检查输出是否已存在
    for filepath in video_files:
        output_path, _ = resolve_output_paths(
            filepath, input_folder, output_folder, keep_structure
        )
        if os.path.exists(output_path) and skip_existing:
            logger.info(
                f"[SKIP] 输出已存在: {os.path.basename(output_path)}",
                extra={"file": os.path.basename(filepath)},
            )
            results.append(
                (
                    filepath,
                    TaskResult(
                        success=True,
                        filepath=filepath,
                        stats={"status": RESULT_SKIP_EXISTS},
                    ),
                )
            )
            skipped_count += 1
            continue
        if os.path.exists(output_path) and not skip_existing:
            overwrite_count += 1
        files_to_process.append(filepath)

    if skipped_count > 0:
        logger.info(f"预检查: {skipped_count} 个文件已存在，跳过")
    if overwrite_count > 0:
        logger.warning(
            f"预检查: {overwrite_count} 个输出已存在，将覆盖（skip_existing=false）"
        )

    total_tasks = len(files_to_process)
    logger.info(f"待处理: {total_tasks} 个文件")

    def build_encode_command(
        filepath: str,
        temp_filename: str,
        bitrate: int,
        source_codec: str,
        encoder_type: EncoderType,
        decode_mode: DecodeMode,
        audio_args: Optional[List[str]] = None,
        subtitle_args: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """根据编码器类型和解码模式构建命令"""
        hw_accel_map = {
            EncoderType.NVENC: "nvenc",
            EncoderType.QSV: "qsv",
            EncoderType.VIDEOTOOLBOX: "videotoolbox",
            EncoderType.CPU: "cpu",
        }
        hw_accel = hw_accel_map.get(encoder_type, "cpu")
        map_args = None

        # CPU 软编码
        if encoder_type == EncoderType.CPU:
            limit_fps = (
                decode_mode == DecodeMode.SW_DECODE_LIMITED
                and limit_fps_software_encode
            )
            return build_sw_encode_command(
                filepath,
                temp_filename,
                bitrate,
                output_codec,
                limit_fps=limit_fps,
                max_fps=max_fps,
                preset=cpu_preset,
                audio_bitrate=audio_bitrate,
                map_args=map_args,
                audio_args=audio_args,
                subtitle_args=subtitle_args,
            )

        # 硬件编码
        use_hw_decode = decode_mode == DecodeMode.HW_DECODE
        limit_fps = (
            decode_mode == DecodeMode.SW_DECODE_LIMITED and limit_fps_software_decode
        )

        result = build_hw_encode_command(
            filepath,
            temp_filename,
            bitrate,
            source_codec,
            hw_accel,
            output_codec,
            use_hw_decode=use_hw_decode,
            limit_fps=limit_fps,
            max_fps=max_fps,
            audio_bitrate=audio_bitrate,
            map_args=map_args,
            audio_args=audio_args,
            subtitle_args=subtitle_args,
        )

        return result

    def normalize_audio_mode(value: Any) -> str:
        mode = str(value or "transcode").strip().lower()
        if mode in ("off", "copy", "transcode", "auto"):
            return mode
        return "transcode"

    def resolve_audio_mode(audio_cfg: Dict[str, Any]) -> str:
        raw_mode = audio_cfg.get("mode")
        if raw_mode not in (None, "", "null"):
            return normalize_audio_mode(raw_mode)

        # 向后兼容：旧配置里 audio.enabled=false 表示关闭音频
        if audio_cfg.get("enabled") is False:
            return "off"

        # 向后兼容：旧配置里 copy_policy!=off 表示尝试 copy（简化后等价于 auto）
        copy_policy = str(audio_cfg.get("copy_policy", "off")).strip().lower()
        if copy_policy and copy_policy != "off":
            return "auto"

        return "transcode"

    def build_audio_args(encoding_cfg: Dict[str, Any], mode: str) -> List[str]:
        audio_cfg = encoding_cfg.get("audio") or {}
        mode = normalize_audio_mode(mode)

        if mode == "off":
            return ["-an"]
        if mode == "copy":
            return ["-c:a", "copy"]

        codec = str(audio_cfg.get("codec") or audio_cfg.get("target_codec") or "aac")
        codec = codec.strip() or "aac"
        bitrate = audio_cfg.get("bitrate")
        if bitrate is None:
            bitrate = audio_cfg.get("target_bitrate")
        if bitrate is None:
            bitrate = encoding_cfg.get("audio_bitrate") or audio_bitrate

        args = ["-c:a", codec]
        if bitrate not in (None, "", "null"):
            args.extend(["-b:a", str(bitrate)])
        return args

    def encode_file(
        filepath: str,
        encoder_type: EncoderType,
        decode_mode: DecodeMode,
        *,
        task_id: int = 0,
        total_tasks_count: int = 0,
    ) -> TaskResult:
        """编码单个文件"""
        import time
        from src.core.encoder import parse_bitrate_to_bps
        from src.core.video import get_duration, get_audio_bitrate

        task_label = (
            f"{task_id}/{total_tasks_count}" if total_tasks_count > 0 else str(task_id)
        )

        extra_ctx = {
            "file": os.path.basename(filepath),
            "enc": encoder_type.value,
            "decode": decode_mode.value,
            "task_id": task_id,
        }
        stats = {
            "original_size": 0,
            "new_size": 0,
            "original_bitrate": 0,
            "new_bitrate": 0,
            "encode_time": 0,
            "task_id": task_id,
        }

        try:
            file_size = os.path.getsize(filepath)
            stats["original_size"] = file_size

            if file_size < min_file_size * 1024 * 1024:
                logger.info(
                    f"[跳过] 文件小于 {min_file_size}MB: {filepath}",
                    extra=extra_ctx,
                )
                stats["status"] = RESULT_SKIP_SIZE
                return TaskResult(success=True, filepath=filepath, stats=stats)

            # 获取源文件信息
            metadata = get_video_metadata_batch(filepath) or {}
            original_bitrate = int(metadata.get("bitrate") or 0)
            width = int(metadata.get("width") or 0)
            height = int(metadata.get("height") or 0)
            source_codec = str(metadata.get("codec") or "unknown")
            duration = float(metadata.get("duration") or 0.0)
            fps = float(metadata.get("fps") or 0.0)

            if original_bitrate <= 0:
                original_bitrate = get_bitrate(filepath)
            if width <= 0 or height <= 0:
                from src.core.video import get_resolution

                width, height = get_resolution(filepath)
            if source_codec == "unknown":
                source_codec = get_codec(filepath)
            if duration <= 0:
                duration = get_duration(filepath)

            stats["original_bitrate"] = original_bitrate
            stats["duration"] = duration
            stats["width"] = width
            stats["height"] = height
            stats["source_codec"] = source_codec
            stats["fps"] = fps

            new_bitrate = calculate_target_bitrate(
                original_bitrate,
                width,
                height,
                force_bitrate,
                forced_bitrate,
                max_bitrate_by_resolution,
            )
            stats["target_bitrate"] = new_bitrate

            new_filename, temp_filename = resolve_output_paths(
                filepath, input_folder, output_folder, keep_structure
            )
            os.makedirs(os.path.dirname(new_filename), mode=0o755, exist_ok=True)

            if os.path.exists(new_filename) and skip_existing:
                logger.info(f"[跳过] 输出文件已存在: {new_filename}", extra=extra_ctx)
                stats["status"] = RESULT_SKIP_EXISTS
                return TaskResult(success=True, filepath=filepath, stats=stats)

            encoding_cfg = config.get("encoding", {})
            audio_cfg = encoding_cfg.get("audio") or {}
            audio_mode = resolve_audio_mode(audio_cfg)

            # 方案1：不做显式 -map，不做 ffprobe 音轨探测
            # 始终 -sn 丢弃字幕，音频按 mode 决定 copy/转码/关闭
            subtitle_args = ["-sn"]
            audio_copy_fallback = False
            retry_audio_args = None

            if audio_mode == "auto":
                audio_copy_fallback = True
                audio_args = build_audio_args(encoding_cfg, "copy")
                retry_audio_args = build_audio_args(encoding_cfg, "transcode")
            elif audio_mode == "transcode":
                transcode_audio_args = build_audio_args(encoding_cfg, "transcode")
                target_bps = None
                if "-b:a" in transcode_audio_args:
                    idx = transcode_audio_args.index("-b:a")
                    if idx + 1 < len(transcode_audio_args):
                        target_bps = parse_bitrate_to_bps(transcode_audio_args[idx + 1])

                source_audio_bps = (
                    get_audio_bitrate(filepath) if target_bps is not None else None
                )
                if (
                    source_audio_bps is not None
                    and target_bps is not None
                    and source_audio_bps <= target_bps
                ):
                    audio_copy_fallback = True
                    retry_audio_args = transcode_audio_args
                    audio_args = build_audio_args(encoding_cfg, "copy")
                    logger.debug(
                        f"[任务 {task_label}] 音频源码率 {source_audio_bps/1000:.0f}kbps "
                        f"<= 目标 {target_bps/1000:.0f}kbps，改用 copy",
                        extra=extra_ctx,
                    )
                else:
                    audio_args = transcode_audio_args
            else:
                audio_args = build_audio_args(encoding_cfg, audio_mode)

            # 构建编码命令
            cmd_info = build_encode_command(
                filepath,
                temp_filename,
                new_bitrate,
                source_codec,
                encoder_type,
                decode_mode,
                audio_args=audio_args,
                subtitle_args=subtitle_args,
            )
            if cmd_info is None:
                error_msg = f"{encoder_type.value} 不支持输出编码 {output_codec}"
                logger.warning(
                    f"[任务 {task_label}] [失败] {error_msg}",
                    extra=extra_ctx,
                )
                return TaskResult(
                    success=False,
                    filepath=filepath,
                    error=error_msg,
                    stats=stats,
                )

            # 获取文件相对路径
            rel_path = os.path.relpath(filepath, input_folder)
            logger.info(
                f"[任务 {task_label}] [开始编码] {rel_path}\n"
                f"    编码器: {cmd_info['name']}\n"
                f"    源信息: {width}x{height} {source_codec.upper()} "
                f"{original_bitrate/1000000:.2f}Mbps {fps:.1f}fps {duration/60:.1f}分钟",
                extra=extra_ctx,
            )

            # 打印完整的 ffmpeg 命令
            cmd_str = " ".join(
                f'"{arg}"' if " " in str(arg) else str(arg) for arg in cmd_info["cmd"]
            )
            if print_cmd or verbose_logging:
                logger.info(f"[命令] {cmd_str}", extra=extra_ctx)
            else:
                logger.debug(f"[命令] {cmd_str}", extra=extra_ctx)

            # 记录开始时间
            start_time = time.time()

            # 执行编码
            # 动态超时：按视频时长放大 10 倍，覆盖编码/IO波动，并限制在 5 分钟到 2 小时之间。
            timeout_duration = duration if duration > 0 else 30
            ffmpeg_timeout = max(300, min(int(timeout_duration * 10), 7200))
            success, error = execute_ffmpeg(cmd_info["cmd"], timeout=ffmpeg_timeout)

            # audio.mode=auto 或 transcode+按码率改用copy：优先 copy，失败则回退转码重试一次
            if not success and audio_copy_fallback and retry_audio_args is not None:
                retry_cmd_info = build_encode_command(
                    filepath,
                    temp_filename,
                    new_bitrate,
                    source_codec,
                    encoder_type,
                    decode_mode,
                    audio_args=retry_audio_args,
                    subtitle_args=subtitle_args,
                )
                if retry_cmd_info is None:
                    logger.debug(
                        f"[任务 {task_label}] audio 回退命令构建失败（编码器不支持）",
                        extra=extra_ctx,
                    )
                else:
                    logger.warning(
                        f"[任务 {task_label}] 音频 copy 失败，回退转码重试一次",
                        extra=extra_ctx,
                    )
                    cmd_info = retry_cmd_info
                    success, error = execute_ffmpeg(
                        cmd_info["cmd"], timeout=ffmpeg_timeout
                    )
                    if success:
                        logger.debug(
                            f"[任务 {task_label}] 音频回退转码重试成功",
                            extra=extra_ctx,
                        )

            # 检测到源流损坏/解码错误时，注入忽错参数重试（同编码方法内）
            if (
                not success
                and retry_decode_errors_with_ignore
                and max_ignore_retries_per_method > 0
                and is_decode_corruption_error(error)
            ):
                tolerant_cmd = add_ignore_decode_errors_flags(cmd_info["cmd"])

                if tolerant_cmd != cmd_info["cmd"]:
                    for attempt in range(1, max_ignore_retries_per_method + 1):
                        logger.warning(
                            f"[任务 {task_label}] 检测到疑似源流损坏，"
                            "启用忽错容错重试 "
                            f"{attempt}/{max_ignore_retries_per_method}",
                            extra=extra_ctx,
                        )
                        success, error = execute_ffmpeg(
                            tolerant_cmd, timeout=ffmpeg_timeout
                        )
                        if success:
                            logger.warning(
                                f"[任务 {task_label}] 忽错容错重试成功",
                                extra=extra_ctx,
                            )
                            cmd_info = {
                                **cmd_info,
                                "cmd": tolerant_cmd,
                                "name": f"{cmd_info['name']} + 忽错容错",
                            }
                            break
                else:
                    logger.debug(
                        f"[任务 {task_label}] 当前命令已包含忽错参数，跳过重复注入",
                        extra=extra_ctx,
                    )

            # 计算耗时
            encode_time = time.time() - start_time
            stats["encode_time"] = encode_time

            if not success:
                if error:
                    logger.error(
                        f"[任务 {task_label}] [失败] FFmpeg 错误: {error}",
                        extra=extra_ctx,
                    )
                if os.path.exists(temp_filename):
                    try:
                        os.remove(temp_filename)
                    except Exception as e:
                        logger.warning(
                            f"临时文件删除失败: {temp_filename}, 错误: {e}",
                            extra=extra_ctx,
                        )
                return TaskResult(
                    success=False, filepath=filepath, error=error, stats=stats
                )

            # 移动文件
            try:
                if skip_existing and os.path.exists(new_filename):
                    os.remove(temp_filename)
                    stats["status"] = RESULT_SKIP_EXISTS
                    return TaskResult(success=True, filepath=filepath, stats=stats)
                os.replace(temp_filename, new_filename)
            except Exception as e:
                return TaskResult(
                    success=False, filepath=filepath, error=str(e), stats=stats
                )

            # 读取输出文件信息
            new_size = os.path.getsize(new_filename)
            output_bitrate = get_bitrate(new_filename)
            output_duration = get_duration(new_filename)
            output_video_codec = get_codec(new_filename)

            stats["new_size"] = new_size
            stats["output_bitrate"] = output_bitrate
            stats["output_duration"] = output_duration
            stats["output_codec"] = output_video_codec
            stats["status"] = RESULT_SUCCESS
            stats["method"] = cmd_info["name"]

            # 计算各种统计数据
            compression_ratio = (1 - new_size / file_size) * 100 if file_size > 0 else 0
            speed_ratio = duration / encode_time if encode_time > 0 else 0
            avg_fps = (
                (fps * duration) / encode_time
                if encode_time > 0 and duration > 0
                else 0
            )

            # 格式化文件大小
            def format_size(size_bytes):
                for unit in ["B", "KB", "MB", "GB"]:
                    if size_bytes < 1024:
                        return f"{size_bytes:.2f}{unit}"
                    size_bytes /= 1024
                return f"{size_bytes:.2f}TB"

            # 详细的完成日志
            logger.info(
                f"[任务 {task_label}] [完成] {rel_path}\n"
                f"    编码器: {encoder_type.value.upper()} | 模式: {cmd_info['name']}\n"
                f"    输入: {format_size(file_size)} "
                f"{source_codec.upper()} {original_bitrate/1000000:.2f}Mbps\n"
                f"    输出: {format_size(new_size)} "
                f"{output_video_codec.upper()} {output_bitrate/1000000:.2f}Mbps\n"
                f"    压缩率: {compression_ratio:.1f}% | 时长: {output_duration/60:.1f}分钟\n"
                f"    耗时: {encode_time/60:.1f}分钟 | 速度: "
                f"{speed_ratio:.2f}x | 平均: {avg_fps:.1f}fps",
                extra=extra_ctx,
            )

            return TaskResult(success=True, filepath=filepath, stats=stats)

        except Exception as e:
            logger.error(
                f"[任务 {task_label}] [异常] 处理 {sanitize_for_log(filepath)} 时发生错误: {e}",
                extra=extra_ctx,
            )
            return TaskResult(
                success=False, filepath=filepath, error=str(e), stats=stats
            )

    def process_file(filepath: str, task_id: int):
        nonlocal completed

        def encode_with_task_context(
            fp: str, encoder_type: EncoderType, decode_mode: DecodeMode
        ) -> TaskResult:
            return encode_file(
                fp,
                encoder_type,
                decode_mode,
                task_id=task_id,
                total_tasks_count=total_tasks,
            )

        result = scheduler.schedule_task(filepath, encode_with_task_context)

        with lock:
            completed += 1
            retry_info = ""
            if result.retry_history:
                retry_info = f" [重试路径: {' → '.join(result.retry_history)}]"
            if show_progress:
                logger.info(
                    f"[进度] {completed}/{total_tasks} "
                    f"({completed/total_tasks*100:.1f}%){retry_info}",
                    extra={"file": os.path.basename(filepath), "task_id": task_id},
                )

        return (filepath, result)

    # 使用线程池并发处理
    # 为每个文件预先分配任务ID（从1开始）
    max_workers = scheduler.max_total_concurrent
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(process_file, f, idx + 1)
                for idx, f in enumerate(files_to_process)
            ]
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    logger.error(f"任务异常: {e}")
    finally:
        scheduler.shutdown()

    # 统计结果
    skip_exists_count = sum(
        1 for _, r in results if r.stats.get("status") == RESULT_SKIP_EXISTS
    )
    skip_size_count = sum(
        1 for _, r in results if r.stats.get("status") == RESULT_SKIP_SIZE
    )
    success_count = sum(
        1
        for _, r in results
        if r.success
        and r.stats.get("status") not in (RESULT_SKIP_SIZE, RESULT_SKIP_EXISTS)
    )
    fail_count = len(results) - success_count - skip_exists_count - skip_size_count

    # 统计编码器使用情况
    encoder_usage = {}
    for _, r in results:
        if r.encoder_used:
            enc = r.encoder_used.value
            encoder_usage[enc] = encoder_usage.get(enc, 0) + 1

    logger.info("=" * 60)
    logger.info("任务完成统计")
    logger.info("-" * 60)
    logger.info(f"发现文件: {total_files}")
    if skipped_count > 0:
        logger.info(f"预检查跳过(已存在): {skipped_count}")
    logger.info(
        f"待处理: {total_tasks}, 成功: {success_count}, 跳过(文件过小): {skip_size_count}, "
        f"跳过(已存在): {skip_exists_count}, 失败: {fail_count}"
    )
    if encoder_usage:
        logger.info(f"编码器使用统计: {encoder_usage}")

    # 显示调度器最终统计
    final_stats = scheduler.get_stats()
    logger.info("编码器详细统计:")
    for enc_name, enc_stats in final_stats["encoder_slots"].items():
        logger.info(
            f"  - {enc_name}: 完成 {enc_stats['completed']}, 失败 {enc_stats['failed']}"
        )
    if log_file_path:
        logger.info(f"日志文件: {log_file_path}")
    logger.info("=" * 60)

    return 0 if fail_count == 0 else 1
