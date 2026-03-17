#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法律版本管理模块
负责管理法律版本数据库，识别同名法律并添加年份后缀
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def extract_base_name(title: str) -> str:
    """
    从标题中提取基础名称，去除年份后缀

    支持的格式：
    - 中华人民共和国民用航空法（2021） -> 中华人民共和国民用航空法
    - 中华人民共和国民用航空法(2021) -> 中华人民共和国民用航空法
    - 中华人民共和国民用航空法（2021修正） -> 中华人民共和国民用航空法
    - 中华人民共和国民用航空法 -> 中华人民共和国民用航空法

    Args:
        title: 原始标题

    Returns:
        去除年份后缀的基础名称
    """
    if not title:
        return ""

    # 匹配：（年份）或 (年份) 或（年份+其他）
    patterns = [
        r'（\d{4}[^）]*）',  # 全角括号： （2021）或（2021修正）
        r'\(\d{4}[^\)]*\)',  # 半角括号： (2021)或(2021修正)
    ]

    result = title
    for pattern in patterns:
        result = re.sub(pattern, '', result).strip()

    return result


def extract_year(gbrq: str) -> str:
    """
    从公布日期中提取年份

    Args:
        gbrq: 公布日期，格式如 "2021-04-29" 或 "20210429"

    Returns:
        年份字符串，如 "2021"
    """
    if not gbrq:
        return ""
    # 移除可能的横线
    clean_date = gbrq.replace('-', '')
    if len(clean_date) >= 4:
        return clean_date[:4]
    return ""


@dataclass
class LawVersion:
    """单个法律版本信息"""
    year: str
    gbrq: str
    bbbs: str
    title: str  # 原始标题
    base_name: str  # 基础名称（无年份后缀）
    display_name: str = ""  # 显示名称（可能带年份后缀）
    file_path: str = ""  # JSON 文件相对路径
    md_path: str = ""  # Markdown 文件相对路径
    is_latest: bool = False
    processed: bool = False  # 是否已处理过

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.title


@dataclass
class LawInfo:
    """一个法律的所有版本信息"""
    base_name: str
    display_name: str
    versions: List[LawVersion] = field(default_factory=list)
    version_count: int = 0
    has_multiple_versions: bool = False
    latest_year: str = ""

    def update_stats(self):
        """更新统计信息"""
        self.version_count = len(self.versions)
        self.has_multiple_versions = self.version_count > 1
        if self.versions:
            # 按日期排序
            self.versions.sort(key=lambda v: v.gbrq or "")
            self.latest_year = self.versions[-1].year
            # 标记最新版本
            for v in self.versions:
                v.is_latest = (v.year == self.latest_year)


