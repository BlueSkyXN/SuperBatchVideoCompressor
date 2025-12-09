# SBVC 设计说明

## 目录与职责

```
.
├── main.py                # 薄入口，调用 CLI 主函数
├── cli.py                 # 命令行解析，调用 bootstrap+service
├── config-example.yaml    # 示例配置，便于拷贝为 config.yaml
├── requirements.txt       # 依赖 (pyyaml)
├── tests/                 # Pytest 用例
├── src/
│   ├── __init__.py        # 包元数据
│   ├── bootstrap.py       # 启动准备（编码、清理、日志、信号、探测）
│   ├── config/            # 配置加载
│   │   ├── defaults.py    # 默认值、编码器映射、常量
│   │   ├── loader.py      # YAML 加载与 CLI 覆盖
│   │   └── __init__.py
│   ├── service.py         # 服务层（CLI/未来 GUI/API 复用的执行入口）
│   ├── core/              # 核心编码逻辑
│   │   ├── video.py       # ffprobe 获取视频信息
│   │   ├── encoder.py     # 码率计算、编码命令构建、FFmpeg 执行
│   │   ├── compressor.py  # 文件枚举、输出路径处理
│   │   └── __init__.py
│   ├── scheduler/         # 多编码器调度
│   │   ├── advanced.py    # AdvancedScheduler 智能调度器
│   │   └── __init__.py
│   └── utils/             # 工具函数
│       ├── __init__.py
│       ├── files.py       # 视频文件枚举、硬件检测
│       ├── logging.py     # 日志配置
│       ├── process.py     # FFmpeg 进程管理、信号处理、临时文件清理
│       └── encoder_check.py  # 编码器可用性检测
└── LICENSE                # MIT 许可证
```

## 调度系统 (AdvancedScheduler)

### 设计目标
1. **多编码器真正并发**：NVENC 和 QSV 同时处理不同文件
2. **智能回退机制**：失败任务按规则降级重试
3. **自动硬件检测**：启动时检测可用编码器

### 调度流程
```
┌─────────────────────────────────────────────────────────────┐
│                        任务入口                              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  第一层：硬解+硬编（分配到有空闲槽位的编码器）               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ NVENC (3槽) │  │ QSV (2槽)   │  │ VT (macOS)  │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
          ↓ 失败                ↓ 失败
┌─────────────────────────────────────────────────────────────┐
│  第二层：软解+硬编（在当前编码器降级重试）                   │
│  - 限帧率版本（减轻负担）                                   │
│  - 不限帧率版本                                             │
└─────────────────────────────────────────────────────────────┘
          ↓ 仍然失败
┌─────────────────────────────────────────────────────────────┐
│  第三层：移交其他硬件编码器                                  │
│  NVENC失败 → 移交QSV                                        │
│  QSV失败 → 移交NVENC                                        │
└─────────────────────────────────────────────────────────────┘
          ↓ 所有硬件编码器失败
┌─────────────────────────────────────────────────────────────┐
│  第四层：CPU 软编码兜底（可开关）                            │
└─────────────────────────────────────────────────────────────┘
          ↓ 全部失败
┌─────────────────────────────────────────────────────────────┐
│  跳过该任务，继续处理队列中的下一个文件                      │
└─────────────────────────────────────────────────────────────┘
```

### 核心类
- `AdvancedScheduler`: 主调度器，管理任务分配和回退
- `EncoderSlot`: 单个编码器的槽位管理（信号量控制并发）
- `TaskState`: 跟踪任务状态和重试历史
- `DecodeMode`: 解码模式枚举（HW_DECODE, SW_DECODE_LIMITED, SW_DECODE）
- `TaskResult`: 任务结果，包含成功状态、使用的编码器、重试历史等

### 编码器优先级
按以下顺序尝试编码器：
1. **NVENC** (NVIDIA GPU)
2. **VideoToolbox** (Apple 芯片，仅 macOS)
3. **QSV** (Intel 集显)
4. **CPU** (软编码兜底)

## 架构分层

```
┌─────────────────────────────────────────────────────────┐
│  入口层 (main.py, cli.py)                                │
│  - pycache 清理（main.py，必须在导入前）                 │
│  - 参数解析与配置加载（cli.py）                          │
│  - 所有 CLI 参数通过 apply_cli_overrides() 转换到 config │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  启动层 (src/bootstrap.py)                               │
│  - 编码设置 (enforce_utf8_windows)                       │
│  - 信号处理器注册                                        │
│  - 日志初始化                                            │
│  - 临时文件清理                                          │
│  - 编码器可用性检测                                      │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  服务层 (src/service.py)                                 │
│  - run_batch(config) - 纯配置驱动，无 CLI 依赖           │
│  - 文件枚举与预检查                                      │
│  - 调度器创建与任务分配                                  │
│  - 统计汇总与结果输出                                    │
│  - 可被 CLI/GUI/API 复用                                 │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  核心层 (src/core, src/scheduler, src/utils)            │
│  - 配置管理 (config/)                                    │
│  - 编码器调度 (scheduler/advanced.py)                    │
│  - 视频处理 (core/video.py, encoder.py)                 │
│  - 工具函数 (utils/)                                     │
└─────────────────────────────────────────────────────────┘
```

