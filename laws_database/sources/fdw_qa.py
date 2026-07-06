# -*- coding: utf-8 -*-
"""
法答网精选答问抓取器（FDW）
==========================

从 https://www.court.gov.cn 抓取"法答网精选答问"内容，转 Markdown 保存。
支持基于下载记录的增量去重，以及旧文件名批量重命名。

重构自原 ``FDW_QA/court_content_scraper.py``，整合点：

- HTTP 请求壳 / 下载记录 / 日志统一到 :mod:`laws_database.core`；
- 清理未使用的 ``import markdown``（原代码 import 但从未调用）；
- 移除未被调用的 ``fetch_content`` 死代码；
- 路径解耦：输出目录由参数注入，不再硬编码 ``court_contents``。
- 业务命名规则 :meth:`FDWScraper.get_safe_filename` 保留在本模块
  （法答网特有的中文括号 / 专题格式转换，属领域知识，不统一到 core）。

入口：

- :func:`run`：交互式总菜单调用（二级菜单）。
- :func:`main`：命令行模式，``python -m laws_database.sources.fdw_qa``。
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from laws_database.core import http_client
from laws_database.core.logger import Logger
from laws_database.core.record_store import RecordStore


class FDWScraper:
    """法答网精选答问抓取器。"""

    def __init__(self, data_dir, base_url: str, search_url: str, delay_range=(1, 3)):
        """
        初始化抓取器。

        Args:
            data_dir: 输出目录（如 ``data/fdw_qa``）。
            base_url: 站点基址（用于拼接相对链接）。
            search_url: 搜索页 URL（列表入口）。
            delay_range: 请求间随机延迟 ``(min, max)`` 秒。
        """
        self.output_dir = Path(data_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url
        self.search_url = search_url
        self.delay_range = tuple(delay_range)
        self.logger = Logger(self.output_dir / "logs", name="fdw")
        self.session = http_client.make_session()
        # 下载记录（txt 集合，安全标题去重）
        self.record_store = RecordStore(self.output_dir / ".downloaded_records.txt", fmt="txt")

    def fetch_page(self, url: str):
        """抓取页面 HTML，带随机延迟防封。"""
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
            "Connection": "keep-alive",
        }
        try:
            http_client.random_delay(self.delay_range)
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            response.encoding = "utf-8"
            return response.text
        except requests.exceptions.RequestException as e:
            self.logger.log(f"Error fetching {url}: {e}")
            return None

    def parse_links(self, html: str):
        """从搜索页 HTML 解析答问链接列表。"""
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        # 兼容多种可能的 class 命名
        search_list = (
            soup.find("div", class_="search_list")
            or soup.find("div", class_="search-list")
            or soup.find("div", class_="searchList")
        )
        if not search_list:
            self.logger.log("Could not find search list div")
            return []
        links = []
        for li in search_list.find_all("li"):
            a_tag = li.find("a")
            if not (a_tag and a_tag.has_attr("href")):
                continue
            href = a_tag["href"]
            # 过滤分页导航链接（首页/上一页/下一页/尾页），
            # 它们形如 /search.html?content=...&page=N，是搜索页而非文章正文，
            # 误当文章下载必然 "No title found" 失败。
            if "search.html" in href or "page=" in href:
                continue
            links.append(href)
        return links

    def parse_total_pages(self, html: str) -> int:
        """
        从分页栏解析总页数。

        取 "尾页" 链接的 ``page`` 参数作为总页数，作为翻页的硬上限。
        court.gov.cn 对超出范围的页码会**静默回退到最后一页**（实测 page=3
        与 page=2 返回完全相同内容），因此绝不能用 "翻到空页为止" 的策略，
        否则会在最后一页死循环。尾页参数是唯一可靠的终止信号。

        Args:
            html: 搜索结果页 HTML（通常传第 1 页）。

        Returns:
            总页数；解析失败时安全降级为 1（只抓第 1 页，绝不死循环）。
        """
        if not html:
            return 1
        soup = BeautifulSoup(html, "html.parser")
        last_link = soup.find("a", string="尾页")
        if last_link and last_link.has_attr("href"):
            match = re.search(r"[?&]page=(\d+)", last_link["href"])
            if match:
                return int(match.group(1))
        return 1

    def _build_page_url(self, page: int) -> str:
        """
        构造第 N 页的搜索 URL。

        在原始 ``search_url`` 上追加 ``page`` 参数。``search_url`` 通常已带
        ``?content=...`` 查询串，故用 ``&`` 拼接；若入口 URL 无查询串，
        则用 ``?`` 起始，保证 URL 始终合法。复用原始 ``search_url`` 的编码
        （content 为 %E6%B3... 形式），而非用页面里未编码的中文，避免编码
        不一致导致的搜索结果差异。

        Args:
            page: 页码（从 1 开始）。

        Returns:
            拼接好 ``page`` 参数的完整 URL。
        """
        separator = "&" if "?" in self.search_url else "?"
        return f"{self.search_url}{separator}page={page}"

    def get_safe_filename(self, title: str) -> str:
        """
        根据标题生成安全的文件名（法答网特有业务规则）。

        转换规则：
        - 法答网精选答问（第三批）→ 法答网精选答问(第三批）
        - 法答网精选答问（第三十五批）——商事审判专题 → 法答网精选答问(第三十五批-商事审判专题）

        即外层中文括号统一为 ``(`` 开头，``——`` 转为 ``-``，内层括号转 ``【】``，
        最后统一以 ``）`` 结尾，并替换文件系统非法字符。

        Args:
            title: 原始标题字符串。

        Returns:
            安全的文件名（不含扩展名）。
        """
        if not title:
            return "unknown"

        title = title.lstrip("#").strip()
        filename = title

        if "——" in filename:
            # 有专题：法答网精选答问（第三十五批）——商事审判专题
            left_count = filename.count("（")
            filename = filename.replace("）——", "-")
            if filename.endswith("）"):
                filename = filename[:-1]
            if left_count >= 2:
                # 有内层括号，只保留第一个（为（，其余转【】
                prefix_end = filename.find("（") + 1
                prefix = filename[:prefix_end]
                rest = filename[prefix_end:]
                rest = rest.replace("（", "【").replace("）", "】")
                if "【" in rest and not rest.endswith("】"):
                    rest += "】"
                filename = prefix + rest
        else:
            # 无专题：法答网精选答问（第三批）
            if filename.endswith("）"):
                filename = filename[:-1]

        # 替换文件系统不允许的字符
        for char in r'\/:*?"<>|':
            filename = filename.replace(char, "_")

        filename = filename.strip(" .")
        filename += "）"
        return filename

    def _format_content(self, title_text: str, body_text: str) -> str:
        """
        将正文格式化为 Markdown。

        规则：以 "问题" 开头且含 "：" 的行视为小标题，转为二级标题 ``## ``；
        其余行原样保留。最终以一级标题 ``# 标题`` 起始。

        Args:
            title_text: 文章标题（用于一级标题）。
            body_text: 正文纯文本（``div.txt.big`` 的文本）。

        Returns:
            拼接好的 Markdown 字符串。
        """
        formatted_lines = []
        for line in body_text.split("\n"):
            line = line.lstrip()
            if line.startswith("问题") and "：" in line:
                formatted_lines.append(f"## {line}")
            else:
                formatted_lines.append(line)
        body = "\n".join(formatted_lines)
        return f"# {title_text}\n\n{body}\n"

    def _index_path(self):
        """URL→文件名 索引文件路径（与旧 txt 记录并存，互为兜底）。"""
        return self.output_dir / ".download_index.json"

    def _load_url_index(self):
        """
        加载 URL→文件名 索引。

        索引结构：``{"url_index": {href: safe_title, ...}, ...}``。
        文件不存在或损坏时返回空 dict（首次运行或索引丢失可继续，后续逐条补全）。
        """
        path = self._index_path()
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            mapping = data.get("url_index", {}) if isinstance(data, dict) else {}
            return dict(mapping)
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.log(f"加载 URL 索引失败: {exc}，视为空索引")
            return {}

    def _save_url_index(self, index):
        """
        原子写入 URL→文件名 索引。

        采用 "写临时文件 → os.replace 原子替换" 策略：崩溃时不会留下半截 JSON；
        os.replace 在同一文件系统内是原子操作，多进程并发时也只会看到完整的
        旧版或新版（并发安全）。
        """
        path = self._index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "url_index": dict(sorted(index.items())),
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_count": len(index),
        }
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except OSError as exc:
            self.logger.log(f"保存 URL 索引失败: {exc}")

    def save_to_markdown(self, links):
        """
        先整体判断存在性，再增量下载。

        两阶段流程：

        1. **整体判断**：用 URL→文件名 索引快速过滤——索引命中的链接直接跳过，
           **完全不发请求**（这是日常运行的快速路径，已下载内容零抓取）。
        2. **增量下载**：仅对索引未命中的链接抓取页面。抓取后若发现文件已存在
           或旧文件名记录已登记（迁移期，索引尚未建立），只补全 URL 索引、不重写
           文件；确属新增才写文件并更新双份记录（URL 索引 + 旧 txt 记录）。

        设计依据：文件名只能从抓取到的页面标题计算得到，而 URL 在抓取前已知，
        故用 URL 作为主去重键，可避免对已下载内容的重复抓取（旧方案每次都要
        抓取全部已下载项取标题，是主要的耗时来源）。
        """
        url_index = self._load_url_index()
        downloaded_titles = self.record_store.load()

        # —— 阶段1：整体判断，区分"索引命中(跳过)"与"待处理" ——
        cached = [lnk for lnk in links if lnk in url_index]
        pending = [lnk for lnk in links if lnk not in url_index]
        self.logger.log(
            f"整体判断: 共 {len(links)} 篇, URL索引命中 {len(cached)} 篇(跳过抓取), "
            f"待处理 {len(pending)} 篇"
        )
        for lnk in cached:
            print(f"跳过(索引命中): {url_index[lnk]}.md")

        saved = 0
        migrated = 0
        failed = 0
        total = len(links)
        # 待处理项的日志序号接在索引命中项之后，便于对照总量
        seq_start = len(cached)

        # —— 阶段2：增量处理索引未命中的链接 ——
        for i, link in enumerate(pending):
            seq = seq_start + i + 1
            full_url = urljoin(self.base_url, link)
            html = self.fetch_page(full_url)
            if not html:
                self.logger.log(f"Failed to fetch {full_url}")
                failed += 1
                continue

            soup = BeautifulSoup(html, "html.parser")
            title_div = soup.find("div", class_="title")
            if not title_div:
                self.logger.log(f"No title found for {full_url}")
                failed += 1
                continue

            title_text = title_div.get_text().strip()
            safe_title = self.get_safe_filename(title_text)

            # 文件已存在：之前下载过，仅 URL 索引缺失 → 补全索引、不重写文件。
            # 以文件系统为准（而非旧 txt 记录）：文件若丢失则重新下载，保证内容完整。
            file_path = self.output_dir / f"{safe_title}.md"
            if file_path.exists():
                url_index = {**url_index, link: safe_title}
                self._save_url_index(url_index)
                print(f"[{seq}/{total}] 补全索引(已下载): {safe_title}.md")
                migrated += 1
                continue

            # 确属新增：抓正文、写文件
            txt_big = soup.find("div", class_="txt big")
            if not txt_big:
                self.logger.log(f"No content found for {full_url}")
                failed += 1
                continue

            content = self._format_content(title_text, txt_big.get_text().strip())
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            # 更新双份记录（不可变：构造新 dict / 新集合）
            url_index = {**url_index, link: safe_title}
            self._save_url_index(url_index)
            downloaded_titles = downloaded_titles | {safe_title}
            self.record_store.save_all(downloaded_titles)

            print(f"[{seq}/{total}] 已保存: {file_path}")
            saved += 1

        self.logger.log(
            f"总结: 共 {len(links)} 篇, 新下载 {saved} 个, 补全索引 {migrated} 个, "
            f"索引命中跳过 {len(cached)} 个, 失败 {failed} 个"
        )

    def rename_existing_files(self):
        """
        批量重命名现有文件（旧格式 → 新格式），并同步更新下载记录。

        旧格式：法答网精选答问_第三批.md
        新格式：法答网精选答问(第三批).md
        """
        if not self.output_dir.exists():
            self.logger.log(f"目录不存在: {self.output_dir}")
            return

        old_records = self.record_store.load()
        filename_map = {}

        md_files = [f for f in os.listdir(self.output_dir) if f.endswith(".md") and not f.startswith(".")]
        renamed_count = 0
        skipped_count = 0
        error_count = 0

        for old_filename in md_files:
            old_path = self.output_dir / old_filename
            try:
                with open(old_path, "r", encoding="utf-8") as f:
                    first_line = f.readline().strip()
                title = first_line.lstrip("#").strip() if first_line.startswith("#") else old_filename.replace(".md", "")
                new_filename = self.get_safe_filename(title) + ".md"
                new_path = self.output_dir / new_filename

                if old_filename == new_filename:
                    skipped_count += 1
                    filename_map[old_filename.replace(".md", "")] = old_filename.replace(".md", "")
                    continue

                # 目标已存在则加序号
                if new_path.exists() and old_path != new_path:
                    base, ext = os.path.splitext(new_filename)
                    counter = 1
                    while (self.output_dir / f"{base}_{counter}{ext}").exists():
                        counter += 1
                    new_filename = f"{base}_{counter}{ext}"
                    new_path = self.output_dir / new_filename

                filename_map[old_filename.replace(".md", "")] = new_filename.replace(".md", "")
                old_path.rename(new_path)
                print(f"重命名: {old_filename} -> {new_filename}")
                renamed_count += 1
            except Exception as e:
                print(f"重命名失败 {old_filename}: {e}")
                error_count += 1

        # 更新下载记录
        if renamed_count > 0:
            updated = set()
            for old_record in old_records:
                updated.add(filename_map.get(old_record, old_record))
            updated.update(filename_map.values())
            self.record_store.save_all(updated)
            print(f"下载记录已更新（共 {len(updated)} 条记录）")

        print(f"\n重命名完成: 成功 {renamed_count} 个, 跳过 {skipped_count} 个, 失败 {error_count} 个")

    def download(self):
        """主流程：抓取搜索页（含翻页）→ 解析链接 → 去重 → 下载保存。"""
        self.logger.log("开始爬取内容...")

        first_html = self.fetch_page(self.search_url)
        if not first_html:
            self.logger.log("Failed to fetch initial page")
            return

        total_pages = self.parse_total_pages(first_html)
        all_links = self.parse_links(first_html)
        self.logger.log(f"第 1/{total_pages} 页: 找到 {len(all_links)} 个文章链接")

        # 翻页累积后续页面的文章链接（total_pages 为硬上限，不会死循环）
        for page in range(2, total_pages + 1):
            page_html = self.fetch_page(self._build_page_url(page))
            if not page_html:
                self.logger.log(f"Failed to fetch page {page}, 跳过该页")
                continue
            page_links = self.parse_links(page_html)
            self.logger.log(f"第 {page}/{total_pages} 页: 找到 {len(page_links)} 个文章链接")
            all_links.extend(page_links)

        # 跨页去重并保持顺序（不可变：构建新列表，不改原始累积列表语义）
        seen = set()
        unique_links = []
        for link in all_links:
            if link not in seen:
                seen.add(link)
                unique_links.append(link)

        if not unique_links:
            self.logger.log("No links found")
            return

        self.logger.log(
            f"共 {total_pages} 页, 去重后 {len(unique_links)} 个文章链接, 开始下载内容..."
        )
        self.save_to_markdown(unique_links)
        self.logger.log("下载完成!")


# ===== 入口 =====

def run(config: dict):
    """交互式菜单入口（由总菜单调用）。"""
    project_root = Path(config["_project_root"])
    src = config["sources"]["fdw_qa"]
    scraper = FDWScraper(
        data_dir=project_root / src["data_dir"],
        base_url=src["base_url"],
        search_url=src["search_url"],
        delay_range=src.get("delay_range", [1, 3]),
    )

    print("\n" + "=" * 50)
    print("        法答网精选答问 (FDW)")
    print("=" * 50)
    print("  1. 下载新内容（增量）")
    print("  2. 重命名现有文件为统一格式")
    print("  0. 返回上级菜单")
    print("=" * 50)
    choice = input("请选择: ").strip()
    if choice == "1":
        scraper.download()
    elif choice == "2":
        scraper.rename_existing_files()
    elif choice == "0":
        return
    else:
        print("无效选择")


def main():
    """命令行入口（python -m laws_database.sources.fdw_qa）。"""
    parser = argparse.ArgumentParser(description="法答网内容下载和重命名工具", add_help=False)
    parser.add_argument("--rename", action="store_true", help="仅重命名现有文件，不下载新内容")
    parser.add_argument("--download", action="store_true", help="下载新内容（默认操作）")
    parser.add_argument("--help", "-h", action="store_true")
    args = parser.parse_args()

    if args.help:
        print("""
用法: python -m laws_database.sources.fdw_qa [选项]

选项:
  --rename    仅重命名现有文件，不下载新内容
  --download  下载新内容（默认操作）
  --help, -h  显示此帮助
        """)
        return

    project_root = Path(__file__).resolve().parent.parent.parent
    from laws_database.config import load_config
    config = load_config(project_root)
    src = config["sources"]["fdw_qa"]
    scraper = FDWScraper(
        data_dir=project_root / src["data_dir"],
        base_url=src["base_url"],
        search_url=src["search_url"],
        delay_range=src.get("delay_range", [1, 3]),
    )

    if args.rename:
        scraper.rename_existing_files()
    else:
        scraper.download()


if __name__ == "__main__":
    main()
