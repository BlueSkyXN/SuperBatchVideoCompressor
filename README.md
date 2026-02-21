# Super Batch Video Compressor (SBVC)

SBVC 是一个基于 FFmpeg 的批量视频压缩命令行工具，支持 NVENC / Intel QSV / VideoToolbox 等硬件加速，并内置**智能多编码器调度**与进程管理，适合大批量转码场景。

## 主要特性

- **自动检测硬件**：启动时自动检测可用编码器，不可用的自动禁用
- **多编码器真正并发**：NVENC 和 QSV 同时处理不同文件（如 3+2=5 并发）
- **智能回退调度**：
  - 同编码器内：硬解+硬编 → 软解+硬编(限帧) → 软解+硬编
  - 跨编码器：NVENC 失败 → QSV，QSV 失败 → NVENC
  - 最终兜底：CPU 软编码（可开关）
  - 解码损坏容错：检测到坏流错误时自动追加忽错参数重试（可配置）
  - 所有方法失败的任务跳过，继续处理队列
- **进程管理**：Ctrl+C 自动终止所有 FFmpeg 进程，启动时清理临时文件
- 自动按分辨率计算目标码率
- 可保持输入目录结构输出
- **音频处理简化**：支持 copy/转码/关闭；`transcode` 下源码率<=目标则优先 copy；`auto` copy 失败回退转码
- 日志/控制台可配置：支持彩色或纯文本、JSON 行输出、静默/进度开关、打印完整 FFmpeg 命令

## 硬件编码器

| 编码器 | 平台 | 硬件 | 说明 |
|--------|------|------|------|
| nvenc | Windows/Linux | NVIDIA GPU | 最快，需要 N 卡 + 驱动 |
| videotoolbox | macOS | Apple 芯片 | 仅 macOS 可用 |
| qsv | Windows/Linux | Intel 集显 | 需要 Intel CPU 集成显卡 |
| cpu | 全平台 | CPU | 软编码兜底，最慢但兼容性最好 |

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 复制并修改配置文件
cp config-example.yaml config.yaml
# 编辑 config.yaml 设置输入/输出路径

# 运行
python main.py

# 预览任务（不实际执行）
python main.py --dry-run
```

## 配置文件

复制 `config-example.yaml` 为 `config.yaml` 并根据需要修改。

### 主要配置项

- **编码器配置**：`encoders` - 设置各编码器的启用状态和并发数
  - `enabled: true` 表示"想用"，启动时自动检测是否真正可用
  - NVENC / QSV / VideoToolbox / CPU 可选

- **编码参数**：`encoding` - 输出视频/音频策略
  - `codec`: hevc/avc/av1
  - `bitrate`: 支持强制码率、压缩比例、分辨率自适应封顶
  - `audio_bitrate`: 默认音频目标码率（需要转码时生效）
  - `audio`: 简化音频模式（off/copy/transcode/auto）与转码参数

  默认行为：字幕丢弃（`-sn`）；音频目标为 AAC@`audio_bitrate`，但若探测到源音频码率 <= 目标码率，则优先 `copy`（copy 失败会回退转码）。

- **帧率限制**：`fps` - 最大帧率、软解/软编时是否限帧

- **解码错误容错**：`error_recovery` - 当源文件局部损坏时，自动启用
  `-fflags +discardcorrupt -err_detect ignore_err` 做同方法重试

- **文件处理**：`files` - 最小文件大小、目录结构保持、跳过已存在文件

- **日志配置**：`logging` - 日志级别、输出格式、进度显示

### 配置优先级

命令行参数 > 配置文件 > 程序默认值

详细配置说明请查看 [config-example.yaml](config-example.yaml)

## 调度策略

```text
┌─────────────────────────────────────────────────────────────┐
│                        任务入口                              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  启用的硬件编码器并发处理（负载均衡分配）                    │
│  ┌─────────────┐  ┌─────────────┐                          │
│  │ NVENC (3槽) │  │ QSV (2槽)   │                          │
│  │ 文件1,2,3   │  │ 文件4,5     │                          │
│  └─────────────┘  └─────────────┘                          │
└─────────────────────────────────────────────────────────────┘
          ↓ 失败
