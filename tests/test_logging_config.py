#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""针对日志/CLI 覆盖的新行为进行单元测试。"""

import logging
import json
from types import SimpleNamespace

from src.config.loader import apply_cli_overrides
from src.utils.logging import setup_logging


def test_apply_cli_overrides_logging_flags(tmp_path):
    base_config = {
        "paths": {"input": "in", "output": "out", "log": str(tmp_path)},
        "logging": {
            "level": "INFO",
            "plain": False,
            "json_console": False,
            "show_progress": True,
            "print_cmd": False,
        },
    }

    args = SimpleNamespace(
        input="in",
        output="out",
        log=str(tmp_path),
        codec=None,
        force_bitrate=0,
        max_fps=30,
        no_fps_limit=False,
        no_fps_limit_decode=False,
        no_fps_limit_encode=False,
        min_size=10,
        no_keep_structure=False,
        max_concurrent=5,
        dry_run=False,
        verbose=1,
        quiet=0,
        plain=True,
        json_logs=True,
        no_progress=True,
        print_cmd=True,
    )

    cfg = apply_cli_overrides(base_config, args)
    log_cfg = cfg["logging"]
    assert log_cfg["level"] == "DEBUG"  # verbose 触发 DEBUG
    assert log_cfg["plain"] is True
    assert log_cfg["json_console"] is True
    assert log_cfg["show_progress"] is False
    assert log_cfg["print_cmd"] is True


def test_apply_cli_overrides_quiet_levels(tmp_path):
    base_config = {
        "paths": {"input": "in", "output": "out", "log": str(tmp_path)},
        "logging": {},
    }
    # quiet=1 -> WARNING, quiet=2 -> ERROR
    args = SimpleNamespace(
        input="in",
        output="out",
        log=str(tmp_path),
        codec=None,
        force_bitrate=0,
        max_fps=30,
        no_fps_limit=False,
        no_fps_limit_decode=False,
        no_fps_limit_encode=False,
        min_size=10,
        no_keep_structure=False,
        max_concurrent=5,
        dry_run=False,
        verbose=0,
        quiet=2,
        plain=False,
        json_logs=False,
        no_progress=False,
        print_cmd=False,
    )
    cfg = apply_cli_overrides(base_config, args)
    assert cfg["logging"]["level"] == "ERROR"


def test_setup_logging_plain_and_json(tmp_path, capsys):
    log_dir = tmp_path / "logs"
    log_file = setup_logging(
        str(log_dir),
        level="INFO",
        plain=True,
        json_console=True,
        console_level=logging.INFO,
    )
    assert log_dir.exists()
    assert log_file.endswith(".log")

    logger = logging.getLogger("test_logger")
    logger.info("hello", extra={"file": "demo.mp4", "enc": "nvenc"})

    captured = capsys.readouterr().out.strip()
    data = json.loads(captured)
    assert data["msg"] == "hello"
    assert data["file"] == "demo.mp4"
    assert data["enc"] == "nvenc"
