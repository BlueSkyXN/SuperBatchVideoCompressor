#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
进程管理模块

管理 FFmpeg 子进程，支持优雅退出时清理所有进程
"""

import os
import shutil
import signal
import logging
import threading
from pathlib import Path
from typing import Set

# 全局进程集合和锁
_ffmpeg_processes: Set = set()
_process_lock = threading.Lock()
_shutdown_requested = False


def register_process(process) -> None:
    """
    注册一个 FFmpeg 进程到全局集合
    
    Args:
        process: subprocess.Popen 对象
    """
    with _process_lock:
        _ffmpeg_processes.add(process)


def unregister_process(process) -> None:
    """
    从全局集合中移除一个 FFmpeg 进程
    
    Args:
        process: subprocess.Popen 对象
    """
    with _process_lock:
        _ffmpeg_processes.discard(process)


def is_shutdown_requested() -> bool:
    """
    检查是否请求了关闭
    
    Returns:
        是否请求了关闭
    """
    return _shutdown_requested


def terminate_all_ffmpeg() -> None:
    """
    终止所有注册的 FFmpeg 进程
    """
    global _shutdown_requested
    _shutdown_requested = True
    
    with _process_lock:
        processes = list(_ffmpeg_processes)
    
    if not processes:
        return
    
    logging.info(f"正在终止 {len(processes)} 个 FFmpeg 进程...")
    
    for process in processes:
        try:
            if process.poll() is None:  # 进程仍在运行
                process.terminate()
                logging.debug(f"已发送 SIGTERM 到进程 {process.pid}")
        except Exception as e:
            logging.warning(f"终止进程时出错: {e}")
    
    # 等待进程退出，如果超时则强制杀死
    for process in processes:
        try:
            if process.poll() is None:
                process.wait(timeout=3)
        except Exception:
            try:
                process.kill()
                logging.debug(f"已发送 SIGKILL 到进程 {process.pid}")
            except Exception:
                pass
    
    logging.info("所有 FFmpeg 进程已终止")


def cleanup_temp_files(output_folder: str) -> int:
    """
    清理输出目录中的临时文件
    
    Args:
        output_folder: 输出文件夹路径
        
    Returns:
        清理的文件数量
    """
    if not os.path.exists(output_folder):
        return 0
    
    cleaned_count = 0
    
    for root, _, files in os.walk(output_folder):
        for file in files:
            # 检查是否匹配临时文件模式
            is_temp = (
                file.startswith("tmp_") or 
                file.endswith(".tmp") or 
                file.endswith(".temp")
            )
            if is_temp:
                filepath = os.path.join(root, file)
                try:
                    os.remove(filepath)
                    logging.info(f"[清理] 删除临时文件: {filepath}")
                    cleaned_count += 1
                except Exception as e:
                    logging.warning(f"[清理] 删除临时文件失败 {filepath}: {e}")
    
    return cleaned_count


def cleanup_pycache(project_root: str = None) -> int:
    """
    清理 Python 字节码缓存目录
    
    解决代码更新后旧缓存导致的类定义不一致问题
    
    Args:
        project_root: 项目根目录，默认为当前脚本所在目录的父目录
        
    Returns:
        清理的目录数量
    """
    if project_root is None:
        # 获取项目根目录 (src/utils/process.py -> project root)
        project_root = Path(__file__).parent.parent.parent
    
    project_root = Path(project_root)
    cleaned_count = 0
    
    # 查找所有 __pycache__ 目录
    for pycache_dir in project_root.rglob("__pycache__"):
        try:
            shutil.rmtree(pycache_dir)
            cleaned_count += 1
        except Exception as e:
            logging.debug(f"清理缓存目录失败 {pycache_dir}: {e}")
    
    # 清理 .pyc 文件（可能在某些情况下存在于源码目录）
    for pyc_file in project_root.rglob("*.pyc"):
        try:
            pyc_file.unlink()
            cleaned_count += 1
        except Exception:
            pass
    
    if cleaned_count > 0:
        logging.debug(f"已清理 {cleaned_count} 个 Python 缓存目录/文件")
    
    return cleaned_count


def setup_signal_handlers() -> None:
    """
    设置信号处理器，捕获 SIGINT (Ctrl+C) 和 SIGTERM
    """
    def signal_handler(signum, frame):
        sig_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
        logging.warning(f"收到 {sig_name} 信号，正在清理...")
        terminate_all_ffmpeg()
        raise KeyboardInterrupt()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
