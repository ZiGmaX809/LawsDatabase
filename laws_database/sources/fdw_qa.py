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
import os
import sys
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
            if a_tag and a_tag.has_attr("href"):
                links.append(a_tag["href"])
        return links

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

    def save_to_markdown(self, links):
        """抓取并保存所有链接内容为 Markdown，基于下载记录增量去重。"""
        record_file = self.output_dir / ".downloaded_records.txt"
        downloaded_titles = self.record_store.load()
        self.logger.log(f"已加载 {len(downloaded_titles)} 条已下载记录")

        skipped = 0
        saved = 0
        failed = 0

        for i, link in enumerate(links):
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

            # 优先检查下载记录（内存操作，比文件系统快）
            if safe_title in downloaded_titles:
                print(f"[{i+1}/{len(links)}] 跳过已下载: {safe_title}.md")
                skipped += 1
                continue

            # 双重检查：记录无但文件存在（处理记录丢失情况），补回记录
            file_path = self.output_dir / f"{safe_title}.md"
            if file_path.exists():
                print(f"[{i+1}/{len(links)}] 文件已存在，补充记录: {safe_title}.md")
                downloaded_titles = downloaded_titles | {safe_title}
                self.record_store.save_all(downloaded_titles)
                skipped += 1
                continue

            txt_big = soup.find("div", class_="txt big")
            if not txt_big:
                self.logger.log(f"No content found for {full_url}")
                failed += 1
                continue

            txt_big_text = txt_big.get_text().strip()
            with open(file_path, "w", encoding="utf-8") as f:
                # "问题1："等转为二级标题
                lines = txt_big_text.split("\n")
                formatted_lines = []
                for line in lines:
                    line = line.lstrip()
                    if line.startswith("问题") and "：" in line:
                        formatted_lines.append(f"## {line}")
                    else:
                        formatted_lines.append(line)
                formatted_content = "\n".join(formatted_lines)
                f.write(f"# {title_text}\n\n{formatted_content}\n")

            # 即时持久化记录（不可变：返回新集合）
            downloaded_titles = downloaded_titles | {safe_title}
            self.record_store.save_all(downloaded_titles)

            print(f"[{i+1}/{len(links)}] 已保存: {file_path}")
            saved += 1

        self.logger.log(
            f"总结: 共处理 {len(links)} 个链接, 新下载 {saved} 个, 跳过 {skipped} 个, 失败 {failed} 个"
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
        """主流程：抓取搜索页 → 解析链接 → 下载保存。"""
        self.logger.log("开始爬取内容...")
        html = self.fetch_page(self.search_url)
        if not html:
            self.logger.log("Failed to fetch initial page")
            return
        links = self.parse_links(html)
        if not links:
            self.logger.log("No links found")
            return
        self.logger.log(f"找到 {len(links)} 个链接, 开始下载内容...")
        self.save_to_markdown(links)
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