class LawVersionsDB:
    """法律版本数据库"""

    def __init__(self, db_path: str, output_dir: Path = None):
        """
        初始化数据库

        Args:
            db_path: 数据库文件路径
            output_dir: 输出目录（用于解析相对路径）
        """
        self.db_path = Path(db_path)
        self.output_dir = Path(output_dir) if output_dir else None
        self.data: Dict = {
            "version": "1.0",
            "generated_at": "",
            "statistics": {
                "total_unique_laws": 0,
                "total_versions": 0,
                "with_duplicates": 0
            },
            "laws": {}
        }
        self._load()

    def _load(self):
        """从文件加载数据库"""
        if self.db_path.exists():
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                return True
            except Exception as e:
                print(f"加载数据库失败: {e}")
        return False

    def save(self):
        """保存数据库到文件"""
        self.data["generated_at"] = datetime.now().isoformat()
        try:
            # 确保父目录存在
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存数据库失败: {e}")
            return False

    def get_law_info(self, base_name: str) -> Optional[LawInfo]:
        """获取法律信息"""
        law_data = self.data.get("laws", {}).get(base_name)
        if not law_data:
            return None

        versions = []
        for v_data in law_data.get("versions", []):
            version = LawVersion(
                year=v_data.get("year", ""),
                gbrq=v_data.get("gbrq", ""),
                bbbs=v_data.get("bbbs", ""),
                title=v_data.get("title", ""),
                base_name=v_data.get("base_name", base_name),
                display_name=v_data.get("display_name", ""),
                file_path=v_data.get("file_path", ""),
                md_path=v_data.get("md_path", ""),
                is_latest=v_data.get("is_latest", False),
                processed=v_data.get("processed", False)
            )
            versions.append(version)

        law_info = LawInfo(
            base_name=law_data.get("base_name", base_name),
            display_name=law_data.get("display_name", base_name),
            versions=versions
        )
        law_info.update_stats()
        return law_info

    def has_multiple_versions(self, base_name: str) -> bool:
        """判断是否有多个版本"""
        law_info = self.get_law_info(base_name)
        if not law_info:
            return False
        return law_info.has_multiple_versions

    def register_law(self, title: str, gbrq: str, bbbs: str, file_path: str, md_path: str = ""):
        """
        注册新法律到数据库

        Args:
            title: 原始标题（可能已带年份后缀）
            gbrq: 公布日期
            bbbs: 唯一标识
            file_path: JSON 文件路径
            md_path: Markdown 文件路径
        """
        # 清理标题，获取 base_name
        base_name = extract_base_name(title)
        year = extract_year(gbrq)

        if base_name not in self.data["laws"]:
            # 新法律
            self.data["laws"][base_name] = {
                "base_name": base_name,
                "display_name": base_name,
                "versions": [],
                "version_count": 0,
                "has_multiple_versions": False,
                "latest_year": ""
            }

        # 检查版本是否已存在
        law_data = self.data["laws"][base_name]
        existing_version = None
        for v in law_data["versions"]:
            if v.get("bbbs") == bbbs:
                existing_version = v
                break

        if existing_version:
            # 更新现有版本
            existing_version["file_path"] = file_path
            if md_path:
                existing_version["md_path"] = md_path
        else:
            # 添加新版本
            law_data["versions"].append({
                "year": year,
                "gbrq": gbrq,
                "bbbs": bbbs,
                "title": title,
                "base_name": base_name,
                "display_name": title,  # 初始使用原始标题
                "file_path": file_path,
                "md_path": md_path,
                "is_latest": False,
                "processed": False
            })

        # 更新统计
        law_data["versions"].sort(key=lambda x: x["gbrq"] or "")
        law_data["version_count"] = len(law_data["versions"])
        law_data["has_multiple_versions"] = law_data["version_count"] > 1
        law_data["latest_year"] = law_data["versions"][-1]["year"]

        # 标记最新版本
        for v in law_data["versions"]:
            v["is_latest"] = (v["year"] == law_data["latest_year"])

        # 更新全局统计
        self._update_statistics()

    def mark_processed(self, base_name: str, bbbs: str):
        """标记某个版本已处理"""
        law_data = self.data.get("laws", {}).get(base_name)
        if law_data:
            for v in law_data.get("versions", []):
                if v.get("bbbs") == bbbs:
                    v["processed"] = True
                    break

    def _update_statistics(self):
        """更新统计信息"""
        laws = self.data.get("laws", {})
        total_unique = len(laws)
        total_versions = 0
        with_duplicates = 0

        for base_name, law_data in laws.items():
            count = law_data.get("version_count", 0)
            total_versions += count
            if count > 1:
                with_duplicates += 1

        self.data["statistics"] = {
            "total_unique_laws": total_unique,
            "total_versions": total_versions,
            "with_duplicates": with_duplicates
        }

    def get_display_name(self, title: str, gbrq: str) -> str:
        """
        获取法律的显示名称

        如果有多个版本，添加年份后缀

        Args:
            title: 原始标题
            gbrq: 公布日期

        Returns:
            显示名称
        """
        base_name = extract_base_name(title)
        year = extract_year(gbrq)

        if self.has_multiple_versions(base_name):
            # 有多个版本，需要添加年份
            return f"{base_name}（{year}）"
        else:
            # 唯一版本，使用原始标题
            return title
