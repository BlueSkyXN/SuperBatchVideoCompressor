#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SBVC (Super Batch Video Compressor) - 主入口

简洁的主入口脚本
"""

import sys
import shutil
from pathlib import Path


def _cleanup_pycache_early(project_root: Path = None) -> int:
    """
    在导入其他模块前清理 __pycache__ 和 .pyc，避免旧字节码干扰。
    使用内联实现以避免预先导入 src 下的模块。
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent

    cleaned = 0
    for pycache_dir in project_root.rglob("__pycache__"):
        try:
            shutil.rmtree(pycache_dir)
            cleaned += 1
        except Exception:
            pass

    for pyc_file in project_root.rglob("*.pyc"):
        try:
            pyc_file.unlink()
            cleaned += 1
        except Exception:
            pass

    return cleaned


_cleanup_pycache_early()

from cli import main  # noqa: E402 确保清理后再导入 CLI


if __name__ == "__main__":
    sys.exit(main())
