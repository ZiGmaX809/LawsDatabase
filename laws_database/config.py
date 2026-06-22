# -*- coding: utf-8 -*-
"""
统一配置加载
============

加载 ``config.json``（共享基础配置，纳入版本控制）并与各源的 ``*.local.json``
（用户特定路径、运行时状态，被 gitignore）合并。

设计原则：

- ``config.json`` 只存非用户特定的共享配置（数据目录、API 端点、分页参数等）；
- ``*.local.json`` 存用户特定路径（整理目录、目标目录）与潜在敏感信息；
- **token 绝不持久化**，只作运行时内存变量；
- 所有相对路径相对于项目根解析，配置字典附带 ``_project_root`` 字段。
"""

import json
from pathlib import Path
from typing import Dict, Union

# 各源对应的 local 配置文件名（位于 configs/ 下）
_SOURCE_LOCAL_FILES = {
    "flk_laws": "laws.local.json",
    "court_cases": "pcc_config.local.json",
}


def load_config(project_root: Union[str, Path, None] = None) -> Dict:
    """
    加载统一配置：``config.json`` + 各源 local 配置合并。

    Args:
        project_root: 项目根目录。``None`` 时取本文件上两级
            （即 ``laws_database/`` 的父目录，项目根）。

    Returns:
        合并后的配置字典，附带 ``_project_root``（项目根绝对路径字符串）。
    """
    root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parent.parent
    config_path = root / "configs" / "config.json"

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        # 配置文件缺失时给出可用骨架，避免硬报错
        config = {"version": "2.0", "data_root": "data", "sources": {}}

    config["_project_root"] = str(root)

    # 合并各源 local 配置（覆盖 / 补充用户特定字段）
    sources = config.setdefault("sources", {})
    for source, local_file in _SOURCE_LOCAL_FILES.items():
        local_path = root / "configs" / local_file
        if not local_path.exists():
            continue
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                local = json.load(f)
            sources.setdefault(source, {}).update(local)
        except (OSError, json.JSONDecodeError) as e:
            print(f"加载本地配置失败 {local_path}: {e}")

    return config


def save_source_local(project_root: Union[str, Path], source: str, data: Dict) -> None:
    """
    将字段合并写入某源的 local 配置（保留原有字段）。

    Args:
        project_root: 项目根目录。
        source: 源 key（如 ``"flk_laws"``），必须在 :data:`_SOURCE_LOCAL_FILES` 中。
        data: 要合并写入的字段。

    Raises:
        ValueError: ``source`` 未知时。
    """
    root = Path(project_root).resolve()
    local_file = _SOURCE_LOCAL_FILES.get(source)
    if not local_file:
        raise ValueError(f"未知的源: {source}（已知: {list(_SOURCE_LOCAL_FILES)})")

    local_path = root / "configs" / local_file
    existing: Dict = {}
    if local_path.exists():
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (OSError, json.JSONDecodeError):
            existing = {}

    existing.update(data)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
