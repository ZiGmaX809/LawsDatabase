# -*- coding: utf-8 -*-
"""
国家法律法规数据库下载器（FLK）
================================

从 https://flk.npc.gov.cn 按分类下载法律 docx 文件并转换为 Markdown，
支持断点续传、多版本同名法律管理（年份后缀）、去重重命名、整理到知识库目录。

重构自原 ``flk_downloader`` 包（downloader.py + cli.py + config.py），整合点：

- 日志 / 文件名清理 / 下载记录统一到 :mod:`laws_database.core`；
- docx→Markdown 转换拆到 :mod:`laws_database.sources.flk_docx_converter`；
- 路径解耦：``data_dir``、状态文件、版本库均由构造参数注入，
  不再从 ``__file__`` 推导（切断原 ``Config`` 类的 project_root 耦合）。

入口：

- :func:`run`：交互式总菜单调用（二级菜单）。
- :func:`main`：命令行高级模式，``python -m laws_database.sources.flk_laws --all --fast``。
"""

import argparse
import json
import os
import random
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from laws_database.core import http_client
from laws_database.core.file_utils import sanitize_filename as _sanitize_filename
from laws_database.core.logger import Logger
from laws_database.core.record_store import RecordStore
from laws_database.sources.flk_docx_converter import convert_docx_to_markdown
from laws_database.sources.flk_laws_batch import FLKBatchOps
from laws_database.sources.law_versions_db import (
    LawVersionsDB,
    extract_base_name,
    extract_year,
)

# 法律分类定义（flfgCodeId 来自 API，每个分类对应固定 ID）
LAW_CATEGORIES = {
    "constitution": {"name": "宪法", "flfgCodeId": 100},
    "law": {"name": "法律", "flfgCodeId": 120},
    "administrative_regulation": {"name": "行政法规", "flfgCodeId": 210},
    "supervision_regulation": {"name": "监察法规", "flfgCodeId": 220},
    "local_regulation": {"name": "地方法规", "flfgCodeId": 310},
    "judicial_interpretation": {"name": "司法解释", "flfgCodeId": 320},
}

# API 端点配置
API_BASE = "https://flk.npc.gov.cn"
API_ENDPOINTS = {
    "search_list": "/law-search/search/list",
    "detail": "/law-search/search/flfgDetails",
}

# 代理配置（如需使用代理，修改此处）
PROXIES = None