**设计原则**：
- ✅ **配置驱动**：所有参数统一通过 config 字典传递
- ✅ **分层清晰**：每层职责单一，上层依赖下层
- ✅ **可复用性**：service 层可被多种前端（CLI/GUI/API）复用
- ✅ **可测试性**：各层独立，易于单元测试

## 运行流程

1. `main.py` 清理 pycache → 调用 `cli.main()`
2. `cli.py` 解析命令行参数并加载配置
3. `apply_cli_overrides(config, args)` 将所有 CLI 参数转换到 config 字典
4. `bootstrap.prepare_environment(config)`：编码设置、临时文件清理、日志初始化、信号处理、编码器检测
5. `service.run_batch(config)`：创建 `AdvancedScheduler` 进行智能调度
6. 使用线程池并发处理文件
7. Ctrl+C 时通过 `terminate_all_ffmpeg()` 优雅终止

## 配置设计

### 编码器配置
```yaml
encoders:
  nvenc:
    enabled: true          # 想用就设 true，启动时自动检测
    max_concurrent: 3
  qsv:
    enabled: true
    max_concurrent: 2
  videotoolbox:
    enabled: false         # macOS 用户设 true
    max_concurrent: 3
  cpu:
    enabled: true          # CPU 兜底
    max_concurrent: 4
    preset: medium

scheduler:
  max_total_concurrent: 5  # 总并发 = 3 + 2
```

### 日志/控制台配置

```yaml
logging:
  level: INFO          # DEBUG/INFO/WARNING/ERROR
  plain: false         # 控制台禁用彩色/装饰
  json_console: false  # 控制台输出 JSON 行，便于采集/CI
  show_progress: true  # 是否显示进度行
  print_cmd: false     # 总是打印完整 FFmpeg 命令
```

命令行对应开关：`-v/--verbose`、`-q/--quiet`、`--plain`、`--json-logs`、`--no-progress`、`--print-cmd`。

### 配置加载优先级
1. 命令行参数
2. 配置文件 (config.yaml)
3. 程序默认值 (src/config/defaults.py)

## 核心模块

### encoder.py
- `calculate_target_bitrate()`: 按原码率与分辨率计算目标码率
- `build_hw_encode_command()`: 构建硬件编码命令
- `build_sw_encode_command()`: 构建软件编码命令
- `execute_ffmpeg()`: 执行命令并处理错误

#### 硬件解码白名单机制
`SUPPORTED_HW_DECODE_CODECS` 是一个按编码器分类的字典，定义了每个硬件加速器支持的硬件解码格式：

```python
SUPPORTED_HW_DECODE_CODECS = {
    "nvenc": ["h264", "hevc", "av1", "vp9", "vp8", "mpeg2video", "mpeg4"],
    "qsv": ["h264", "hevc", "av1", "vp9", "vp8", "mpeg2video", "vc1", "wmv3", "mjpeg"],
    "videotoolbox": ["h264", "hevc", "mpeg2video", "mpeg4", "mjpeg", "prores"],
}
```

**工作原理**：

1. **动态判断**：根据当前使用的编码器（nvenc/qsv/videotoolbox）查询其支持的硬解格式
2. **智能尝试**：如果源编码在白名单中，构建硬解命令并尝试执行
3. **自动回退**：如果硬解失败（FFmpeg 报错），调度器自动切换到软解+硬编模式
4. **性能优化**：避免对不支持的格式进行无效的硬解尝试

**关键差异**：

- **NVENC**：不支持 VC1/WMV，WMV 文件会直接使用软解
- **QSV**：支持 VC1/WMV 硬解，WMV 文件可以充分利用硬件加速
- **VideoToolbox**：支持 ProRes，但不支持 VP9/AV1

**调试方法**：

- 设置 `logging.level: DEBUG` 或 `--verbose` 查看硬解决策日志
- 使用 `--print-cmd` 查看实际执行的 FFmpeg 命令

### encoder_check.py
- `detect_available_encoders()`: 检测所有启用的编码器，返回实际可用的配置
- `check_encoder_available()`: 检测单个编码器是否可用
- `check_nvenc_available()`: 检测 NVENC
- `check_qsv_available()`: 检测 QSV
- `check_videotoolbox_available()`: 检测 VideoToolbox
- `check_cpu_available()`: 检测 CPU 软编码
- `print_encoder_status()`: 打印编码器状态摘要

### process.py
- `register_process()` / `unregister_process()`: 跟踪 FFmpeg 进程
- `is_shutdown_requested()`: 检查是否请求了关闭
- `terminate_all_ffmpeg()`: 优雅终止所有进程
- `cleanup_temp_files()`: 清理临时文件
- `cleanup_pycache()`: 清理 Python 缓存
- `setup_signal_handlers()`: 设置信号处理器

## 输入/输出

- **输入**: 指定目录内所有视频文件
- **输出**: 统一 `.mp4`，保持目录结构
- **临时文件**: `tmp_*.mp4`，启动时自动清理
- **日志**: 同时输出到文件和控制台

## 依赖

- `ffmpeg` / `ffprobe`: 必需
- `pyyaml`: 可选（读取配置文件）
- 硬件编码需要对应驱动
