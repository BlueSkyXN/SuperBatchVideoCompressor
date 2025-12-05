# SBVC - Super Batch Video Compressor

**超级批量视频压缩器** - 一款功能强大的批量视频压缩工具，支持多平台硬件加速和智能编码策略。

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

## ✨ 功能特性

- 🚀 **多平台硬件加速**
  - NVIDIA GPU (CUDA + NVENC)
  - Apple VideoToolbox (Mac)
  - Intel Quick Sync Video (QSV)

- 🎬 **多格式输出**
  - HEVC/H.265 (推荐，压缩率高)
  - AVC/H.264 (兼容性最好)
  - AV1 (最新，压缩率最高)

- 🔧 **智能编码策略**
  - 自动检测硬件加速能力
  - 智能降级机制 (GPU → CPU 自动回退)
  - 基于分辨率的智能码率计算
  - 可配置的帧率限制

- 📁 **批量处理能力**
  - 支持 18 种视频格式
  - 多线程并发处理
  - 保持原始目录结构
  - 详细的日志记录与进度显示

## 📋 支持的视频格式

| 格式 | 扩展名 |
|------|--------|
| 常见格式 | `.mp4`, `.mkv`, `.avi`, `.mov`, `.wmv` |
| 流媒体 | `.ts`, `.m2ts`, `.mpeg`, `.mpg`, `.flv` |
| 其他格式 | `.rm`, `.rmvb`, `.3gp`, `.webm`, `.m4v`, `.vob`, `.ogv`, `.f4v` |

## 🛠️ 安装要求

### 必需依赖

- **Python 3.6+**
- **FFmpeg** (包含 ffprobe)

### FFmpeg 安装

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows (使用 Chocolatey)
choco install ffmpeg

# Windows (使用 Scoop)
scoop install ffmpeg
```

### 硬件加速支持

| 平台 | 加速器 | 要求 |
|------|--------|------|
| Windows/Linux | NVENC | NVIDIA GPU + 驱动 |
| macOS | VideoToolbox | 内置支持 |
| Windows/Linux | QSV | Intel 集成显卡 |

## 🚀 快速开始

### 基本用法

```bash
# 基本压缩
python SBVC.py -i /path/to/input -o /path/to/output

# 查看帮助
python SBVC.py --help
```

### 使用示例

```bash
# 使用 Mac VideoToolbox 硬件加速
python SBVC.py -i ./input -o ./output --hw-accel videotoolbox

# 使用 NVIDIA 硬件加速
python SBVC.py -i ./input -o ./output --hw-accel nvenc

# 使用 Intel QSV 硬件加速
python SBVC.py -i ./input -o ./output --hw-accel qsv

# 输出 H.264/AVC 编码（兼容性最好）
python SBVC.py -i ./input -o ./output --codec avc

# 输出 AV1 编码（压缩率最高）
python SBVC.py -i ./input -o ./output --codec av1

# 启用 CPU 编码回退
python SBVC.py -i ./input -o ./output --cpu-fallback

# 自定义帧率限制
python SBVC.py -i ./input -o ./output --max-fps 24

# 设置并发线程数
python SBVC.py -i ./input -o ./output -w 4
```

## 📖 命令行参数

### 基本参数

| 参数 | 简写 | 说明 | 默认值 |
|------|------|------|--------|
| `--input` | `-i` | 输入文件夹路径 | `F:\lada\output` |
| `--output` | `-o` | 输出文件夹路径 | `F:\lada\pre` |
| `--log` | `-l` | 日志文件夹路径 | `I:\BVC` |

### 编码格式选项

| 参数 | 说明 | 可选值 | 默认值 |
|------|------|--------|--------|
| `--hw-accel` | 硬件加速类型 | `auto`, `nvenc`, `videotoolbox`, `qsv`, `none` | `auto` |
| `--codec` | 输出视频编码格式 | `hevc`, `avc`, `av1` | `hevc` |

### 处理选项

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--min-size` | 最小文件大小阈值 (MB) | `100` |
| `--force-bitrate` | 强制码率 (bps)，0 表示自动 | `0` |
| `--no-keep-structure` | 不保持原始目录结构 | - |
| `--workers` / `-w` | 并发处理线程数 | `3` |

