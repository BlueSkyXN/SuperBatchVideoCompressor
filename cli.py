#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SBVC (Super Batch Video Compressor) - CLI 入口

命令行参数解析和运行模式选择
"""

import os
import sys
import io
import logging
import argparse
import concurrent.futures
from typing import Dict, Any

# 强制使用UTF-8编码，解决Windows环境下中文输出问题
if sys.platform == 'win32':
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 确保可以导入 src 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import load_config, apply_cli_overrides
from src.config.defaults import (
    DEFAULT_INPUT_FOLDER,
    DEFAULT_OUTPUT_FOLDER,
    DEFAULT_LOG_FOLDER,
    DEFAULT_HW_ACCEL,
    DEFAULT_OUTPUT_CODEC,
    MIN_FILE_SIZE_MB,
    MAX_FPS,
    MAX_WORKERS,
    RESULT_SUCCESS,
    RESULT_SKIP_SIZE,
    RESULT_SKIP_EXISTS,
    RESULT_ERROR,
)
from src.core import compress_video, get_video_files, resolve_output_paths
from src.utils.logging import setup_logging
from src.utils.files import get_hw_accel_type


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='SBVC (Super Batch Video Compressor) - 超级批量视频压缩器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
使用示例:
  # 基本用法
  python main.py -i /path/to/input -o /path/to/output
  
  # 多 GPU 模式
  python main.py -i ./input -o ./output --multi-gpu
  
  # 使用配置文件
  python main.py --config ./config.yaml
        '''
    )
    
    # 基本路径参数
    parser.add_argument('-i', '--input', default=DEFAULT_INPUT_FOLDER,
                        help=f'输入文件夹路径 (默认: {DEFAULT_INPUT_FOLDER})')
    parser.add_argument('-o', '--output', default=DEFAULT_OUTPUT_FOLDER,
                        help=f'输出文件夹路径 (默认: {DEFAULT_OUTPUT_FOLDER})')
    parser.add_argument('-l', '--log', default=DEFAULT_LOG_FOLDER,
                        help=f'日志文件夹路径 (默认: {DEFAULT_LOG_FOLDER})')
    
    # 编码格式选项
    parser.add_argument('--hw-accel', '--hardware',
                        choices=['auto', 'nvenc', 'videotoolbox', 'qsv', 'none'],
                        default=DEFAULT_HW_ACCEL,
                        help=f'硬件加速类型 (默认: {DEFAULT_HW_ACCEL})')
    parser.add_argument('-c', '--codec', choices=['hevc', 'avc', 'av1'],
                        default=DEFAULT_OUTPUT_CODEC,
                        help=f'输出视频编码格式 (默认: {DEFAULT_OUTPUT_CODEC})')
    
    # 处理选项
    parser.add_argument('--min-size', type=int, default=MIN_FILE_SIZE_MB,
                        help=f'最小文件大小阈值(MB) (默认: {MIN_FILE_SIZE_MB})')
    parser.add_argument('--force-bitrate', type=int, default=0,
                        help='强制使用指定码率(bps)，0 表示自动计算')
    parser.add_argument('--no-keep-structure', action='store_true',
                        help='不保持原始目录结构')
    parser.add_argument('-w', '--workers', type=int, default=MAX_WORKERS,
                        help=f'并发处理线程数 (默认: {MAX_WORKERS})')
    
    # 编码回退选项
    parser.add_argument('--enable-software-fallback', action='store_true',
                        help='启用软件编码回退')
    parser.add_argument('--cpu-fallback', action='store_true',
                        help='启用 CPU 编码回退')
    
    # 帧率限制选项
    parser.add_argument('--no-fps-limit', action='store_true',
                        help='禁用所有帧率限制')
    parser.add_argument('--no-fps-limit-decode', action='store_true',
                        help='软件解码时不限制帧率')
    parser.add_argument('--no-fps-limit-encode', action='store_true',
                        help='软件编码时不限制帧率')
    parser.add_argument('--max-fps', type=int, default=MAX_FPS,
                        help=f'最大帧率限制 (默认: {MAX_FPS})')
    
    # 配置文件选项
    parser.add_argument('--config', type=str, default=None,
                        help='配置文件路径 (YAML 格式)')
    
    # 多 GPU 调度选项
    parser.add_argument('--multi-gpu', action='store_true',
                        help='启用多 GPU 混合调度模式')
    parser.add_argument('--encoders', type=str, default=None,
                        help='启用的编码器列表，逗号分隔 (例如: nvenc,qsv)')
    parser.add_argument('--nvenc-concurrent', type=int, default=3,
                        help='NVENC 并发任务上限 (默认: 3)')
    parser.add_argument('--qsv-concurrent', type=int, default=2,
                        help='QSV 并发任务上限 (默认: 2)')
    parser.add_argument('--cpu-concurrent', type=int, default=4,
                        help='CPU 并发任务上限 (默认: 4)')
    parser.add_argument('--max-concurrent', type=int, default=6,
                        help='总并发任务上限 (默认: 6)')
    parser.add_argument('--scheduler', choices=['priority', 'least_loaded', 'round_robin'],
                        default='priority', help='调度策略 (默认: priority)')
    parser.add_argument('--dry-run', action='store_true',
                        help='仅显示任务计划，不实际执行')
    
    return parser.parse_args()


def run_single_encoder_mode(args, config: Dict[str, Any]) -> int:
    """单编码器模式"""
    input_folder = config["paths"]["input"]
    output_folder = config["paths"]["output"]
    log_folder = config["paths"]["log"]
    min_file_size = config["files"]["min_size_mb"]
    force_bitrate = config["encoding"]["bitrate"]["forced"] > 0
    forced_bitrate = config["encoding"]["bitrate"]["forced"]
    keep_structure = config["files"]["keep_structure"]
    max_workers = args.workers
    output_codec = config["encoding"]["codec"]
    enable_software_encoding = args.enable_software_fallback or args.cpu_fallback
    limit_fps_software_decode = config["fps"]["limit_on_software_decode"]
    limit_fps_software_encode = config["fps"]["limit_on_software_encode"]
    max_fps = config["fps"]["max"]
    
    log_file = setup_logging(log_folder)
    hw_accel = get_hw_accel_type(args.hw_accel)
    
    logging.info("=" * 60)
    logging.info("SBVC - 超级批量视频压缩器 (单编码器模式)")
    logging.info("=" * 60)
    logging.info(f"输入目录: {input_folder}")
    logging.info(f"输出目录: {output_folder}")
    logging.info(f"硬件加速: {hw_accel}")
    logging.info(f"输出编码: {output_codec}")
    logging.info("-" * 60)
    
    if not os.path.exists(input_folder):
        logging.error(f"输入目录不存在: {input_folder}")
        return 1
    
    os.makedirs(output_folder, exist_ok=True)
    video_files = get_video_files(input_folder)
    total_files = len(video_files)
    
    if total_files == 0:
        logging.warning("未发现任何视频文件")
        return 0
    
    logging.info(f"发现 {total_files} 个视频文件")
    
    # 预先检查输出是否存在，减少无谓开销
    results = []
    files_to_process = []
    processed_count = 0
    for filepath in video_files:
        output_path, _ = resolve_output_paths(
            filepath, input_folder, output_folder, keep_structure
        )
        if os.path.exists(output_path):
            logging.info(f"[跳过] 输出文件已存在(预检查): {output_path}")
            results.append((filepath, (RESULT_SKIP_EXISTS, None, {})))
            processed_count += 1
            continue
        files_to_process.append(filepath)
    
    def process_file(filepath):
        return compress_video(
            filepath=filepath,
            input_folder=input_folder,
            output_folder=output_folder,
            keep_structure=keep_structure,
            force_bitrate=force_bitrate,
            forced_bitrate=forced_bitrate,
            min_file_size_mb=min_file_size,
            hw_accel=hw_accel,
            output_codec=output_codec,
            enable_software_encoding=enable_software_encoding,
            limit_fps_software_decode=limit_fps_software_decode,
            limit_fps_software_encode=limit_fps_software_encode,
            max_fps=max_fps
        )
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(process_file, f): f for f in files_to_process}
        for future in concurrent.futures.as_completed(future_to_file):
            filepath = future_to_file[future]
            try:
                result = future.result()
                results.append((filepath, result))
            except Exception as e:
                results.append((filepath, (RESULT_ERROR, str(e), {})))
            processed_count += 1
            logging.info(f"[进度] {processed_count}/{total_files} ({processed_count/total_files*100:.1f}%)")
    
    return summarize_results(results, total_files)


def run_multi_encoder_mode(args, config: Dict[str, Any]) -> int:
    """多编码器混合调度模式"""
    from src.scheduler import HybridScheduler, create_scheduler_from_config, EncoderType
    from src.scheduler.pool import TaskResult
    
    input_folder = config["paths"]["input"]
    output_folder = config["paths"]["output"]
    log_folder = config["paths"]["log"]
    min_file_size = config["files"]["min_size_mb"]
    force_bitrate = config["encoding"]["bitrate"]["forced"] > 0
    forced_bitrate = config["encoding"]["bitrate"]["forced"]
    keep_structure = config["files"]["keep_structure"]
    output_codec = config["encoding"]["codec"]
    max_fps = config["fps"]["max"]
    limit_fps_software_decode = config["fps"]["limit_on_software_decode"]
    limit_fps_software_encode = config["fps"]["limit_on_software_encode"]
    
    log_file = setup_logging(log_folder)
    scheduler = create_scheduler_from_config(config)
    
    logging.info("=" * 60)
    logging.info("SBVC - 超级批量视频压缩器 (多 GPU 混合调度模式)")
    logging.info("=" * 60)
    
    scheduler_stats = scheduler.get_stats()
    logging.info(f"调度策略: {scheduler_stats['strategy']}")
    logging.info(f"启用编码器: {', '.join(scheduler_stats['enabled_encoders'])}")
    logging.info("-" * 60)
    
    if args.dry_run:
        video_files = get_video_files(input_folder)
        logging.info(f"[DRY RUN] 发现 {len(video_files)} 个视频文件")
        return 0
    
    if not os.path.exists(input_folder):
        logging.error(f"输入目录不存在: {input_folder}")
        return 1
    
    os.makedirs(output_folder, exist_ok=True)
    video_files = get_video_files(input_folder)
    total_files = len(video_files)
    
    if total_files == 0:
        logging.warning("未发现任何视频文件")
        return 0
    
    logging.info(f"发现 {total_files} 个视频文件")
    
    results = []
    files_to_process = []
    completed = 0
    
    # 预检查输出是否已存在，先行跳过
    for filepath in video_files:
        output_path, _ = resolve_output_paths(
            filepath, input_folder, output_folder, keep_structure
        )
        if os.path.exists(output_path):
            logging.info(f"[跳过] 输出文件已存在(预检查): {output_path}")
            results.append((filepath, TaskResult(success=True, stats={"status": RESULT_SKIP_EXISTS})))
            completed += 1
            continue
        files_to_process.append(filepath)
    
    import threading
    
    def encode_with_encoder(filepath: str, encoder_type: EncoderType) -> TaskResult:
        hw_accel_map = {
            EncoderType.NVENC: "nvenc",
            EncoderType.QSV: "qsv",
            EncoderType.VIDEOTOOLBOX: "videotoolbox",
            EncoderType.CPU: "none",
        }
        hw_accel = hw_accel_map.get(encoder_type, "none")
        
        result = compress_video(
            filepath=filepath,
            input_folder=input_folder,
            output_folder=output_folder,
            keep_structure=keep_structure,
            force_bitrate=force_bitrate,
            forced_bitrate=forced_bitrate,
            min_file_size_mb=min_file_size,
            hw_accel=hw_accel,
            output_codec=output_codec,
            enable_software_encoding=(encoder_type == EncoderType.CPU),
            limit_fps_software_decode=limit_fps_software_decode,
            limit_fps_software_encode=limit_fps_software_encode,
            max_fps=max_fps
        )
        
        status, error, stats = result
        stats["status"] = status
        return TaskResult(
            success=(status == RESULT_SUCCESS or status == RESULT_SKIP_SIZE or status == RESULT_SKIP_EXISTS),
            error=error,
            stats=stats
        )
    
    lock = threading.Lock()
    
    def process_file_with_scheduler(filepath: str):
        nonlocal completed
        
        def task_func(encoder_type: EncoderType) -> TaskResult:
            return encode_with_encoder(filepath, encoder_type)
        
        result = scheduler.schedule_task(task_func)
        
        with lock:
            completed += 1
            logging.info(f"[进度] {completed}/{total_files} ({completed/total_files*100:.1f}%)")
        
        return (filepath, result)
    
    max_workers = config["scheduler"]["max_total_concurrent"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_file_with_scheduler, f) for f in files_to_process]
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                logging.error(f"任务异常: {e}")
    
    skip_exists_count = sum(1 for _, r in results if r.stats.get("status") == RESULT_SKIP_EXISTS)
    skip_size_count = sum(1 for _, r in results if r.stats.get("status") == RESULT_SKIP_SIZE)
    success_count = sum(
        1 for _, r in results
        if r.success and r.stats.get("status") not in (RESULT_SKIP_SIZE, RESULT_SKIP_EXISTS)
    )
    fail_count = len(results) - success_count - skip_exists_count - skip_size_count
    
    logging.info("=" * 60)
    logging.info(
        f"总文件数: {total_files}, 成功: {success_count}, 跳过(文件过小): {skip_size_count}, "
        f"跳过(已存在): {skip_exists_count}, 失败: {fail_count}"
    )
    logging.info("=" * 60)
    
    return 0 if fail_count == 0 else 1


def summarize_results(results: list, total_files: int) -> int:
    """统计并输出结果摘要"""
    success_count = 0
    skip_size_count = 0
    skip_exists_count = 0
    fail_count = 0
    total_original_size = 0
    total_new_size = 0
    
    for filepath, (status, error, stats) in results:
        if status == RESULT_SUCCESS:
            success_count += 1
            total_original_size += stats.get("original_size", 0)
            total_new_size += stats.get("new_size", 0)
        elif status == RESULT_SKIP_SIZE:
            skip_size_count += 1
        elif status == RESULT_SKIP_EXISTS:
            skip_exists_count += 1
        else:
            fail_count += 1
    
    logging.info("=" * 60)
    logging.info("任务完成统计")
    logging.info("=" * 60)
    logging.info(f"总文件数: {total_files}")
    logging.info(f"成功压缩: {success_count}")
    logging.info(f"跳过(文件过小): {skip_size_count}")
    logging.info(f"跳过(已存在): {skip_exists_count}")
    logging.info(f"失败: {fail_count}")
    
    if success_count > 0 and total_original_size > 0:
        total_saved = total_original_size - total_new_size
        compression_ratio = (1 - total_new_size / total_original_size) * 100
        logging.info("-" * 60)
        logging.info(f"原始总大小: {total_original_size/1024/1024/1024:.2f} GB")
        logging.info(f"压缩后大小: {total_new_size/1024/1024/1024:.2f} GB")
        logging.info(f"节省空间: {total_saved/1024/1024/1024:.2f} GB ({compression_ratio:.1f}%)")
    
    logging.info("=" * 60)
    return 0 if fail_count == 0 else 1


def main():
    """主函数"""
    args = parse_arguments()
    
    try:
        config = load_config(args.config)
        config = apply_cli_overrides(config, args)
        
        if args.multi_gpu:
            return run_multi_encoder_mode(args, config)
        else:
            return run_single_encoder_mode(args, config)
        
    except KeyboardInterrupt:
        logging.warning("用户中断操作")
        return 130
    except Exception as e:
        logging.critical(f"程序执行过程中发生严重错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