class FLKDownloader(FLKBatchOps):
    """国家法律法规数据库下载器。"""

    def __init__(
        self,
        data_dir,
        state_file,
        versions_db_file,
        organized_dir=None,
        page_size: int = 100,
        min_delay: float = 0.0,
        max_delay: float = 0.5,
    ):
        """
        初始化下载器。

        Args:
            data_dir: 数据输出根目录（含 docx/markdown/json/logs 子目录）。
            state_file: 下载状态记录文件路径（json，存 bbbs 集合）。
            versions_db_file: 法律版本数据库文件路径（law_versions.json）。
            organized_dir: 整理目标目录（外部知识库），可选。
            page_size: API 每页数量。
            min_delay: 请求间最小延迟（秒）。
            max_delay: 请求间最大延迟（秒）。
        """
        self.output_dir = Path(data_dir)
        self.page_size = page_size
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.versions_db_file = Path(versions_db_file)
        self.organized_dir = Path(organized_dir) if organized_dir else None

        # 统一日志器（替代原 self.log_file + self.log）
        self.logger = Logger(self.output_dir / "logs", name="flk")

        # 下载状态记录（json 格式，bbbs 集合），替代原 load_state/save_state
        self.state_store = RecordStore(state_file, fmt="json")
        self.downloaded_files = self.state_store.load()
        self.logger.log(f"已加载 {len(self.downloaded_files)} 条下载记录")

        # HTTP 会话（连接复用 + 默认 UA）
        self.session = http_client.make_session()
        self.headers = self._build_headers()

        self.init_dirs()

    def _build_headers(self) -> Dict:
        """构建 FLK 专用请求头。"""
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": API_BASE,
            "Referer": f"{API_BASE}/search",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": http_client.DEFAULT_USER_AGENT,
            "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }

    def init_dirs(self):
        """初始化输出目录结构。"""
        for d in [
            self.output_dir,
            self.output_dir / "docx",
            self.output_dir / "markdown",
            self.output_dir / "json",
            self.output_dir / "json" / "laws",
        ]:
            d.mkdir(parents=True, exist_ok=True)

    # ---- 向后兼容转发：保持原调用点 self.log / self.sanitize_filename 不变 ----

    def log(self, message: str):
        """记录日志（转发到统一日志器）。"""
        self.logger.log(message)

    def sanitize_filename(self, name: str) -> str:
        """清理文件名（转发到 core.file_utils）。"""
        return _sanitize_filename(name)

    def load_state(self) -> set:
        """加载下载状态。"""
        return self.state_store.load()

    def save_state(self):
        """保存下载状态。"""
        self.state_store.save_all(self.downloaded_files)

    # ---- 法律版本与命名 ----

    def extract_gbrq_from_md(self, md_path: Path) -> Optional[str]:
        """
        从 Markdown 文件中提取公布日期。

        Args:
            md_path: Markdown 文件路径。

        Returns:
            公布日期字符串（如 "2021-04-29"），失败返回 None。
        """
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
            for line in content.split("\n"):
                line = line.strip()
                if "公布日期" in line and "**" in line:
                    match = re.search(r"\*\*公布日期\*\*\s*:\s*(\d{4}-\d{2}-\d{2})", line)
                    if match:
                        return match.group(1)
            return None
        except Exception as e:
            self.log(f"提取公布日期失败 {md_path.name}: {e}")
            return None

    def get_clean_md_filename(self, title: str, category_name: str, law_type_folder: str) -> str:
        """获取干净的 Markdown 文件名（去除日期和 hash 后缀）。"""
        return self.sanitize_filename(title)

    def ensure_unique_md_filename(
        self,
        title: str,
        gbrq: str,
        bbbs: str,
        category_name: str,
        law_type_folder: str,
        db: LawVersionsDB = None,
    ) -> Tuple[str, bool]:
        """
        确保生成唯一的 Markdown 文件名。

        逻辑：
        1. 先尝试干净文件名（无年份后缀）；
        2. 若已存在，查数据库是否有多个版本；
        3. 若有多个版本，为所有版本添加年份后缀；
        4. 返回 (文件名, 是否重命名了已有文件)。

        Args:
            title: 法律标题。
            gbrq: 公布日期。
            bbbs: 唯一标识。
            category_name: 分类名称。
            law_type_folder: 法律类型文件夹。
            db: 法律版本数据库（可选）。

        Returns:
            (文件名, 是否重命名了已有文件)。
        """
        base_name = extract_base_name(title)
        year = extract_year(gbrq)

        md_dir = self.output_dir / "markdown" / category_name / law_type_folder
        clean_name = self.sanitize_filename(base_name)
        clean_md_path = md_dir / f"{clean_name}.md"

        # 干净文件名不存在，直接使用
        if not clean_md_path.exists():
            return clean_name, False

        self.log(f"检测到重复文件: {clean_name}.md")

        # 判断是否有多个版本
        has_multiple = False
        if db:
            has_multiple = db.has_multiple_versions(base_name)
        else:
            for _existing in md_dir.glob(f"{base_name}（*.md"):
                has_multiple = True
                break

        if not has_multiple:
            # 只有一个版本，直接覆盖（可能是更新）
            return clean_name, False

        self.log(f"法律有多个版本，需要添加年份后缀: {base_name}")

        existing_gbrq = self.extract_gbrq_from_md(clean_md_path)
        if existing_gbrq:
            existing_year = extract_year(existing_gbrq)
            old_name = f"{base_name}（{existing_year}）"
            old_md_path = md_dir / f"{old_name}.md"

            if not old_md_path.exists():
                try:
                    clean_md_path.rename(old_md_path)
                    self.log(f"已重命名已有文件: {clean_name}.md -> {old_name}.md")

                    if db:
                        law_info = db.get_law_info(base_name)
                        if law_info:
                            for v in law_info.versions:
                                if v.md_path and v.md_path.endswith(f"{clean_name}.md"):
                                    try:
                                        new_rel_path = old_md_path.relative_to(self.output_dir)
                                        v.md_path = str(new_rel_path).replace("\\", "/")
                                    except ValueError:
                                        pass
                            db.save()
                except Exception as e:
                    self.log(f"重命名已有文件失败: {e}")

        new_name = f"{base_name}（{year}）"
        return new_name, True

    def get_law_type_folder(self, flxz: str) -> str:
        """根据法律类型获取文件夹名称。"""
        if not flxz:
            return "未知类型"
        return self.sanitize_filename(flxz)

    # ---- API 交互 ----

    def get_law_list(self, category_key: str, page: int = 1) -> Optional[Dict]:
        """
        获取法律列表。

        Args:
            category_key: 分类 key（如 'constitution', 'law'）。
            page: 页码。

        Returns:
            API 响应数据，失败返回 None。
        """
        if category_key not in LAW_CATEGORIES:
            self.log(f"错误: 不支持的分类 {category_key}")
            return None

        category = LAW_CATEGORIES[category_key]
        payload = {
            "searchRange": 1,
            "sxrq": [],
            "gbrq": [],
            "searchType": 2,
            "sxx": [],
            "gbrqYear": [],
            "flfgCodeId": [category["flfgCodeId"]],
            "zdjgCodeId": [],
            "searchContent": "",
            "orderByParam": {"order": "-1", "sort": ""},
            "pageNum": page,
            "pageSize": self.page_size,
        }

        url = f"{API_BASE}{API_ENDPOINTS['search_list']}"
        try:
            response = self.session.post(
                url, headers=self.headers, json=payload, proxies=PROXIES, timeout=30
            )
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 200:
                total = data.get("total", 0)
                rows = data.get("rows", [])
                self.log(f"获取 {category['name']} 第{page}页: {len(rows)}条，总计 {total} 条")
                return data
            self.log(f"获取列表失败: {data.get('msg')}")
            return None
        except Exception as e:
            self.log(f"请求失败: {e}")
            return None

    def get_law_detail(self, bbbs: str) -> Optional[Dict]:
        """获取法律详情（含文件路径）。"""
        url = f"{API_BASE}{API_ENDPOINTS['detail']}"
        try:
            response = self.session.get(
                url, headers=self.headers, params={"bbbs": bbbs}, proxies=PROXIES, timeout=30
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") == 200:
                return data.get("data")
            self.log(f"获取详情失败: {data.get('msg')}")
            return None
        except Exception as e:
            self.log(f"获取详情出错: {e}")
            return None

    def get_download_url(self, file_path: str) -> str:
        """
        获取下载 URL（直接下载 API，返回 docx 文件内容，无需签名）。

        Args:
            file_path: 文件路径（如 'prod/20180311/xxx.docx'）。
        """
        if not file_path.startswith("/"):
            file_path = "/" + file_path
        encoded_path = quote(file_path, safe="")
        return f"{API_BASE}/law-search/file/download?filePath={encoded_path}"

    def download_docx(self, download_url: str, output_path: Path) -> bool:
        """下载 docx 文件。"""
        try:
            response = self.session.get(
                download_url,
                headers={"User-Agent": self.headers["User-Agent"]},
                proxies=PROXIES,
                timeout=60,
                stream=True,
            )
            response.raise_for_status()

            # 检查是否返回了错误（JSON 而非文件）
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                try:
                    error_data = response.json()
                    if error_data.get("code") == 500:
                        self.log(f"下载失败: {error_data.get('msg', 'Unknown error')}")
                        return False
                except Exception:
                    pass

            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            self.log(f"下载成功: {output_path.name}")
            return True
        except Exception as e:
            self.log(f"下载失败: {e}")
            return False

    def save_law_info(self, law: Dict, detail: Dict, category_key: str = None) -> bool:
        """保存法律信息到 JSON 文件。"""
        try:
            bbbs = law.get("bbbs") or ""
            title = law.get("title", "未知")

            law_info = {
                "bbbs": bbbs,
                "title": title,
                "gbrq": law.get("gbrq", ""),
                "sxrq": law.get("sxrq") or "",
                "sxx": law.get("sxx", 0),
                "zdjgName": law.get("zdjgName") or "",
                "flxz": law.get("flxz", ""),
                "zdjgCodeId": law.get("zdjgCodeId", 0),
                "flfgCodeId": law.get("flfgCodeId", 0),
                "detail": detail,
                "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

            safe_title = self.sanitize_filename(title)
            gbrq = (law.get("gbrq") or "").replace("-", "")
            flxz = law.get("flxz") or "未知类型"
            law_type_folder = self.get_law_type_folder(flxz)

            if category_key and category_key in LAW_CATEGORIES:
                category_name = LAW_CATEGORIES[category_key]["name"]
            else:
                category_name = "未分类"

            json_filename = f"{safe_title}_{gbrq}_{bbbs[:10]}.json"
            json_path = self.output_dir / "json" / "laws" / category_name / law_type_folder / json_filename
            os.makedirs(json_path.parent, exist_ok=True)

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(law_info, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            self.log(f"保存JSON失败: {e}")
            return False

    # ---- 批处理 ----

# ===========================================================================
# 入口：交互式菜单 run(config) 与命令行 main()
# ===========================================================================

def _show_categories():
    """打印法律分类列表。"""
    print("\n法律分类:")
    for key, cat in LAW_CATEGORIES.items():
        print(f"  {key:28s} {cat['name']}")


def _prompt_organized_dir(project_root: Path):
    """
    交互式输入整理目录并保存到 laws.local.json。

    Args:
        project_root: 项目根目录。

    Returns:
        设置成功的整理目录 Path，或用户跳过时返回 None。
    """
    print("\n请输入整理目录路径（用于存放整理后的 Markdown 文件）")
    print("示例: /Users/username/Documents/LawsMD")
    while True:
        try:
            raw = input("整理目录（回车跳过）: ").strip()
            if not raw:
                print("已跳过整理目录设置")
                return None
            path = Path(raw).expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
            from laws_database.config import save_source_local
            save_source_local(project_root, "flk_laws", {"organized_dir": str(path)})
            print(f"✓ 整理目录已设置: {path}")
            return path
        except (EOFError, KeyboardInterrupt):
            print("\n已跳过")
            return None
        except Exception as e:
            print(f"无效路径: {e}，请重新输入")


def _build_downloader(src: Dict, project_root: Path, fast: bool = False) -> "FLKDownloader":
    """根据源配置构造 FLKDownloader。"""
    page_size = src.get("page_size", 100)
    default_delay = src.get("default_delay", [0, 0.5])
    mn, mx = (0, 0) if fast else (default_delay[0], default_delay[1])
    return FLKDownloader(
        data_dir=project_root / src["data_dir"],
        state_file=project_root / src["state_file"],
        versions_db_file=project_root / src["versions_db_file"],
        organized_dir=src.get("organized_dir"),
        page_size=page_size,
        min_delay=mn,
        max_delay=mx,
    )


def run(config: Dict):
    """
    交互式菜单入口（由总菜单调用）。

    Args:
        config: :func:`laws_database.config.load_config` 返回的统一配置字典。
    """
    project_root = Path(config["_project_root"])
    src = config["sources"]["flk_laws"]

    while True:
        print("\n" + "=" * 50)
        print("        国家法律法规数据库 (FLK)")
        print("=" * 50)
        print("  1. 下载全部分类（排除地方法规）")
        print("  2. 下载指定分类")
        print("  3. 转换已下载 docx 为 Markdown")
        print("  4. 整理 Markdown 到知识库目录")
        print("  5. 去重重命名（多版本加年份）")
        print("  6. 初始化 / 重建版本数据库")
        print("  7. 设置整理目录")
        print("  0. 返回上级菜单")
        print("=" * 50)
        choice = input("请选择: ").strip()

        if choice == "0":
            break
        try:
            if choice == "1":
                fast = input("快速模式（无延迟）? (y/n，默认n): ").strip().lower() == "y"
                downloader = _build_downloader(src, project_root, fast)
                downloader.process_all([k for k in LAW_CATEGORIES if k != "local_regulation"])
                if downloader.organized_dir:
                    downloader.organize_markdown_files()
            elif choice == "2":
                _show_categories()
                cat = input("\n输入分类代码: ").strip()
                if cat not in LAW_CATEGORIES:
                    print("无效分类")
                    continue
                fast = input("快速模式? (y/n，默认n): ").strip().lower() == "y"
                downloader = _build_downloader(src, project_root, fast)
                downloader.process_category(cat)
                if downloader.organized_dir:
                    downloader.organize_markdown_files()
            elif choice == "3":
                _build_downloader(src, project_root).convert_existing_docx()
            elif choice == "4":
                downloader = _build_downloader(src, project_root)
                if not downloader.organized_dir:
                    downloader.organized_dir = _prompt_organized_dir(project_root)
                if downloader.organized_dir:
                    downloader.organize_markdown_files()
            elif choice == "5":
                _build_downloader(src, project_root).deduplicate_markdown_files()
            elif choice == "6":
                _build_downloader(src, project_root).init_law_versions_db()
            elif choice == "7":
                _prompt_organized_dir(project_root)
                # 重新加载配置以反映新设置的 organized_dir
                from laws_database.config import load_config
                config = load_config(project_root)
                src = config["sources"]["flk_laws"]
            else:
                print("无效选择")
        except KeyboardInterrupt:
            print("\n操作已取消")
        except Exception as e:
            print(f"操作失败: {e}")


def _print_usage():
    """打印命令行使用说明。"""
    print(
        """
国家法律法规数据库下载器
========================
用法: python -m laws_database.sources.flk_laws [选项]

选项:
    --category CAT     指定分类（可多次指定）
    --all              下载所有分类（排除地方法规）
    --pages N          限制下载页数
    --page-size N      每页数量（默认 100）
    --fast             快速模式（无延迟）
    --min-delay SEC    最小延迟（默认 0）
    --max-delay SEC    最大延迟（默认 0.5）
    --output DIR       数据目录（默认读 config.json）
    --json-only        仅保存 JSON 元数据
    --convert          仅转换已下载 docx
    --init-db          初始化版本数据库
    --dedup            去重重命名
    --organize         整理到知识库目录
    --set-organized-dir PATH  设置整理目录
    --dry-run          预览模式
    --force            强制重新处理
    --help, -h         显示此帮助

分类: """
        + ", ".join(LAW_CATEGORIES.keys())
        + "\n"
    )


def main():
    """命令行高级模式入口（python -m laws_database.sources.flk_laws）。"""
    parser = argparse.ArgumentParser(description="国家法律法规数据库下载器", add_help=False)
    parser.add_argument("--category", action="append", dest="categories")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--pages", type=int)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--min-delay", type=float, default=0)
    parser.add_argument("--max-delay", type=float, default=0.5)
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--convert", action="store_true")
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--dedup", action="store_true")
    parser.add_argument("--organize", action="store_true")
    parser.add_argument("--set-organized-dir", type=str, metavar="PATH")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--help", "-h", action="store_true")
    args = parser.parse_args()

    if args.help:
        _print_usage()
        return 0

    project_root = Path(__file__).resolve().parent.parent.parent
    from laws_database.config import load_config, save_source_local

    config = load_config(project_root)
    src = config["sources"]["flk_laws"]

    if args.set_organized_dir:
        path = Path(args.set_organized_dir).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        save_source_local(project_root, "flk_laws", {"organized_dir": str(path)})
        print(f"✓ 整理目录已设置: {path}")
        return 0

    data_dir = Path(args.output) if args.output else project_root / src["data_dir"]
    mn, mx = (0, 0) if args.fast else (args.min_delay, args.max_delay)
    downloader = FLKDownloader(
        data_dir=data_dir,
        state_file=project_root / src["state_file"],
        versions_db_file=project_root / src["versions_db_file"],
        organized_dir=src.get("organized_dir"),
        page_size=args.page_size,
        min_delay=mn,
        max_delay=mx,
    )

    if args.init_db:
        downloader.init_law_versions_db()
        return 0
    if args.dedup:
        downloader.deduplicate_markdown_files(dry_run=args.dry_run, force=args.force)
        return 0
    if args.organize:
        downloader.organize_markdown_files(dry_run=args.dry_run)
        return 0
    if args.convert:
        downloader.convert_existing_docx()
        if downloader.organized_dir:
            downloader.organize_markdown_files()
        return 0

    if args.all:
        categories = [k for k in LAW_CATEGORIES if k != "local_regulation"]
    elif args.categories:
        categories = args.categories
        for c in categories:
            if c not in LAW_CATEGORIES:
                print(f"错误: 不支持的分类 '{c}'")
                return 1
    else:
        print("错误: 请指定 --category 或 --all")
        _print_usage()
        return 1

    if args.pages or args.json_only:
        for cat in categories:
            downloader.process_category(cat, max_pages=args.pages, save_json_only=args.json_only)
    else:
        downloader.process_all(categories)

    if downloader.organized_dir:
        downloader.organize_markdown_files()
    return 0


if __name__ == "__main__":
    sys.exit(main())
