#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务层

提供可被 CLI/GUI/API 复用的批量压缩执行入口。
"""

import os
import logging
import concurrent.futures
from typing import Dict, Any

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
from src.config.defaults import (
    MIN_FILE_SIZE_MB,
    RESULT_SUCCESS,
    RESULT_SKIP_SIZE,
    RESULT_SKIP_EXISTS,
)
from src.scheduler.advanced import (
    AdvancedScheduler,
    DecodeMode,
    EncoderType,
    create_advanced_scheduler,
    TaskResult,
)
from src.utils.process import terminate_all_ffmpeg


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
    max_fps = config["fps"]["max"]
    limit_fps_software_decode = config["fps"]["limit_on_software_decode"]
    limit_fps_software_encode = config["fps"]["limit_on_software_encode"]
    max_bitrate_by_resolution = config["encoding"]["bitrate"].get("max_by_resolution")
    cpu_preset = config.get("encoders", {}).get("cpu", {}).get("preset", "medium")
    dry_run = config.get("dry_run", False)

    # 创建高级调度器
    scheduler = create_advanced_scheduler(config)

    logging.info("=" * 60)
    logging.info("SBVC - 超级批量视频压缩器")
    logging.info("=" * 60)

    # 显示路径配置
    logging.info(f"输入目录: {input_folder}")
    logging.info(f"输出目录: {output_folder}")
    logging.info(f"保持目录结构: {'是' if keep_structure else '否'}")
    logging.info(f"输出编码: {output_codec}")
    logging.info("-" * 60)

    stats = scheduler.get_stats()
    logging.info(f"总并发上限: {stats['max_total_concurrent']}")
    hw_encoders = stats['enabled_hw_encoders']
    if hw_encoders:
        logging.info(f"硬件编码器: {hw_encoders}")
    logging.info(f"CPU 兜底: {'启用' if stats['cpu_fallback'] else '禁用'}")
    for enc_name, enc_stats in stats['encoder_slots'].items():
        logging.info(f"  - {enc_name}: 最大并发 {enc_stats['max']}")
    logging.info("回退策略: 硬解+硬编 → 软解+硬编 → 其他编码器 → CPU")
    logging.info("-" * 60)

    if not os.path.exists(input_folder):
        logging.error(f"输入目录不存在: {input_folder}")
        return 1

    # 预扫描任务列表
    video_files = get_video_files(input_folder)
    total_files = len(video_files)

    if total_files == 0:
        logging.warning("未发现任何视频文件")
        return 0

    logging.info(f"发现 {total_files} 个视频文件")

    # 显示路径映射示例（帮助用户确认目录结构）
    if total_files > 0:
        if keep_structure:
            logging.info("路径映射示例（保持目录结构）:")
            for i, sample_file in enumerate(video_files[:3], 1):
                sample_output, _ = resolve_output_paths(
                    sample_file, input_folder, output_folder, keep_structure
                )
                rel_path = os.path.relpath(sample_file, input_folder)
                logging.info(f"  {i}. {rel_path} → {os.path.relpath(sample_output, output_folder)}")
            if total_files > 3:
                logging.info(f"  ... 还有 {total_files - 3} 个文件")
        else:
            logging.warning("注意：未保持目录结构，所有文件将输出到同一目录")
            logging.info("路径映射示例（扁平化输出）:")
            for i, sample_file in enumerate(video_files[:3], 1):
                sample_output, _ = resolve_output_paths(
                    sample_file, input_folder, output_folder, keep_structure
                )
                logging.info(f"  {i}. {os.path.basename(sample_file)} → {os.path.basename(sample_output)}")
            if total_files > 3:
                logging.info(f"  ... 还有 {total_files - 3} 个文件")
            logging.warning("如需保持目录结构，请在配置文件中设置 keep_structure: true 或移除 --no-keep-structure 参数")

    if dry_run:
        logging.info(f"[DRY RUN] 预览模式，不实际执行")
        for i, f in enumerate(video_files[:10], 1):
            logging.info(f"  {i}. {os.path.basename(f)}")
        if total_files > 10:
            logging.info(f"  ... 还有 {total_files - 10} 个文件")
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
            logging.info(f"[跳过] 输出已存在: {os.path.basename(output_path)}")
            results.append((filepath, TaskResult(success=True, filepath=filepath, stats={"status": RESULT_SKIP_EXISTS})))
            skipped_count += 1
            continue
        files_to_process.append(filepath)

    if skipped_count > 0:
        logging.info(f"预检查: {skipped_count} 个文件已存在，跳过")

    logging.info(f"待处理: {len(files_to_process)} 个文件")

    def build_encode_command(
        filepath: str,
        temp_filename: str,
        bitrate: int,
        source_codec: str,
        encoder_type: EncoderType,
        decode_mode: DecodeMode
    ) -> Dict[str, Any]:
        """根据编码器类型和解码模式构建命令"""
        hw_accel_map = {
            EncoderType.NVENC: "nvenc",
            EncoderType.QSV: "qsv",
            EncoderType.VIDEOTOOLBOX: "videotoolbox",
            EncoderType.CPU: "cpu",
        }
        hw_accel = hw_accel_map.get(encoder_type, "cpu")

        # CPU 软编码
        if encoder_type == EncoderType.CPU:
            limit_fps = (decode_mode == DecodeMode.SW_DECODE_LIMITED and limit_fps_software_encode)
            return build_sw_encode_command(
                filepath, temp_filename, bitrate, output_codec,
                limit_fps=limit_fps, max_fps=max_fps, preset=cpu_preset
            )

        # 硬件编码
        use_hw_decode = (decode_mode == DecodeMode.HW_DECODE)
        limit_fps = (decode_mode == DecodeMode.SW_DECODE_LIMITED and limit_fps_software_decode)

        result = build_hw_encode_command(
            filepath, temp_filename, bitrate, source_codec, hw_accel, output_codec,
            use_hw_decode=use_hw_decode, limit_fps=limit_fps, max_fps=max_fps
        )

        if result is None:
            # 硬件不支持此编码格式，回退到 CPU
            return build_sw_encode_command(
                filepath, temp_filename, bitrate, output_codec,
                limit_fps=limit_fps_software_encode, max_fps=max_fps, preset=cpu_preset
            )

        return result

    def encode_file(filepath: str, encoder_type: EncoderType, decode_mode: DecodeMode) -> TaskResult:
        """编码单个文件"""
        stats = {"original_size": 0, "new_size": 0, "original_bitrate": 0, "new_bitrate": 0}

        try:
            file_size = os.path.getsize(filepath)
            stats["original_size"] = file_size

            if file_size < min_file_size * 1024 * 1024:
                logging.info(f"[跳过] 文件小于 {min_file_size}MB: {filepath}")
                stats["status"] = RESULT_SKIP_SIZE
                return TaskResult(success=True, filepath=filepath, stats=stats)

            original_bitrate = get_bitrate(filepath)
            width, height = get_resolution(filepath)
            source_codec = get_codec(filepath)
            stats["original_bitrate"] = original_bitrate

            new_bitrate = calculate_target_bitrate(
                original_bitrate, width, height,
                force_bitrate, forced_bitrate,
                max_bitrate_by_resolution
            )
            stats["new_bitrate"] = new_bitrate

            new_filename, temp_filename = resolve_output_paths(
                filepath, input_folder, output_folder, keep_structure
            )
            os.makedirs(os.path.dirname(new_filename), exist_ok=True)

            if os.path.exists(new_filename):
                logging.info(f"[跳过] 输出文件已存在: {new_filename}")
                stats["status"] = RESULT_SKIP_EXISTS
                return TaskResult(success=True, filepath=filepath, stats=stats)

            # 构建编码命令
            cmd_info = build_encode_command(
                filepath, temp_filename, new_bitrate, source_codec,
                encoder_type, decode_mode
            )

            logging.info(f"[编码] {encoder_type.value}/{decode_mode.value}: {os.path.basename(filepath)} -> {cmd_info['name']}")

            # 打印完整的 ffmpeg 命令
            cmd_str = ' '.join(f'"{arg}"' if ' ' in str(arg) else str(arg) for arg in cmd_info["cmd"])
            logging.info(f"FFmpeg 命令: {cmd_str}")

            # 执行编码
            success, error = execute_ffmpeg(cmd_info["cmd"])

            if not success:
                if os.path.exists(temp_filename):
                    try:
                        os.remove(temp_filename)
                    except Exception as e:
                        logging.warning(f"临时文件删除失败: {temp_filename}, 错误: {e}")
                return TaskResult(success=False, filepath=filepath, error=error, stats=stats)

            # 移动文件
            try:
                shutil.move(temp_filename, new_filename)
            except Exception as e:
                return TaskResult(success=False, filepath=filepath, error=str(e), stats=stats)

            new_size = os.path.getsize(new_filename)
            stats["new_size"] = new_size
            stats["status"] = RESULT_SUCCESS
            stats["method"] = cmd_info['name']

            compression_ratio = (1 - new_size / file_size) * 100 if file_size > 0 else 0
            logging.info(
                f"[完成] {encoder_type.value}: {os.path.basename(filepath)} | "
                f"{cmd_info['name']} | 压缩率: {compression_ratio:.1f}%"
            )

            return TaskResult(success=True, filepath=filepath, stats=stats)

        except Exception as e:
            logging.error(f"[异常] 处理 {filepath} 时发生错误: {e}")
            return TaskResult(success=False, filepath=filepath, error=str(e), stats=stats)

    def process_file(filepath: str):
        nonlocal completed

        result = scheduler.schedule_task(filepath, encode_file)

        with lock:
            completed += 1
            retry_info = ""
            if result.retry_history:
                retry_info = f" [尝试: {' → '.join(result.retry_history)}]"
            logging.info(f"[进度] {completed}/{total_files} ({completed/total_files*100:.1f}%){retry_info}")

        return (filepath, result)

    # 使用线程池并发处理
    max_workers = scheduler.max_total_concurrent
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_file, f) for f in files_to_process]
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    logging.error(f"任务异常: {e}")
    finally:
        scheduler.shutdown()

    # 统计结果
    skip_exists_count = sum(1 for _, r in results if r.stats.get("status") == RESULT_SKIP_EXISTS)
    skip_size_count = sum(1 for _, r in results if r.stats.get("status") == RESULT_SKIP_SIZE)
    success_count = sum(
        1 for _, r in results
        if r.success and r.stats.get("status") not in (RESULT_SKIP_SIZE, RESULT_SKIP_EXISTS)
    )
    fail_count = len(results) - success_count - skip_exists_count - skip_size_count

    # 统计编码器使用情况
    encoder_usage = {}
    for _, r in results:
        if r.encoder_used:
            enc = r.encoder_used.value
            encoder_usage[enc] = encoder_usage.get(enc, 0) + 1

    logging.info("=" * 60)
    logging.info("任务完成统计")
    logging.info("-" * 60)
    logging.info(
        f"总文件数: {total_files}, 成功: {success_count}, 跳过(文件过小): {skip_size_count}, "
        f"跳过(已存在): {skip_exists_count}, 失败: {fail_count}"
    )
    if encoder_usage:
        logging.info(f"编码器使用统计: {encoder_usage}")

    # 显示调度器最终统计
    final_stats = scheduler.get_stats()
    logging.info("编码器详细统计:")
    for enc_name, enc_stats in final_stats['encoder_slots'].items():
        logging.info(f"  - {enc_name}: 完成 {enc_stats['completed']}, 失败 {enc_stats['failed']}")
    logging.info("=" * 60)

    return 0 if fail_count == 0 else 1
