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
    DEFAULT_OUTPUT_CODEC,
    MIN_FILE_SIZE_MB,
    MAX_FPS,
    RESULT_SUCCESS,
    RESULT_SKIP_SIZE,
    RESULT_SKIP_EXISTS,
    RESULT_ERROR,
)
from src.core import get_video_files, resolve_output_paths
from src.utils.logging import setup_logging
from src.utils.process import setup_signal_handlers, cleanup_temp_files, cleanup_pycache, terminate_all_ffmpeg
from src.utils.encoder_check import detect_available_encoders, print_encoder_status


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='SBVC (Super Batch Video Compressor) - 超级批量视频压缩器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
使用示例:
  # 基本用法
  python main.py -i /path/to/input -o /path/to/output
  
  # 使用配置文件（推荐）
  python main.py --config ./config.yaml
  
  # 预览任务（不实际执行）
  python main.py --config ./config.yaml --dry-run
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
    
    # 帧率限制选项
    parser.add_argument('--no-fps-limit', action='store_true',
                        help='禁用所有帧率限制')
    parser.add_argument('--max-fps', type=int, default=MAX_FPS,
                        help=f'最大帧率限制 (默认: {MAX_FPS})')
    
    # 配置文件选项
    parser.add_argument('--config', type=str, default=None,
                        help='配置文件路径 (YAML 格式)')
    
    # 调度选项
    parser.add_argument('--max-concurrent', type=int, default=5,
                        help='总并发任务上限 (默认: 5)')
    parser.add_argument('--dry-run', action='store_true',
                        help='仅显示任务计划，不实际执行')
    
    return parser.parse_args()


def run(args, config: Dict[str, Any]) -> int:
    """运行视频压缩任务
    
    调度策略：
    1. 启用的硬件编码器并发处理不同文件
    2. 失败任务智能回退：同编码器降级 → 其他编码器 → CPU兜底
    3. 所有方法都失败的任务跳过，继续处理队列
    """
    import shutil
    import threading
    from src.scheduler.advanced import (
        AdvancedScheduler, DecodeMode, EncoderType, create_advanced_scheduler, TaskResult
    )
    from src.core import (
        get_video_files, resolve_output_paths, get_bitrate, get_resolution, get_codec,
        execute_ffmpeg, calculate_target_bitrate,
        build_hw_encode_command, build_sw_encode_command
    )
    from src.config.defaults import AUDIO_BITRATE
    
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
    
    # 创建高级调度器
    scheduler = create_advanced_scheduler(config)
    
    logging.info("=" * 60)
    logging.info("SBVC - 超级批量视频压缩器")
    logging.info("=" * 60)
    
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
    
    if args.dry_run:
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
            
            # 执行编码
            success, error = execute_ffmpeg(cmd_info["cmd"])
            
            if not success:
                if os.path.exists(temp_filename):
                    try:
                        os.remove(temp_filename)
                    except:
                        pass
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
        
        # 设置信号处理器
        setup_signal_handlers()
        
        # 设置日志（需要先设置，才能记录清理信息）
        log_folder = config["paths"]["log"]
        setup_logging(log_folder)
        
        # 启动时清理临时文件
        output_folder = config["paths"]["output"]
        cleaned = cleanup_temp_files(output_folder)
        if cleaned > 0:
            logging.info(f"启动清理: 删除 {cleaned} 个临时文件")
        
        # 检测编码器可用性
        logging.info("检测编码器可用性...")
        encoder_configs = config.get("encoders", {})
        checked_configs = detect_available_encoders(encoder_configs)
        config["encoders"] = checked_configs
        
        # 检查是否有可用编码器
        hw_available = any(
            cfg.get("enabled", False) 
            for name, cfg in checked_configs.items() 
            if name != "cpu"
        )
        cpu_available = checked_configs.get("cpu", {}).get("enabled", False)
        
        if not hw_available and not cpu_available:
            logging.error("没有可用的编码器！请检查硬件和驱动。")
            return 1
        
        return run(args, config)
        
    except KeyboardInterrupt:
        logging.warning("用户中断操作")
        terminate_all_ffmpeg()
        return 130
    except Exception as e:
        logging.critical(f"程序执行过程中发生严重错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
