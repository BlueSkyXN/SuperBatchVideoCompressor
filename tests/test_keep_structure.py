#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
目录保持功能测试
"""

import pytest
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.compressor import resolve_output_paths


class TestResolveOutputPaths:
    """测试 resolve_output_paths 函数"""

    def test_keep_structure_root_file(self):
        """测试保持目录结构 - 根目录文件"""
        input_folder = "/input"
        output_folder = "/output"
        filepath = "/input/video.mkv"

        new_filename, temp_filename = resolve_output_paths(
            filepath, input_folder, output_folder, keep_structure=True
        )

        assert new_filename == "/output/video.mp4"
        assert temp_filename == "/output/tmp_video.mp4"
        assert os.path.dirname(new_filename) == output_folder

    def test_keep_structure_single_level_subdir(self):
        """测试保持目录结构 - 一级子目录"""
        input_folder = "/input"
        output_folder = "/output"
        filepath = "/input/Season 01/episode01.mkv"

        new_filename, temp_filename = resolve_output_paths(
            filepath, input_folder, output_folder, keep_structure=True
        )

        assert new_filename == "/output/Season 01/episode01.mp4"
        assert temp_filename == "/output/Season 01/tmp_episode01.mp4"
        # 验证目录结构保持
        assert "Season 01" in new_filename
        assert os.path.dirname(new_filename) == "/output/Season 01"

    def test_keep_structure_multi_level_subdir(self):
        """测试保持目录结构 - 多级子目录"""
        input_folder = "/input"
        output_folder = "/output"
        filepath = "/input/Movies/2024/Action/movie.mkv"

        new_filename, temp_filename = resolve_output_paths(
            filepath, input_folder, output_folder, keep_structure=True
        )

        assert new_filename == "/output/Movies/2024/Action/movie.mp4"
        assert temp_filename == "/output/Movies/2024/Action/tmp_movie.mp4"
        # 验证完整的目录结构
        assert "Movies/2024/Action" in new_filename
        assert os.path.dirname(new_filename) == "/output/Movies/2024/Action"

    def test_keep_structure_chinese_path(self):
        """测试保持目录结构 - 中文路径"""
        input_folder = "/input"
        output_folder = "/output"
        filepath = "/input/测试中文/视频文件.mkv"

        new_filename, temp_filename = resolve_output_paths(
            filepath, input_folder, output_folder, keep_structure=True
        )

        assert new_filename == "/output/测试中文/视频文件.mp4"
        assert "测试中文" in new_filename

    def test_no_keep_structure_root_file(self):
        """测试不保持目录结构 - 根目录文件"""
        input_folder = "/input"
        output_folder = "/output"
        filepath = "/input/video.mkv"

        new_filename, temp_filename = resolve_output_paths(
            filepath, input_folder, output_folder, keep_structure=False
        )

        assert new_filename == "/output/video.mp4"
        assert temp_filename == "/output/tmp_video.mp4"
        assert os.path.dirname(new_filename) == output_folder

    def test_no_keep_structure_subdir_file(self):
        """测试不保持目录结构 - 子目录文件"""
        input_folder = "/input"
        output_folder = "/output"
        filepath = "/input/Season 01/episode01.mkv"

        new_filename, temp_filename = resolve_output_paths(
            filepath, input_folder, output_folder, keep_structure=False
        )

        # 文件应该直接输出到输出根目录，不保持子目录结构
        assert new_filename == "/output/episode01.mp4"
        assert temp_filename == "/output/tmp_episode01.mp4"
        assert os.path.dirname(new_filename) == output_folder
        assert "Season 01" not in new_filename

    def test_no_keep_structure_multi_level(self):
        """测试不保持目录结构 - 多级子目录"""
        input_folder = "/input"
        output_folder = "/output"
        filepath = "/input/Movies/2024/Action/movie.mkv"

        new_filename, temp_filename = resolve_output_paths(
            filepath, input_folder, output_folder, keep_structure=False
        )

        # 文件应该直接输出到输出根目录
        assert new_filename == "/output/movie.mp4"
        assert os.path.dirname(new_filename) == output_folder
        assert "Movies" not in new_filename
        assert "2024" not in new_filename
        assert "Action" not in new_filename

    def test_file_extension_conversion(self):
        """测试文件扩展名转换"""
        input_folder = "/input"
        output_folder = "/output"

        # 测试各种视频格式转换为 mp4
        test_cases = [
            ("/input/video.mkv", "/output/video.mp4"),
            ("/input/video.avi", "/output/video.mp4"),
            ("/input/video.flv", "/output/video.mp4"),
            ("/input/video.mov", "/output/video.mp4"),
            ("/input/video.wmv", "/output/video.mp4"),
        ]

        for filepath, expected_output in test_cases:
            new_filename, _ = resolve_output_paths(
                filepath, input_folder, output_folder, keep_structure=True
            )
            assert new_filename == expected_output

    def test_windows_style_paths(self):
        """测试 Windows 风格路径"""
        input_folder = "L:/input"
        output_folder = "J:/Output3"
        filepath = "L:/input/Season 01/video.mkv"

        new_filename, temp_filename = resolve_output_paths(
            filepath, input_folder, output_folder, keep_structure=True
        )

        # 验证路径保持了子目录结构
        assert "Season 01" in new_filename.replace("\\", "/")
        assert new_filename.endswith(".mp4")

    def test_temp_filename_location(self):
        """测试临时文件位置"""
        input_folder = "/input"
        output_folder = "/output"

        # 测试根目录文件
        filepath = "/input/video.mkv"
        new_filename, temp_filename = resolve_output_paths(
            filepath, input_folder, output_folder, keep_structure=True
        )
        assert os.path.dirname(temp_filename) == os.path.dirname(new_filename)
        temp_prefix = Path(output_folder).joinpath("tmp_").as_posix()
        assert Path(temp_filename).as_posix().startswith(temp_prefix)

        # 测试子目录文件
        filepath = "/input/subdir/video.mkv"
        new_filename, temp_filename = resolve_output_paths(
            filepath, input_folder, output_folder, keep_structure=True
        )
        assert os.path.dirname(temp_filename) == os.path.dirname(new_filename)
        assert os.path.basename(temp_filename) == "tmp_video.mp4"


class TestPathMappingConsistency:
    """测试路径映射的一致性"""

    def test_relative_path_preservation(self):
        """测试相对路径保持一致"""
        input_folder = "/input"
        output_folder = "/output"

        test_files = [
            "/input/A/B/video.mkv",
            "/input/X/Y/Z/video.mkv",
            "/input/测试/中文/路径/video.mkv",
        ]

        for filepath in test_files:
            new_filename, _ = resolve_output_paths(
                filepath, input_folder, output_folder, keep_structure=True
            )

            # 计算相对路径
            rel_input = os.path.relpath(filepath, input_folder)
            rel_output = os.path.relpath(new_filename, output_folder)

            # 验证目录结构一致（仅比较目录部分）
            input_dir = os.path.dirname(rel_input)
            output_dir = os.path.dirname(rel_output)

            assert (
                input_dir == output_dir
            ), f"目录结构不一致: {input_dir} != {output_dir}"

    def test_file_name_preservation(self):
        """测试文件名保持（仅扩展名改变）"""
        input_folder = "/input"
        output_folder = "/output"

        test_files = [
            "/input/video.mkv",
            "/input/my_video.avi",
            "/input/测试视频.flv",
            "/input/video_2024.mov",
        ]

        for filepath in test_files:
            new_filename, _ = resolve_output_paths(
                filepath, input_folder, output_folder, keep_structure=True
            )

            # 验证文件名（不包括扩展名）保持不变
            input_stem = Path(filepath).stem
            output_stem = Path(new_filename).stem

            assert (
                input_stem == output_stem
            ), f"文件名改变: {input_stem} != {output_stem}"
            assert new_filename.endswith(".mp4"), "输出文件应该是 .mp4 格式"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
