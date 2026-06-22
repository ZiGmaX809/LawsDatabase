# -*- coding: utf-8 -*-
"""
下载记录去重存储
================

三个数据源都用"记录文件"实现增量去重：

- 法答网：``.downloaded_records.txt``（安全标题集合，原为 append 写入）
- 法律法规：``download_state.json``（bbbs 集合，全量重写）
- 案例库：``known_case_nos_<type>.txt``、``organized_files_<type>.txt``
  （cpws_al_no / 文件名集合，全量重写）

本模块抽象出统一的 :class:`RecordStore`，支持 txt（每行一个 key）与 json
（``{"downloaded": [...]}`` 结构，兼容法律法规的 download_state.json）两种格式，
统一采用"启动时加载到内存集合 → 变更后全量重写"的写入策略，
比法答网原有的 append 模式更抗崩溃（崩溃时不会产生半行记录）。

设计原则：
- 存储格式与"按案件类型分文件"等业务策略解耦——后者由调用方持有多个实例；
- :func:`add_records` 遵循不可变风格，返回新集合，不就地修改。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Set, Union

PathLike = Union[str, Path]


class RecordStore:
    """
    基于文件的集合存储，用于下载去重与已整理记录。

    典型用法::

        store = RecordStore("data/fdw_qa/.downloaded_records.txt", fmt="txt")
        records = store.load()
        if title not in records:
            ...  # 执行下载
            store.save_all(add_records(records, title))
    """

    def __init__(self, path: PathLike, fmt: str = "txt"):
        """
        Args:
            path: 记录文件路径。父目录不存在时会在 :meth:`save_all` 时自动创建。
            fmt: 存储格式，``"txt"``（每行一个 key）或 ``"json"``
                （``{"downloaded": [...]}`` 结构，兼容法律法规的
                ``download_state.json``）。

        Raises:
            ValueError: ``fmt`` 不是 ``txt`` / ``json`` 时。
        """
        if fmt not in ("txt", "json"):
            raise ValueError(f"不支持的记录格式: {fmt}（仅支持 txt / json）")
        self.path = Path(path)
        self.fmt = fmt

    def load(self) -> Set[str]:
        """
        加载记录文件为字符串集合。

        文件不存在或损坏时返回空集合（而非抛错），保证首次运行可继续。
        """
        if not self.path.exists():
            return set()
        try:
            if self.fmt == "txt":
                with open(self.path, "r", encoding="utf-8") as f:
                    return {line.strip() for line in f if line.strip()}
            # json：兼容 Laws download_state.json 的 {"downloaded": [...]} 结构
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
                items = data.get("downloaded", []) if isinstance(data, dict) else data
                return {str(item).strip() for item in items if str(item).strip()}
        except (OSError, json.JSONDecodeError) as exc:
            print(f"加载记录文件失败 {self.path}: {exc}，将视为空记录")
            return set()

    def save_all(self, keys: Set[str]) -> None:
        """
        将整个集合全量写入记录文件（覆盖写入）。

        Args:
            keys: 要持久化的字符串集合。
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.fmt == "txt":
                with open(self.path, "w", encoding="utf-8") as f:
                    for key in sorted(keys):
                        f.write(f"{key}\n")
            else:  # json：保持与 download_state.json 一致的结构
                payload = {
                    "downloaded": sorted(keys),
                    "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "total_count": len(keys),
                }
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            print(f"保存记录文件失败 {self.path}: {exc}")

    def contains(self, key: str) -> bool:
        """便捷方法：判断 key 是否已在记录中（触发一次文件读取）。"""
        return key in self.load()


def add_records(records: Set[str], *keys: str) -> Set[str]:
    """
    不可变风格的集合添加：返回新集合，不修改原集合。

    Args:
        records: 原集合。
        *keys: 要添加的一个或多个键。

    Returns:
        包含所有新键的新集合。
    """
    return records | set(keys)
