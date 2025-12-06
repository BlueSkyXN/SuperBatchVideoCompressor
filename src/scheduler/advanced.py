#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高级多编码器调度系统

设计：
1. 从配置中读取各编码器的 enabled 状态
2. 启用的硬件编码器并发处理不同文件
3. 失败任务智能回退：同编码器降级 → 其他编码器 → CPU兜底(可选)
4. 所有方法失败的任务跳过，继续处理队列中下一个
5. 预扫描任务列表，构建调度队列
"""

import threading
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Callable, Any, Set

from src.utils.process import is_shutdown_requested


class EncoderType(Enum):
    """编码器类型（按优先级排序）"""
    NVENC = "nvenc"
    VIDEOTOOLBOX = "videotoolbox"
    QSV = "qsv"
    CPU = "cpu"


# 编码器优先级顺序
ENCODER_PRIORITY = [EncoderType.NVENC, EncoderType.VIDEOTOOLBOX, EncoderType.QSV]


class DecodeMode(Enum):
    """解码模式"""
    HW_DECODE = "hw_decode"           # 硬件解码
    SW_DECODE_LIMITED = "sw_decode_limited"  # 软件解码+限帧
    SW_DECODE = "sw_decode"           # 软件解码


@dataclass
class TaskState:
    """任务状态"""
    filepath: str
    task_id: int
    current_encoder: Optional[EncoderType] = None
    current_decode_mode: DecodeMode = DecodeMode.HW_DECODE
    tried_combinations: Set[str] = field(default_factory=set)  # "encoder:decode_mode"
    errors: List[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 20  # 防止无限循环


@dataclass
class TaskResult:
    """任务结果"""
    success: bool
    filepath: str = ""
    encoder_used: Optional[EncoderType] = None
    decode_mode: Optional[DecodeMode] = None
    error: Optional[str] = None
    stats: Dict[str, Any] = field(default_factory=dict)
    retry_history: List[str] = field(default_factory=list)
    skipped: bool = False  # 是否因所有方法失败而跳过


class EncoderSlot:
    """编码器槽位管理"""
    
    def __init__(self, encoder_type: EncoderType, max_concurrent: int):
        self.encoder_type = encoder_type
        self.max_concurrent = max_concurrent
        self.semaphore = threading.Semaphore(max_concurrent)
        self.current_tasks = 0
        self.total_completed = 0
        self.total_failed = 0
        self._lock = threading.Lock()
    
    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        acquired = self.semaphore.acquire(blocking=blocking, timeout=timeout)
        if acquired:
            with self._lock:
                self.current_tasks += 1
        return acquired
    
    def release(self, success: bool = True):
        with self._lock:
            self.current_tasks -= 1
            if success:
                self.total_completed += 1
            else:
                self.total_failed += 1
        self.semaphore.release()
    
    def can_accept(self) -> bool:
        with self._lock:
            return self.current_tasks < self.max_concurrent
    
    def get_load(self) -> float:
        with self._lock:
            return self.current_tasks / self.max_concurrent if self.max_concurrent > 0 else 1.0
    
    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "encoder": self.encoder_type.value,
                "current": self.current_tasks,
                "max": self.max_concurrent,
                "completed": self.total_completed,
                "failed": self.total_failed,
            }


class AdvancedScheduler:
    """
    高级多编码器调度器
    
    特性：
    1. 从配置的 enabled 字段读取启用状态
    2. 多编码器并发处理
    3. 智能回退：同编码器降级 → 其他编码器 → CPU兜底
    4. 失败任务跳过，继续队列
    """
    
    def __init__(
        self,
        encoder_configs: Dict[str, Dict[str, Any]],
        max_total_concurrent: int = 5,
    ):
        self.max_total_concurrent = max_total_concurrent
        self.total_semaphore = threading.Semaphore(max_total_concurrent)
        
        self._lock = threading.Lock()
        self._shutdown = False
        self._task_counter = 0
        
        self.logger = logging.getLogger("Scheduler")
        
        # 初始化编码器槽位（根据 enabled 状态）
        self.encoder_slots: Dict[EncoderType, EncoderSlot] = {}
        self.enabled_hw_encoders: List[EncoderType] = []  # 启用的硬件编码器
        self.cpu_fallback_enabled = False
        
        # 按优先级顺序检查硬件编码器
        for encoder_type in ENCODER_PRIORITY:
            name = encoder_type.value
            if name in encoder_configs:
                config = encoder_configs[name]
                if config.get("enabled", False):
                    max_concurrent = config.get("max_concurrent", 2)
                    self.encoder_slots[encoder_type] = EncoderSlot(encoder_type, max_concurrent)
                    self.enabled_hw_encoders.append(encoder_type)
        
        # CPU 兜底
        cpu_config = encoder_configs.get("cpu", {})
        if cpu_config.get("enabled", False):
            self.cpu_fallback_enabled = True
            max_concurrent = cpu_config.get("max_concurrent", 4)
            self.encoder_slots[EncoderType.CPU] = EncoderSlot(EncoderType.CPU, max_concurrent)
        
        if not self.enabled_hw_encoders and not self.cpu_fallback_enabled:
            raise ValueError("至少需要启用一个编码器！请检查配置文件。")
        
        self.logger.info(
            f"调度器初始化: 硬件编码器={[e.value for e in self.enabled_hw_encoders]}, "
            f"CPU兜底={'启用' if self.cpu_fallback_enabled else '禁用'}, "
            f"总并发={max_total_concurrent}"
        )
    
    def _get_next_combination(self, task_state: TaskState) -> Optional[tuple]:
        """
        获取下一个编码器+解码模式组合
        
        回退顺序:
        1. 当前编码器的下一个解码模式（硬解 → 软解限帧 → 软解）
        2. 下一个硬件编码器（从硬解开始）
        3. CPU 兜底（如果启用）
        
        Returns: (EncoderType, DecodeMode) 或 None
        """
        decode_modes_hw = [DecodeMode.HW_DECODE, DecodeMode.SW_DECODE_LIMITED, DecodeMode.SW_DECODE]
        decode_modes_cpu = [DecodeMode.SW_DECODE_LIMITED, DecodeMode.SW_DECODE]
        
        # 尝试所有硬件编码器的所有解码模式
        for encoder_type in self.enabled_hw_encoders:
            for decode_mode in decode_modes_hw:
                combo = f"{encoder_type.value}:{decode_mode.value}"
                if combo not in task_state.tried_combinations:
                    return (encoder_type, decode_mode)
        
        # 尝试 CPU 兜底
        if self.cpu_fallback_enabled:
            for decode_mode in decode_modes_cpu:
                combo = f"cpu:{decode_mode.value}"
                if combo not in task_state.tried_combinations:
                    return (EncoderType.CPU, decode_mode)
        
        return None
    
    def schedule_task(
        self,
        filepath: str,
        encode_func: Callable[[str, EncoderType, DecodeMode], TaskResult],
        timeout: Optional[float] = None
    ) -> TaskResult:
        """
        调度单个任务
        
        Args:
            filepath: 文件路径
            encode_func: 编码函数 (filepath, encoder_type, decode_mode) -> TaskResult
            
        Returns:
            TaskResult（包含是否被跳过）
        """
        if self._shutdown:
            return TaskResult(success=False, filepath=filepath, error="调度器已关闭", skipped=True)
        
        # 获取总并发槽位
        acquired = self.total_semaphore.acquire(blocking=True, timeout=timeout)
        if not acquired:
            return TaskResult(success=False, filepath=filepath, error="获取并发槽位超时", skipped=True)
        
        try:
            with self._lock:
                self._task_counter += 1
                task_id = self._task_counter
            
            task_state = TaskState(filepath=filepath, task_id=task_id)
            retry_history = []
            
            while task_state.retry_count < task_state.max_retries:
                # 检查是否收到关闭信号
                if self._shutdown or is_shutdown_requested():
                    return TaskResult(
                        success=False,
                        filepath=filepath,
                        error="收到关闭信号",
                        retry_history=retry_history,
                        skipped=True
                    )
                
                # 获取下一个组合
                combination = self._get_next_combination(task_state)
                
                if combination is None:
                    # 所有方法都尝试过了，跳过此任务
                    error_summary = "; ".join(task_state.errors[-3:]) if task_state.errors else "未知错误"
                    self.logger.warning(f"[跳过] 任务 {task_id}: 所有编码方法均失败 - {filepath}")
                    return TaskResult(
                        success=False,
                        filepath=filepath,
                        error=f"所有编码方法均失败: {error_summary}",
                        retry_history=retry_history,
                        skipped=True
                    )
                
                encoder_type, decode_mode = combination
                combo_str = f"{encoder_type.value}:{decode_mode.value}"
                task_state.tried_combinations.add(combo_str)
                
                # 获取编码器槽位
                slot = self.encoder_slots.get(encoder_type)
                if not slot:
                    task_state.retry_count += 1
                    continue
                
                # 等待槽位（带超时）
                if not slot.acquire(blocking=True, timeout=10):
                    task_state.errors.append(f"{combo_str}: 获取槽位超时")
                    task_state.retry_count += 1
                    continue
                
                retry_history.append(combo_str)
                self.logger.info(f"[任务 {task_id}] 尝试 {combo_str}")
                
                try:
                    # 再次检查关闭信号
                    if self._shutdown or is_shutdown_requested():
                        slot.release(success=False)
                        return TaskResult(
                            success=False,
                            filepath=filepath,
                            error="收到关闭信号",
                            retry_history=retry_history,
                            skipped=True
                        )
                    
                    result = encode_func(filepath, encoder_type, decode_mode)
                    
                    if result.success:
                        slot.release(success=True)
                        result.retry_history = retry_history
                        result.encoder_used = encoder_type
                        result.decode_mode = decode_mode
                        return result
                    else:
                        slot.release(success=False)
                        
                        # 如果是因为收到信号导致的失败，不继续重试
                        if is_shutdown_requested():
                            return TaskResult(
                                success=False,
                                filepath=filepath,
                                error="收到关闭信号",
                                retry_history=retry_history,
                                skipped=True
                            )
                        
                        error_msg = result.error or "未知错误"
                        task_state.errors.append(f"{combo_str}: {error_msg}")
                        self.logger.warning(f"[任务 {task_id}] {combo_str} 失败: {error_msg}")
                        task_state.retry_count += 1
                        
                except Exception as e:
                    slot.release(success=False)
                    
                    # 如果是键盘中断，直接返回
                    if isinstance(e, KeyboardInterrupt) or is_shutdown_requested():
                        return TaskResult(
                            success=False,
                            filepath=filepath,
                            error="收到关闭信号",
                            retry_history=retry_history,
                            skipped=True
                        )
                    
                    task_state.errors.append(f"{combo_str}: {str(e)}")
                    self.logger.error(f"[任务 {task_id}] 异常: {e}")
                    task_state.retry_count += 1
            
            # 超过最大重试次数
            return TaskResult(
                success=False,
                filepath=filepath,
                error="超过最大重试次数",
                retry_history=retry_history,
                skipped=True
            )
            
        finally:
            self.total_semaphore.release()
    
    def shutdown(self):
        """关闭调度器"""
        self._shutdown = True
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "max_total_concurrent": self.max_total_concurrent,
            "enabled_hw_encoders": [e.value for e in self.enabled_hw_encoders],
            "cpu_fallback": self.cpu_fallback_enabled,
            "encoder_slots": {
                encoder_type.value: slot.get_stats()
                for encoder_type, slot in self.encoder_slots.items()
            }
        }


def create_advanced_scheduler(config: Dict[str, Any]) -> AdvancedScheduler:
    """从配置创建高级调度器"""
    encoders_config = config.get("encoders", {})
    scheduler_config = config.get("scheduler", {})
    
    # 直接读取各编码器的配置（enabled 在各自配置中）
    encoder_configs = {}
    for name in ["nvenc", "qsv", "videotoolbox", "cpu"]:
        cfg = encoders_config.get(name, {})
        encoder_configs[name] = {
            "enabled": cfg.get("enabled", False),
            "max_concurrent": cfg.get("max_concurrent", 2),
        }
    
    return AdvancedScheduler(
        encoder_configs=encoder_configs,
        max_total_concurrent=scheduler_config.get("max_total_concurrent", 5),
    )
