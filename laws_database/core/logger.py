# -*- coding: utf-8 -*-
"""
统一日志器
==========

三个数据源原本各自实现了几乎相同的 ``log()`` 方法
（时间戳 + 控制台输出 + 追加写日志文件）。本模块抽取为通用的 :class:`Logger`，
按 ``<name>_log_<时间戳>.txt`` 命名日志文件。

设计要点：
- 日志目录在构造时即创建，确保上下文（如案件类型）未定时也能立即记录；
- 同时输出到控制台与文件，便于实时观察与事后排查；
- 纯 I/O 封装，不耦合任何业务概念；
- 文件写入失败时降级为仅控制台提示，绝不中断主流程。
"""

from datetime import datetime
from pathlib import Path
from typing import Union

# 路径类型别名：兼容 str 与 pathlib.Path
PathLike = Union[str, Path]


class Logger:
    """
    轻量日志器：每行日志带时间戳，同时写控制台与日志文件。

    Attributes:
        log_file: 当前日志文件的绝对路径。
    """

    def __init__(self, log_dir: PathLike, name: str = "app"):
        """
        初始化日志器并立即创建日志文件。

        Args:
            log_dir: 日志目录（不存在则自动创建）。
            name: 日志文件名前缀，如 ``"flk"`` 将生成
                ``flk_log_20260622_120000.txt``。
        """
        log_dir_path = Path(log_dir)
        log_dir_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = log_dir_path / f"{name}_log_{timestamp}.txt"

    def log(self, message: str, *, level: str = "INFO") -> None:
        """
        记录一行日志（写控制台 + 追加写文件）。

        Args:
            message: 日志正文。
            level: 日志级别标签，默认 ``"INFO"``。
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"{timestamp} [{level}] {message}"
        print(entry)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except OSError as exc:
            # 日志写入失败不应中断主流程，降级为仅控制台提示
            print(f"{timestamp} [WARN] 日志写入失败: {exc}")