┌─────────────────────────────────────────────────────────────┐
│  同编码器降级重试                                           │
│  硬解+硬编 → 软解+硬编(限帧) → 软解+硬编                    │
└─────────────────────────────────────────────────────────────┘
          ↓ 仍然失败
┌─────────────────────────────────────────────────────────────┐
│  移交其他硬件编码器                                         │
│  NVENC失败 → QSV, QSV失败 → NVENC                          │
└─────────────────────────────────────────────────────────────┘
          ↓ 所有硬件都失败
┌─────────────────────────────────────────────────────────────┐
│  CPU 软编码兜底（如果启用）                                  │
│  如果也失败 → 跳过此任务，继续队列                          │
└─────────────────────────────────────────────────────────────┘
```

## 目录结构保持

默认情况下，程序会保持输入目录的结构：

```text
输入目录:                  输出目录:
L:/input/                 J:/Output3/
├── video1.mkv           ├── video1.mp4
├── Season 01/           ├── Season 01/
│   ├── ep01.mkv        │   ├── ep01.mp4
│   └── ep02.mkv        │   └── ep02.mp4
└── Movies/              └── Movies/
    └── 2024/                └── 2024/
        └── film.mkv            └── film.mp4
```

**配置方式：**

1. **配置文件**（推荐）：

   ```yaml
   files:
     keep_structure: true   # 保持目录结构
     # keep_structure: false  # 扁平化输出（所有文件输出到同一目录）
   ```

2. **命令行参数**：

   ```bash
   # 不保持目录结构（所有文件输出到同一目录）
   python main.py --no-keep-structure
   ```

**提示：** 运行时会显示路径映射示例，可以确认输出结构是否符合预期。

## 命令行参数

```text
python main.py [选项]

基本选项:
  -i, --input PATH          输入文件夹路径
  -o, --output PATH         输出文件夹路径
  -l, --log PATH            日志文件夹路径
  -c, --codec CODEC         输出编码 (hevc/avc/av1)
  --config PATH             配置文件路径

编码选项:
  --max-concurrent N        总并发数
  --force-bitrate BPS       强制使用指定码率（单位：bps），0表示自动计算
  --max-fps N               最大帧率限制（默认30）
  --no-fps-limit            禁用所有帧率限制

文件处理:
  --min-size MB             最小文件大小阈值（MB），默认100
  --no-keep-structure       不保持原始目录结构（扁平化输出）
  --dry-run                 预览模式，不实际执行

日志和输出:
  -v, --verbose             增加日志详细度（可重复）
  -q, --quiet               减少控制台输出（可重复）
  --plain                   禁用彩色输出/装饰
  --no-progress             关闭进度输出（仍保留摘要）
  --json-logs               控制台输出 JSON 行，便于采集/CI
  --print-cmd               总是输出完整 FFmpeg 命令
```

## 日志与控制台输出

- **默认**：彩色控制台 + 详细文件日志（`logs/transcoding_*.log`），INFO 级别
- **`--plain`**：强制无色，适合重定向或不支持 ANSI 的终端（Windows 在未安装 colorama 时自动降级）
- **`--json-logs`**：控制台输出 JSON 行，便于 CI/采集；文件日志保持文本格式
- **`--no-progress`**：关闭进度行，仅输出关键事件和最终统计
- **`--print-cmd` 或 `--verbose`**：打印完整 FFmpeg 命令；否则仅 DEBUG 级别写入

### 日志级别

- **DEBUG**：硬解决策、完整 FFmpeg 命令、详细执行过程
- **INFO**：任务开始/完成、编码器检测、统计信息（默认）
- **WARNING**：编码器不可用、任务跳过
- **ERROR**：FFmpeg 执行失败、严重错误

## 环境要求

- Python 3.8+
- FFmpeg（需在 PATH 中）
- pyyaml（`pip install pyyaml`）
- （可选）colorama，用于在 Windows 控制台启用 ANSI 彩色输出
- 硬件驱动：NVIDIA / Intel

## 测试

### 运行所有测试

```bash
pytest
```

### 运行特定测试

```bash
# 测试目录保持功能
pytest tests/test_keep_structure.py -v

# 测试编码器功能
pytest tests/test_encoder.py -v

