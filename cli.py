#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SBVC (Super Batch Video Compressor) - CLI 入口

命令行参数解析和运行模式选择
"""

import logging
import argparse
import sys

from src.bootstrap import enforce_utf8_windows, prepare_environment
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
)
from src.service import run_batch
from src.utils.process import terminate_all_ffmpeg

# 确保 Windows 下输出编码正确
enforce_utf8_windows()


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
        # 环境准备（编码、缓存/临时文件清理、日志、信号、编码器检测）
        config = prepare_environment(config)
        
        # 检查是否有可用编码器
        encoders_cfg = config.get("encoders", {})
        hw_available = any(
            cfg.get("enabled", False) 
            for name, cfg in encoders_cfg.items() 
            if name != "cpu"
        )
        cpu_available = encoders_cfg.get("cpu", {}).get("enabled", False)
        
        if not hw_available and not cpu_available:
            logging.error("没有可用的编码器！请检查硬件和驱动。")
            return 1

        return run_batch(config)
        
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
