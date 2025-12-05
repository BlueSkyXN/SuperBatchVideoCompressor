#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SBVC (Super Batch Video Compressor) - 主入口

简洁的主入口脚本
"""

import sys
import io

# 强制使用UTF-8编码，解决Windows环境下中文输出问题
if sys.platform == 'win32':
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 启动前清理 Python 缓存，避免旧的 .pyc 文件导致类定义不一致
from src.utils.process import cleanup_pycache
cleanup_pycache()

from cli import main

if __name__ == "__main__":
    exit(main())