# 生成覆盖率报告
pytest --cov=src --cov-report=html
```

### 持续集成

项目使用 GitHub Actions 进行自动化测试，包括：

- ✅ 多平台测试（Ubuntu、Windows、macOS）
- ✅ 多 Python 版本测试（3.8-3.14）
- ✅ 代码质量检查
- ✅ 目录保持功能专项测试
- ✅ CLI 功能测试

每次提交都会自动运行所有测试，确保功能稳定可靠。

## 调试指南

### 启用详细日志

#### 方法1：配置文件

```yaml
logging:
  level: DEBUG           # 启用详细日志
  print_cmd: true        # 打印完整 FFmpeg 命令
```

#### 方法2：命令行

```bash
python main.py --verbose --print-cmd
```

### 验证硬件加速是否生效

#### 1. 查看编码器检测日志

```text
检测编码器可用性...
✓ NVENC 可用
✓ QSV 可用
✓ CPU 可用
```

#### 2. 查看 FFmpeg 命令（启用 `--print-cmd`）

**硬解命令**（包含 `-hwaccel`）：

```bash
ffmpeg -y -hide_banner -hwaccel qsv -hwaccel_output_format qsv -i input.mkv -c:v hevc_qsv ...
```

**软解命令**（不包含 `-hwaccel`）：

```bash
ffmpeg -y -hide_banner -i input.mkv -c:v hevc_qsv ...
```

#### 3. 手动测试硬件支持

```bash
# 查看 QSV 支持的解码器
ffmpeg -decoders | grep qsv

# 查看 NVENC 支持的编码器
ffmpeg -encoders | grep nvenc

# 测试 NVENC 初始化
ffmpeg -f lavfi -i testsrc=duration=1:size=1280x720:rate=1 -c:v h264_nvenc -f null -
```

## 故障排除

### 问题1：编码器检测失败

**症状**：

```text
✗ NVENC 不可用: 未找到 NVIDIA GPU
```

**解决方案**：

- 检查硬件驱动是否安装（NVIDIA 驱动、Intel 显卡驱动）
- 确认 FFmpeg 编译时包含对应编码器支持：`ffmpeg -encoders | grep nvenc`
- Windows: 确保最新版本的 NVIDIA 驱动

### 问题2：所有任务都失败

**可能原因**：

1. FFmpeg 不在 PATH 中
2. 输入文件损坏或格式不支持
3. 输出目录权限不足

**诊断步骤**：

```bash
# 检查 FFmpeg 是否可用
ffmpeg -version

# 启用详细日志
python main.py --verbose --print-cmd

# 尝试单个文件
ffmpeg -i input.mkv -c:v hevc output.mp4
```

**补充说明（损坏源流）**：

- 如果日志包含 `Invalid data found when processing input`、`Error splitting the input into NAL units`，通常是源文件局部损坏。
- SBVC 默认会在该编码方法内自动进行一次“忽错容错重试”。
- 你可在 `config.yaml` 调整：

```yaml
error_recovery:
  retry_decode_errors_with_ignore: true
  max_ignore_retries_per_method: 1
```

### 问题3：WMV 文件处理很慢

**原因**：NVENC 不支持 WMV 硬解，需要使用 QSV

**解决方案**：

1. 确保 QSV 已启用并检测成功
2. 查看日志确认使用了正确的编码器：

```text
[INFO] [ENC] qsv/hw_decode: file.wmv -> Intel QSV (HEVC, 硬解+硬编)
```

### 问题4：码率没有按预期设置

**检查清单**：

1. 确认修改的是 `config.yaml` 而不是 `config-example.yaml`
2. 检查是否使用了 `--force-bitrate` 命令行参数（会覆盖配置）
3. 检查配置文件的 `bitrate.forced` 是否为 0
4. 启用 DEBUG 日志查看码率计算过程

## 详细文档

更多技术细节请参考：

- **[架构设计](docs/DESIGN.md)** - 完整的架构设计、目录结构、调度流程
- **[码率配置](docs/BITRATE_CONFIG.md)** - 码率计算详解、配置示例、故障排除
- **[硬解白名单](docs/HARDWARE_DECODE_WHITELIST.md)** - 硬件解码机制、编码器对比、性能影响

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件。
