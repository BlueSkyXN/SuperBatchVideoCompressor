#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务层

提供可被 CLI/GUI/API 复用的批量压缩执行入口。
"""

import os
import logging
import concurrent.futures
from typing import Dict, Any, Optional

from src.core import (
    get_video_files,
    resolve_output_paths,
    get_bitrate,
    get_resolution,
    get_codec,
    execute_ffmpeg,
    calculate_target_bitrate,
    build_hw_encode_command,
    build_sw_encode_command,
)
from src.core.media_plan import build_stream_plan
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


def run_batch(config: Dict[str, Any]) -> int:
    """
    执行批量压缩任务，行为与原 CLI run 保持一致。

    Args:
        config: 已准备好的配置（含编码器检测结果、CLI覆盖、运行模式）

    Returns:
        进程退出码：0 成功，非 0 表示存在失败任务
    """
    import shutil
    import threading

    input_folder = config["paths"]["input"]
    output_folder = config["paths"]["output"]
    min_file_size = config["files"]["min_size_mb"]
    force_bitrate = config["encoding"]["bitrate"]["forced"] > 0
    forced_bitrate = config["encoding"]["bitrate"]["forced"]
    keep_structure = config["files"]["keep_structure"]
    output_codec = config["encoding"]["codec"]
    audio_bitrate = config["encoding"]["audio_bitrate"]
    max_fps = config["fps"]["max"]
    limit_fps_software_decode = config["fps"]["limit_on_software_decode"]
    limit_fps_software_encode = config["fps"]["limit_on_software_encode"]
    max_bitrate_by_resolution = config["encoding"]["bitrate"].get("max_by_resolution")
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
    logger.info(f"输入目录: {input_folder}")
    logger.info(f"输出目录: {output_folder}")
    logger.info(f"保持目录结构: {'是' if keep_structure else '否'}")
    logger.info(f"输出编码: {output_codec}")
    logger.info("-" * 60)

    stats = scheduler.get_stats()
    logger.info(f"总并发上限: {stats['max_total_concurrent']}")
    hw_encoders = stats["enabled_hw_encoders"]
    if hw_encoders:
        logger.info(f"硬件编码器: {hw_encoders}")
    logger.info(f"CPU 兜底: {'启用' if stats['cpu_fallback'] else '禁用'}")
    for enc_name, enc_stats in stats["encoder_slots"].items():
        logger.info(f"  - {enc_name}: 最大并发 {enc_stats['max']}")
    logger.info("回退策略: 硬解+硬编 → 软解+硬编 → 其他编码器 → CPU")
    logger.info("-" * 60)

    if not os.path.exists(input_folder):
        logger.error(f"输入目录不存在: {input_folder}")
        return 1

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

    os.makedirs(output_folder, exist_ok=True)

    results = []
    files_to_process = []
    completed = 0
    skipped_count = 0
    lock = threading.Lock()

    # 预检查输出是否已存在
    for filepath in video_files:
        output_path, _ = resolve_output_paths(
            filepath, input_folder, output_folder, keep_structure
        )
        if os.path.exists(output_path):
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
        files_to_process.append(filepath)

    if skipped_count > 0:
        logger.info(f"预检查: {skipped_count} 个文件已存在，跳过")

    total_tasks = len(files_to_process)
    logger.info(f"待处理: {total_tasks} 个文件")

    def build_encode_command(
        filepath: str,
        temp_filename: str,
        bitrate: int,
        source_codec: str,
        encoder_type: EncoderType,
        decode_mode: DecodeMode,
        stream_plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """根据编码器类型和解码模式构建命令"""
        hw_accel_map = {
            EncoderType.NVENC: "nvenc",
            EncoderType.QSV: "qsv",
            EncoderType.VIDEOTOOLBOX: "videotoolbox",
            EncoderType.CPU: "cpu",
        }
        hw_accel = hw_accel_map.get(encoder_type, "cpu")
        map_args = stream_plan.get("map_args") if stream_plan else None
        audio_args = stream_plan.get("audio_args") if stream_plan else None
        subtitle_args = stream_plan.get("subtitle_args") if stream_plan else None

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

        if result is None:
            # 硬件不支持此编码格式，回退到 CPU
            return build_sw_encode_command(
                filepath,
                temp_filename,
                bitrate,
                output_codec,
                limit_fps=limit_fps_software_encode,
                max_fps=max_fps,
                preset=cpu_preset,
                audio_bitrate=audio_bitrate,
                map_args=map_args,
                audio_args=audio_args,
                subtitle_args=subtitle_args,
            )

        return result

    def encode_file(
        filepath: str, encoder_type: EncoderType, decode_mode: DecodeMode
    ) -> TaskResult:
        """编码单个文件"""
        import time
        from src.core.video import get_duration, get_fps

        # 获取任务ID（从外部传入）
        task_id = getattr(encode_file, "_current_task_id", 0)
        total_tasks = getattr(encode_file, "_total_tasks", 0)
        task_label = f"{task_id}/{total_tasks}" if total_tasks > 0 else str(task_id)

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
            original_bitrate = get_bitrate(filepath)
            width, height = get_resolution(filepath)
            source_codec = get_codec(filepath)
            duration = get_duration(filepath)
            fps = get_fps(filepath)

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
            os.makedirs(os.path.dirname(new_filename), exist_ok=True)

            if os.path.exists(new_filename):
                logger.info(f"[跳过] 输出文件已存在: {new_filename}", extra=extra_ctx)
                stats["status"] = RESULT_SKIP_EXISTS
                return TaskResult(success=True, filepath=filepath, stats=stats)

            # 构建编码命令
            stream_plan = build_stream_plan(filepath, config["encoding"])
            cmd_info = build_encode_command(
                filepath,
                temp_filename,
                new_bitrate,
                source_codec,
                encoder_type,
                decode_mode,
                stream_plan=stream_plan,
            )
            cmd_info["used_audio_copy"] = stream_plan.get("used_audio_copy", False)
            cmd_info["used_subtitle_copy"] = stream_plan.get(
                "used_subtitle_copy", False
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
            success, error = execute_ffmpeg(cmd_info["cmd"])

            # copy 模式失败时，尝试一次安全回退（禁用 copy/字幕）
            if not success and (
                cmd_info.get("used_audio_copy") or cmd_info.get("used_subtitle_copy")
            ):
                from copy import deepcopy

                safe_encoding = deepcopy(config["encoding"])
                safe_encoding.setdefault("audio", {})
                safe_encoding["audio"]["copy_policy"] = "off"
                safe_encoding.setdefault("subtitles", {})
                safe_encoding["subtitles"]["keep"] = "none"

                safe_plan = build_stream_plan(filepath, safe_encoding)
                safe_cmd_info = build_encode_command(
                    filepath,
                    temp_filename,
                    new_bitrate,
                    source_codec,
                    encoder_type,
                    decode_mode,
                    stream_plan=safe_plan,
                )

                logger.warning(
                    f"[任务 {task_label}] copy/字幕保留失败，使用安全模式重试一次",
                    extra=extra_ctx,
                )
                success, error = execute_ffmpeg(safe_cmd_info["cmd"])
                if success:
                    logger.debug(
                        f"[任务 {task_label}] 安全模式重试成功",
                        extra=extra_ctx,
                    )
                    cmd_info = safe_cmd_info
                else:
                    logger.debug(
                        f"[任务 {task_label}] 安全模式重试仍失败: {error}",
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
                shutil.move(temp_filename, new_filename)
            except Exception as e:
                return TaskResult(
                    success=False, filepath=filepath, error=str(e), stats=stats
                )

            # 读取输出文件信息
            new_size = os.path.getsize(new_filename)
            output_bitrate = get_bitrate(new_filename)
            output_duration = get_duration(new_filename)
            output_codec = get_codec(new_filename)

            stats["new_size"] = new_size
            stats["output_bitrate"] = output_bitrate
            stats["output_duration"] = output_duration
            stats["output_codec"] = output_codec
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
                f"{output_codec.upper()} {output_bitrate/1000000:.2f}Mbps\n"
                f"    压缩率: {compression_ratio:.1f}% | 时长: {output_duration/60:.1f}分钟\n"
                f"    耗时: {encode_time/60:.1f}分钟 | 速度: "
                f"{speed_ratio:.2f}x | 平均: {avg_fps:.1f}fps",
                extra=extra_ctx,
            )

            return TaskResult(success=True, filepath=filepath, stats=stats)

        except Exception as e:
            logger.error(
                f"[任务 {task_label}] [异常] 处理 {filepath} 时发生错误: {e}",
                extra=extra_ctx,
            )
            return TaskResult(
                success=False, filepath=filepath, error=str(e), stats=stats
            )

    def process_file(filepath: str, task_id: int):
        nonlocal completed

        # 传递任务ID和总任务数到编码函数
        encode_file._current_task_id = task_id
        encode_file._total_tasks = total_tasks

        result = scheduler.schedule_task(filepath, encode_file)

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
