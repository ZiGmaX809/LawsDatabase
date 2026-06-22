# -*- coding: utf-8 -*-
"""
FLK 批处理操作（mixin）
=======================

FLKDownloader 的批处理方法：分类下载、批量转换、版本数据库初始化、
去重重命名、整理到知识库目录。作为 mixin 拆分，使主文件保持在合理体积；
方法体与原实现一致（功能等价）。

这些方法依赖 FLKDownloader 提供的实例状态（self.output_dir / self.session /
self.logger / self.downloaded_files / self.versions_db_file 等），故以 mixin
形式由 ``FLKDownloader`` 继承。LAW_CATEGORIES 在方法内延迟导入以避免循环引用。
"""

import json
import os
import random
import shutil
import time
from pathlib import Path
from typing import Dict, List

from laws_database.sources.flk_docx_converter import convert_docx_to_markdown
from laws_database.sources.law_versions_db import (
    LawVersionsDB,
    extract_base_name,
    extract_year,
)


class FLKBatchOps:
    """FLKDownloader 的批处理操作 mixin（不单独实例化，由 FLKDownloader 继承）。"""

    def convert_existing_docx(self, docx_dir: Path = None, md_dir: Path = None) -> Dict:
        """
        转换已下载的 docx 文件为 Markdown（保持与 docx 相同的目录结构）。

        Args:
            docx_dir: docx 文件目录，默认 output_dir/docx。
            md_dir: markdown 输出目录，默认 output_dir/markdown。

        Returns:
            处理统计信息。
        """
        if docx_dir is None:
            docx_dir = self.output_dir / "docx"
        if md_dir is None:
            md_dir = self.output_dir / "markdown"
        os.makedirs(md_dir, exist_ok=True)

        self.log(f"开始转换docx文件: {docx_dir}")
        stats = {"total": 0, "converted": 0, "skipped": 0, "failed": 0}

        docx_files = list(docx_dir.rglob("*.docx"))
        if not docx_files:
            self.log("没有找到docx文件")
            return stats
        self.log(f"找到 {len(docx_files)} 个docx文件")

        db = None
        if self.versions_db_file.exists():
            db = LawVersionsDB(str(self.versions_db_file), self.output_dir)

        for docx_file in docx_files:
            stats["total"] += 1
            rel_path = docx_file.relative_to(docx_dir)

            if len(rel_path.parts) >= 3:
                category_folder = rel_path.parts[0]
                law_type_folder = rel_path.parts[1]
            elif len(rel_path.parts) == 2:
                category_folder = rel_path.parts[0]
                law_type_folder = ""
            else:
                category_folder = ""
                law_type_folder = ""

            stem = docx_file.stem
            parts = stem.rsplit("_", 2)
            if len(parts) >= 2:
                title = parts[0]
                gbrq = parts[1]
                formatted_date = f"{gbrq[:4]}-{gbrq[4:6]}-{gbrq[6:8]}" if len(gbrq) == 8 else gbrq
            else:
                title = stem
                formatted_date = ""
            bbbs = parts[2] if len(parts) >= 3 else ""

            md_filename, renamed_existing = self.ensure_unique_md_filename(
                title, formatted_date, bbbs, category_folder, law_type_folder, db
            )
            md_file = (
                md_dir / category_folder / law_type_folder / f"{md_filename}.md"
                if law_type_folder
                else md_dir / category_folder / f"{md_filename}.md"
            )
            os.makedirs(md_file.parent, exist_ok=True)

            if md_file.exists() and not renamed_existing:
                stats["skipped"] += 1
                continue

            # 从 JSON 读取元数据
            json_dir = self.output_dir / "json" / "laws"
            json_file = None
            if len(rel_path.parts) >= 3:
                json_file = json_dir / rel_path.parts[0] / rel_path.parts[1] / f"{docx_file.stem}.json"
            elif len(rel_path.parts) == 2:
                json_file = json_dir / rel_path.parts[0] / f"{docx_file.stem}.json"
            if json_file is None or not json_file.exists():
                json_file = json_dir / f"{docx_file.stem}.json"
                if not json_file.exists():
                    for jf in json_dir.rglob(f"{docx_file.stem}.json"):
                        json_file = jf
                        break

            law_info = None
            if json_file and json_file.exists():
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        json_data = json.load(f)
                    json_title = json_data.get("title", title)
                    json_gbrq = json_data.get("gbrq", formatted_date)
                    base = extract_base_name(json_title)
                    if db and db.has_multiple_versions(base):
                        display_title = f"{base}（{extract_year(json_gbrq)}）"
                    else:
                        display_title = json_title
                    law_info = {
                        "title": display_title,
                        "gbrq": json_gbrq,
                        "sxrq": json_data.get("sxrq", formatted_date),
                        "zdjgName": json_data.get("zdjgName", ""),
                        "flxz": json_data.get("flxz", ""),
                        "bbbs": json_data.get("bbbs", ""),
                        "sxx": json_data.get("sxx", 0),
                    }
                    self.log(f"从JSON读取元数据: {title}")
                except Exception as e:
                    self.log(f"读取JSON失败: {e}，使用文件名解析")

            if law_info is None:
                base = extract_base_name(title)
                if db and db.has_multiple_versions(base):
                    display_title = f"{base}（{extract_year(formatted_date)}）"
                else:
                    display_title = title
                law_info = {
                    "title": display_title,
                    "gbrq": formatted_date,
                    "sxrq": formatted_date,
                    "zdjgName": "",
                    "flxz": "",
                    "bbbs": bbbs,
                    "sxx": 0,
                }

            if convert_docx_to_markdown(docx_file, md_file, law_info, self.logger):
                stats["converted"] += 1
                if db:
                    try:
                        md_rel_path = md_file.relative_to(self.output_dir)
                        db.register_law(
                            law_info.get("title", title),
                            law_info.get("gbrq", formatted_date),
                            law_info.get("bbbs", bbbs),
                            "",
                            str(md_rel_path).replace("\\", "/"),
                        )
                        db.save()
                    except (ValueError, Exception):
                        pass
            else:
                stats["failed"] += 1

            if self.max_delay > 0:
                time.sleep(max(self.min_delay, random.uniform(0, 0.1)))

        self.log(
            f"转换完成: 总计 {stats['total']}, 转换 {stats['converted']}, "
            f"跳过 {stats['skipped']}, 失败 {stats['failed']}"
        )
        return stats

    def process_category(self, category_key: str, max_pages: int = None, save_json_only: bool = False) -> Dict:
        from laws_database.sources.flk_laws import LAW_CATEGORIES
        """
        处理指定分类的法律下载。

        Args:
            category_key: 分类 key。
            max_pages: 最大页数，None 表示全部。
            save_json_only: 仅保存 JSON，不下载文件。

        Returns:
            处理统计信息。
        """
        category = LAW_CATEGORIES[category_key]
        self.log(f"开始处理分类: {category['name']}")
        stats = {"total": 0, "downloaded": 0, "skipped": 0, "failed": 0}

        page = 1
        while True:
            list_data = self.get_law_list(category_key, page)
            if not list_data:
                break

            rows = list_data.get("rows", [])
            if not rows:
                self.log(f"第{page}页无数据，停止")
                break

            for law in rows:
                stats["total"] += 1
                bbbs = law.get("bbbs") or ""

                if bbbs in self.downloaded_files:
                    stats["skipped"] += 1
                    continue

                detail = self.get_law_detail(bbbs)
                if not detail:
                    stats["failed"] += 1
                    continue

                self.save_law_info(law, detail, category_key)

                if save_json_only:
                    stats["downloaded"] += 1
                    self.downloaded_files.add(bbbs)
                    if stats["downloaded"] % 10 == 0:
                        self.save_state()
                    if self.max_delay > 0:
                        time.sleep(random.uniform(self.min_delay, min(self.max_delay, 1.5)))
                    continue

                oss_file = detail.get("ossFile", {})
                docx_path = oss_file.get("ossWordPath") or ""
                if not docx_path:
                    self.log(f"无docx文件路径: {law.get('title')}")
                    stats["failed"] += 1
                    continue

                download_url = self.get_download_url(docx_path)
                title = law.get("title", "未知")
                safe_title = self.sanitize_filename(title)
                gbrq = (law.get("gbrq") or "").replace("-", "")
                gbrq_formatted = law.get("gbrq", "")
                flxz = law.get("flxz", "未知类型")
                law_type_folder = self.get_law_type_folder(flxz)
                category_name = LAW_CATEGORIES[category_key]["name"]

                db = None
                if self.versions_db_file.exists():
                    db = LawVersionsDB(str(self.versions_db_file), self.output_dir)

                md_filename, renamed_existing = self.ensure_unique_md_filename(
                    title, gbrq_formatted, bbbs, category_name, law_type_folder, db
                )
                md_filename = f"{md_filename}.md"
                docx_filename = f"{safe_title}_{gbrq}_{bbbs[:10]}.docx"

                docx_output = self.output_dir / "docx" / category_name / law_type_folder / docx_filename
                md_output = self.output_dir / "markdown" / category_name / law_type_folder / md_filename
                os.makedirs(docx_output.parent, exist_ok=True)
                os.makedirs(md_output.parent, exist_ok=True)

                if self.download_docx(download_url, docx_output):
                    display_title = title
                    if renamed_existing or (db and db.has_multiple_versions(extract_base_name(title))):
                        display_title = f"{extract_base_name(title)}（{extract_year(gbrq_formatted)}）"

                    law_info = {
                        "title": display_title,
                        "bbbs": bbbs,
                        "gbrq": gbrq_formatted,
                        "sxrq": law.get("sxrq") or "",
                        "zdjgName": law.get("zdjgName") or "",
                        "flxz": law.get("flxz") or "未知类型",
                        "sxx": law.get("sxx", 0),
                    }

                    if convert_docx_to_markdown(docx_output, md_output, law_info, self.logger):
                        stats["downloaded"] += 1
                        self.downloaded_files.add(bbbs)

                        if db:
                            try:
                                md_rel_path = md_output.relative_to(self.output_dir)
                                db.register_law(
                                    title, gbrq_formatted, bbbs,
                                    f"docx/{category_name}/{law_type_folder}/{docx_filename}",
                                    str(md_rel_path).replace("\\", "/"),
                                )
                            except ValueError:
                                pass
                            db.save()

                        if stats["downloaded"] % 10 == 0:
                            self.save_state()
                    else:
                        self.log(f"转换失败，删除文件以便重试: {docx_output.name}")
                        try:
                            docx_output.unlink()
                        except Exception:
                            pass
                        stats["failed"] += 1

                if self.max_delay > 0:
                    time.sleep(random.uniform(self.min_delay, self.max_delay))

            if len(rows) < self.page_size:
                break
            if max_pages and page >= max_pages:
                break
            if page >= 1000:
                self.log("达到最大页数限制，停止")
                break

            page += 1
            if self.max_delay > 0:
                time.sleep(random.uniform(self.min_delay, min(self.max_delay * 2, 4)))

        self.save_state()
        self.log(
            f"分类 {category['name']} 处理完成: 总计 {stats['total']}, "
            f"下载 {stats['downloaded']}, 跳过 {stats['skipped']}, 失败 {stats['failed']}"
        )
        return stats

    def process_all(self, categories: List[str] = None) -> Dict:
        from laws_database.sources.flk_laws import LAW_CATEGORIES
        """处理所有或指定分类。"""
        if categories is None:
            categories = list(LAW_CATEGORIES.keys())

        total_stats = {"categories": len(categories), "total": 0, "downloaded": 0, "skipped": 0, "failed": 0}
        for category_key in categories:
            stats = self.process_category(category_key)
            for key in ["total", "downloaded", "skipped", "failed"]:
                total_stats[key] += stats.get(key, 0)

        self.log(
            f"全部处理完成: 总计 {total_stats['total']}, "
            f"下载 {total_stats['downloaded']}, 跳过 {total_stats['skipped']}, 失败 {total_stats['failed']}"
        )
        return total_stats

    def init_law_versions_db(self, db_path: str = None) -> Dict:
        """
        初始化法律版本数据库（扫描所有 JSON 文件建立索引）。

        Args:
            db_path: 数据库文件路径，默认使用 versions_db_file。
        """
        if db_path is None:
            db_path = self.versions_db_file

        self.log(f"开始初始化法律版本数据库: {db_path}")
        db = LawVersionsDB(str(db_path), self.output_dir)

        json_dir = self.output_dir / "json" / "laws"
        if not json_dir.exists():
            self.log(f"JSON 目录不存在: {json_dir}")
            return {"error": "JSON 目录不存在"}

        stats = {"total_scanned": 0, "registered": 0, "skipped": 0, "errors": 0}
        json_files = list(json_dir.rglob("*.json"))
        self.log(f"找到 {len(json_files)} 个 JSON 文件")

        for json_file in json_files:
            stats["total_scanned"] += 1
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                title = data.get("title", "")
                gbrq = data.get("gbrq", "")
                bbbs = data.get("bbbs", "")
                if not title or not bbbs:
                    stats["skipped"] += 1
                    continue

                try:
                    rel_path = json_file.relative_to(self.output_dir)
                    file_path = str(rel_path).replace("\\", "/")
                except ValueError:
                    file_path = str(json_file)

                md_path = ""
                json_stem = json_file.stem
                md_dir = self.output_dir / "markdown"
                if md_dir.exists():
                    for md_file in md_dir.rglob(f"{json_stem}.md"):
                        try:
                            md_rel = md_file.relative_to(self.output_dir)
                            md_path = str(md_rel).replace("\\", "/")
                            break
                        except ValueError:
                            pass

                db.register_law(title, gbrq, bbbs, file_path, md_path)
                stats["registered"] += 1
            except Exception as e:
                self.log(f"处理 JSON 文件失败 {json_file.name}: {e}")
                stats["errors"] += 1

        if db.save():
            self.log(f"数据库已保存: {db_path}")
            statistics = db.data.get("statistics", {})
            self.log(
                f"统计: 唯一法律 {statistics.get('total_unique_laws', 0)}, "
                f"总版本数 {statistics.get('total_versions', 0)}, "
                f"有重复 {statistics.get('with_duplicates', 0)}"
            )
        else:
            self.log("保存数据库失败")
            stats["errors"] += 1

        self.log(
            f"初始化完成: 扫描 {stats['total_scanned']}, 注册 {stats['registered']}, "
            f"跳过 {stats['skipped']}, 错误 {stats['errors']}"
        )
        return stats

    def deduplicate_markdown_files(self, db_path: str = None, dry_run: bool = False, force: bool = False) -> Dict:
        """
        重命名重复法律的 Markdown 文件（为多版本法律添加年份后缀）。

        Args:
            db_path: 数据库文件路径，默认 versions_db_file。
            dry_run: 预览模式，不实际执行。
            force: 强制处理所有文件，包括已处理的。
        """
        if db_path is None:
            db_path = self.versions_db_file

        self.log(f"开始{'预览' if dry_run else '处理'} Markdown 文件去重: {db_path}")
        db = LawVersionsDB(str(db_path), self.output_dir)
        stats = {
            "total_laws": 0, "with_duplicates": 0, "files_to_rename": 0,
            "renamed": 0, "skipped": 0, "errors": 0,
        }

        laws = db.data.get("laws", {})
        stats["total_laws"] = len(laws)

        for base_name, law_data in laws.items():
            if not law_data.get("has_multiple_versions", False):
                continue
            stats["with_duplicates"] += 1
            versions = law_data.get("versions", [])

            for version in versions:
                if version.get("processed", False) and not force:
                    stats["skipped"] += 1
                    continue

                md_path = version.get("md_path", "")
                if not md_path:
                    continue

                full_md_path = self.output_dir / md_path
                if not full_md_path.exists():
                    stats["skipped"] += 1
                    continue

                current_name = full_md_path.stem
                year = version.get("year", "")
                expected_name = f"{base_name}（{year}）"

                if current_name == expected_name:
                    if not force:
                        db.mark_processed(base_name, version.get("bbbs", ""))
                    stats["skipped"] += 1
                    continue

                stats["files_to_rename"] += 1
                new_md_name = f"{expected_name}.md"
                new_md_path = full_md_path.parent / new_md_name

                if dry_run:
                    self.log(f"[预览] {md_path} -> {new_md_name}")
                    stats["renamed"] += 1
                else:
                    try:
                        full_md_path.rename(new_md_path)
                        self._update_markdown_title(new_md_path, expected_name)
                        try:
                            new_rel_path = new_md_path.relative_to(self.output_dir)
                            version["md_path"] = str(new_rel_path).replace("\\", "/")
                            version["display_name"] = expected_name
                        except ValueError:
                            pass
                        version["processed"] = True
                        self.log(f"已重命名: {md_path} -> {new_md_name}")
                        stats["renamed"] += 1
                    except Exception as e:
                        self.log(f"重命名失败 {md_path}: {e}")
                        stats["errors"] += 1

        if not dry_run and stats["renamed"] > 0:
            db.save()

        self.log(
            f"{'预览' if dry_run else '处理'}完成: 法律 {stats['total_laws']}, "
            f"有重复 {stats['with_duplicates']}, 需处理 {stats['files_to_rename']}, "
            f"{'预览' if dry_run else '已处理'} {stats['renamed']}, 跳过 {stats['skipped']}, 错误 {stats['errors']}"
        )
        return stats

    def _update_markdown_title(self, md_path: Path, new_title: str):
        """更新 Markdown 文件的第一个标题。"""
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if line.strip().startswith("#"):
                    lines[i] = f"# {new_title}"
                    break
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception as e:
            self.log(f"更新 Markdown 标题失败 {md_path.name}: {e}")

    def organize_markdown_files(self, dry_run: bool = False) -> Dict:
        """
        整理 Markdown 文件到 organized_dir（镜像复制，保留源文件）。

        从原 ``Config.organize_markdown_files`` 迁移。遍历 markdown 目录的所有文件，
        按相对路径镜像复制到 organized_dir。

        Args:
            dry_run: 预览模式。

        Returns:
            操作统计信息。
        """
        if not self.organized_dir:
            self.log("未设置整理目录，跳过整理")
            return {"error": "未设置整理目录"}

        source_dir = self.output_dir / "markdown"
        if not source_dir.exists():
            return {"error": "markdown 源目录不存在"}

        stats = {"dirs_created": 0, "files_copied": 0, "errors": []}
        self.log(f"{'[预览] ' if dry_run else ''}整理 Markdown: {source_dir} -> {self.organized_dir}")

        for item in source_dir.rglob("*"):
            if not item.is_file():
                continue
            try:
                rel_path = item.relative_to(source_dir)
                dest_path = self.organized_dir / rel_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)

                if dry_run:
                    self.log(f"[预览] {rel_path}")
                    stats["files_copied"] += 1
                else:
                    try:
                        shutil.copy2(item, dest_path)
                        stats["files_copied"] += 1
                        if stats["files_copied"] % 100 == 0:
                            self.log(f"已复制 {stats['files_copied']} 个文件...")
                    except Exception as e:
                        stats["errors"].append(f"{rel_path}: {e}")
            except ValueError:
                stats["errors"].append(f"{item.name}: 无法计算相对路径")

        if not dry_run:
            self.log(f"整理完成: 共复制 {stats['files_copied']} 个文件")
            if stats["errors"]:
                self.log(f"警告: {len(stats['errors'])} 个文件复制失败")
        return stats