### 编码回退选项

| 参数 | 说明 |
|------|------|
| `--enable-software-fallback` | 启用软件编码回退 |
| `--cpu-fallback` | 启用 CPU 编码回退 (同上) |

### 帧率限制选项

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--max-fps` | 最大帧率限制 | `30` |
| `--no-fps-limit` | 禁用所有帧率限制 | - |
| `--no-fps-limit-decode` | 软件解码时不限制帧率 | - |
| `--no-fps-limit-encode` | 软件编码时不限制帧率 | - |

## 🔄 编码策略

SBVC 采用智能的多级编码策略，自动选择最优方案：

```
┌─────────────────────────────────────────────────────────────┐
│                      编码优先级                              │
├─────────────────────────────────────────────────────────────┤
│  1. 硬件全加速模式  │ 硬件解码 + 硬件编码     │ 最快速度    │
├─────────────────────────────────────────────────────────────┤
│  2. 混合模式        │ 软件解码 + 硬件编码     │ 高速度      │
├─────────────────────────────────────────────────────────────┤
│  3. 纯软件模式      │ 软件解码 + 软件编码     │ 最大兼容    │
└─────────────────────────────────────────────────────────────┘
```

> **注意**: 纯软件模式默认禁用，需通过 `--cpu-fallback` 启用

## 📊 智能码率计算

根据视频分辨率自动确定目标码率上限：

| 分辨率 | 最大码率 |
|--------|----------|
| ≤720p | 1.5 Mbps |
| ≤1080p | 3 Mbps |
| ≤1440p | 5 Mbps |
| >1440p | 9 Mbps |

实际码率 = min(原始码率 × 0.5, 最大码率)

## 📝 日志输出

程序运行时会生成详细的日志文件，包含：

- 处理进度和状态
- 各文件的压缩详情（原始/目标码率、文件大小、压缩率）
- 使用的编码方法
- 错误和警告信息
- 最终统计摘要

日志文件命名格式：`transcoding_YYYYMMDDHHMMSS.log`

## 🏷️ 输出示例

```
============================================================
SBVC - 超级批量视频压缩器
============================================================
输入目录: /Users/videos/input
输出目录: /Users/videos/output
硬件加速: Apple VideoToolbox
输出编码: HEVC/H.265
------------------------------------------------------------
[尝试] 方法 1/3 (Apple VideoToolbox 全加速): video1.mp4
[成功] 使用 Apple VideoToolbox 全加速 (HEVC/H.265) 完成压缩
[完成] video1.mp4 | 码率: 8000k -> 3000k | 大小: 500.0MB -> 187.5MB | 压缩率: 62.5%
[进度] 1/10 (10.0%)
------------------------------------------------------------
============================================================
任务完成统计
============================================================
总文件数: 10
成功压缩: 8
跳过(文件过小): 1
跳过(已存在): 1
失败: 0
------------------------------------------------------------
原始总大小: 4.00 GB
压缩后大小: 1.50 GB
节省空间: 2.50 GB (62.5%)
============================================================
```

## ⚙️ 内置配置

可直接在脚本中修改默认配置：

```python
# 路径配置
DEFAULT_INPUT_FOLDER = r"F:\lada\output"
DEFAULT_OUTPUT_FOLDER = r"F:\lada\pre"
DEFAULT_LOG_FOLDER = r"I:\BVC"

# 码率设置
MIN_BITRATE = 500000      # 最小码率 500kbps
BITRATE_RATIO = 0.5       # 压缩比例

# 音频质量
AUDIO_BITRATE = "128k"

# 并发设置
MAX_WORKERS = 3
```

## 📄 许可证

本项目采用 [GNU General Public License v3.0](LICENSE) 许可证。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📮 联系方式

如有问题或建议，请在 [GitHub Issues](https://github.com/BlueSkyXN/SuperBatchVideoCompressor/issues) 中提出。
