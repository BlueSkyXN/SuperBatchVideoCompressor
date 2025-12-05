# SBVC 设计说明

## 目录与职责

```
.
├── main.py                # 入口脚本，调用 CLI 主函数
├── cli.py                 # 命令行解析、运行流程、任务调度
├── config-example.yaml    # 示例配置，便于拷贝为 config.yaml
├── requirements.txt       # 依赖 (pyyaml)
├── tests/                 # Pytest 用例
├── src/
│   ├── __init__.py        # 包元数据
│   ├── config/            # 配置加载
│   │   ├── defaults.py    # 默认值、编码器映射、常量
│   │   ├── loader.py      # YAML 加载与 CLI 覆盖
│   │   └── __init__.py
│   ├── core/              # 核心编码逻辑
│   │   ├── video.py       # ffprobe 获取视频信息
│   │   ├── encoder.py     # 码率计算、编码命令构建、FFmpeg 执行
│   │   ├── compressor.py  # 文件枚举、输出路径处理
│   │   └── __init__.py
│   ├── scheduler/         # 多编码器调度
│   │   ├── advanced.py    # AdvancedScheduler 智能调度器
│   │   └── __init__.py
│   └── utils/             # 工具函数
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

## 运行流程

1. `main.py` 调用 `cli.main()`
2. `cli.py` 解析命令行参数并加载配置
3. 设置信号处理器（捕获 Ctrl+C）
4. 启动时清理输出目录中的临时文件
5. **检测编码器可用性**：
   - 检查 NVENC/QSV/VideoToolbox/CPU
   - 自动禁用不可用的编码器
6. 创建 `AdvancedScheduler` 进行智能调度
7. 使用线程池并发处理文件
8. Ctrl+C 时通过 `terminate_all_ffmpeg()` 优雅终止

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
    preset: medium

scheduler:
  max_total_concurrent: 5  # 总并发 = 3 + 2
```

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

### encoder_check.py
- `detect_available_encoders()`: 检测所有编码器可用性
- `check_nvenc_available()`: 检测 NVENC
- `check_qsv_available()`: 检测 QSV
- `check_videotoolbox_available()`: 检测 VideoToolbox

### process.py
- `register_process()` / `unregister_process()`: 跟踪 FFmpeg 进程
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
