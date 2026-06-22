# -*- coding: utf-8 -*-
"""
PCC 批处理操作（mixin）
=======================

CourtDataProcessor 的批处理方法：案例详情下载与即时整理、批量整理、
目标目录统计。作为 mixin 拆分，使主文件保持在合理体积；方法体与原
``court_data_processor.py`` 实现一致（功能等价）。

这些方法依赖 CourtDataProcessor 提供的实例状态（self.base_dir / self.config /
self.logger / self.log 等），故以 mixin 形式由 ``CourtDataProcessor`` 继承。
"""

import json
import os
import random
import shutil
import time
from datetime import datetime
from pathlib import Path


class CourtBatchOps:
    """CourtDataProcessor 的批处理操作 mixin（不单独实例化）。"""

    def download_case_details(self):
        """
        下载案例详情并转为 Markdown，下载一个文件后立即整理到目标目录。

        Returns:
            bool/str: True(成功下载新文件), False(没有新文件或失败),
                     "limit_reached"(达到上限), "consecutive_failed"(连续失败)
        """
        self.log("开始下载案例详情...")

        if not self.config.get("target_dir"):
            self.log("错误: 未设置目标目录，无法整理文件")
            self.log("请重新运行并设置目标目录")
            return False

        json_dir = self.base_dir / self.config["json_dir"]
        markdown_dir = self.base_dir / self.config["markdown_dir"]
        type_name = self.config.get("case_type_name", "")
        target_dir = Path(self.config["target_dir"]) / type_name if type_name else Path(self.config["target_dir"])

        # 加载标题到分类的映射（用于实时整理）
        title_to_sort = {}
        for json_file in json_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "data" in data and "datas" in data["data"]:
                        for item in data["data"]["datas"]:
                            if "cpws_al_title" in item and "cpws_al_sort_name" in item:
                                title_to_sort[item["cpws_al_title"]] = item["cpws_al_sort_name"]
            except Exception as e:
                self.log(f"处理JSON文件 {json_file.name} 时出错: {str(e)}")

        if not title_to_sort:
            self.log("警告: 没有找到有效的标题到分类的映射，将无法整理文件")
        else:
            self.log(f"已加载 {len(title_to_sort)} 个标题到分类的映射")

        organized_files = self.load_organized_files_record()

        case_type_code = self.config.get("case_type_code", "civil")
        record_file = self.base_dir / "downloaded_records" / f"downloaded_records_{case_type_code}.txt"
        downloaded_files = set()
        if record_file.exists():
            with open(record_file, "r", encoding="utf-8") as f:
                downloaded_files = set(line.strip() for line in f)
            self.log(f"已下载记录文件存在，已跳过 {len(downloaded_files)} 个案例")

        json_files = [f for f in json_dir.glob("*.json")]
        if not json_files:
            self.log("没有找到JSON文件")
            return False

        success_count = 0
        skipped_count = 0
        organized_count = 0
        failed_count = 0
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 10

        for json_file in sorted(json_files, reverse=True):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "data" not in data or "datas" not in data["data"]:
                        continue
                    cases_list = data["data"]["datas"]
                    self.log(f"正在处理 {json_file.name}，共 {len(cases_list)} 个案例")

                    for idx, item in enumerate(cases_list, 1):
                        if "id" not in item:
                            continue
                        if item["id"][:10] in {x[:10] for x in downloaded_files}:
                            skipped_count += 1
                            continue

                        title = item.get("cpws_al_title", "未知标题")[:30]
                        self.log(f"[{idx}/{len(cases_list)}] 正在下载: {title}...")

                        case_data = self.fetch_case_content(item["id"])

                        if case_data and case_data.get("daily_limit_reached"):
                            self.log(f"已下载 {success_count} 个新案例，跳过 {skipped_count} 个已下载案例，失败 {failed_count} 个")
                            self.log(f"已整理 {organized_count} 个文件")
                            self.log("=" * 60)
                            self.log("达到下载上限，停止下载")
                            if organized_files:
                                self.save_organized_files_record(organized_files)
                            return "limit_reached"

                        if not case_data:
                            failed_count += 1
                            consecutive_failures += 1
                            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                                self.log(f"⚠️ 连续 {MAX_CONSECUTIVE_FAILURES} 次下载失败")
                                if organized_files:
                                    self.save_organized_files_record(organized_files)
                                return "consecutive_failed"
                            continue

                        consecutive_failures = 0

                        md_file_path = None
                        if self.save_as_markdown(case_data, markdown_dir):
                            success_count += 1
                            data_content = case_data.get("data", {}).get("data", {})
                            title = data_content.get("cpws_al_title", "")
                            if title:
                                safe_title = self.sanitize_filename(title)
                                md_file_path = markdown_dir / f"{safe_title}.md"

                                if title_to_sort and md_file_path.exists():
                                    self.log(f"正在整理: {safe_title}.md")
                                    if self.organize_single_file(md_file_path, title_to_sort, target_dir):
                                        organized_count += 1
                                        organized_files.add(safe_title)
                                        self.log(f"  已整理并记录: {safe_title}")
                                    try:
                                        md_file_path.unlink()
                                        self.log(f"  已删除源文件: {md_file_path.name}")
                                    except Exception as del_e:
                                        self.log(f"  删除源文件失败: {del_e}")

                            case_id_short = item["id"][:10]
                            with open(record_file, "a", encoding="utf-8") as f:
                                f.write(f"{case_id_short}\n")
                            downloaded_files.add(case_id_short)

                        time.sleep(random.uniform(*self.config["request_interval"]))
            except Exception as e:
                self.log(f"处理文件 {json_file.name} 时出错: {str(e)}")

        self.log(
            f"下载完成，共处理 {success_count} 个新案例，跳过 {skipped_count} 个已下载案例，"
            f"失败 {failed_count} 个，已整理 {organized_count} 个"
        )
        if organized_files:
            self.save_organized_files_record(organized_files)
        return success_count > 0

    def organize_single_file(self, md_file, title_to_sort, target_dir):
        """
        整理单个文件到分类目录。

        Args:
            md_file: markdown 文件路径。
            title_to_sort: 标题到分类的映射字典。
            target_dir: 目标目录。

        Returns:
            bool: 是否成功整理。
        """
        file_title = md_file.stem
        sort_name = None

        if file_title in title_to_sort:
            sort_name = title_to_sort[file_title]
        else:
            for title, sn in title_to_sort.items():
                clean_title = self.sanitize_filename(title)
                if file_title == clean_title or file_title in clean_title or clean_title in file_title:
                    sort_name = sn
                    break

        if sort_name:
            safe_sort = self.sanitize_filename(sort_name)
            dest_dir = target_dir / safe_sort
            os.makedirs(dest_dir, exist_ok=True)
            dest_file = dest_dir / md_file.name
            try:
                shutil.copy2(md_file, dest_file)
                self.log(f"  已整理: {md_file.name} -> {safe_sort}/")
                return True
            except Exception as e:
                self.log(f"  整理文件 {md_file.name} 时出错: {str(e)}")
                return False
        else:
            self.log(f"  未匹配到分类: {md_file.name}")
            return False

    def organize_case_files(self):
        """
        整理案例文件到分类目录。

        逻辑：加载已整理记录 → 从 JSON 提取标题到分类映射 → 扫描 markdown 目录 →
        按标题匹配复制到分类子目录 → 删除源文件 → 保存记录。
        """
        if not self.config.get("target_dir"):
            self.log("错误: 未设置目标目录（target_dir）")
            self.log("请使用 --organize 模式重新运行并输入目标目录地址")
            return False

        self.log("开始整理案例文件...")
        organized_files = self.load_organized_files_record()

        json_dir = self.base_dir / self.config["json_dir"]
        markdown_dir = self.base_dir / self.config["markdown_dir"]
        type_name = self.config.get("case_type_name", "")
        target_dir = Path(self.config["target_dir"]) / type_name if type_name else Path(self.config["target_dir"])

        if not json_dir.exists():
            self.log(f"JSON目录 {json_dir} 不存在")
            return False
        if not markdown_dir.exists():
            self.log(f"Markdown目录 {markdown_dir} 不存在")
            return False

        os.makedirs(target_dir, exist_ok=True)

        title_to_sort = {}
        for json_file in json_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "data" in data and "datas" in data["data"]:
                        for item in data["data"]["datas"]:
                            if "cpws_al_title" in item and "cpws_al_sort_name" in item:
                                title_to_sort[item["cpws_al_title"]] = item["cpws_al_sort_name"]
            except Exception as e:
                self.log(f"处理JSON文件 {json_file.name} 时出错: {str(e)}")

        if not title_to_sort:
            self.log("没有找到有效的标题到分类的映射")
            return False
        self.log(f"从JSON中提取了 {len(title_to_sort)} 个标题到分类的映射")

        md_files = list(markdown_dir.glob("*.md"))
        self.log(f"在markdown目录中找到 {len(md_files)} 个文件")
        if not md_files:
            self.log("markdown目录中没有文件需要整理")
            return False

        pending_files = [f for f in md_files if f.stem not in organized_files]
        skipped_count = len(md_files) - len(pending_files)
        if skipped_count > 0:
            self.log(f"跳过已整理的 {skipped_count} 个文件")
        if not pending_files:
            self.log("没有需要整理的新文件")
            return False
        self.log(f"待整理文件数: {len(pending_files)}")

        sort_dirs = {}
        success_count = 0
        unmatched_files = []
        newly_organized = set()

        for md_file in pending_files:
            file_title = md_file.stem
            sort_name = None

            if file_title in title_to_sort:
                sort_name = title_to_sort[file_title]
            else:
                for title, sn in title_to_sort.items():
                    clean_title = self.sanitize_filename(title)
                    if file_title == clean_title or file_title in clean_title or clean_title in file_title:
                        sort_name = sn
                        break

            if sort_name:
                safe_sort = self.sanitize_filename(sort_name)
                if safe_sort not in sort_dirs:
                    dest_dir = target_dir / safe_sort
                    os.makedirs(dest_dir, exist_ok=True)
                    sort_dirs[safe_sort] = dest_dir
                else:
                    dest_dir = sort_dirs[safe_sort]
                dest_file = dest_dir / md_file.name

                try:
                    if dest_file.exists():
                        if md_file.stat().st_mtime > dest_file.stat().st_mtime:
                            shutil.copy2(md_file, dest_file)
                            self.log(f"已更新: {md_file.name} -> {safe_sort}/")
                        else:
                            self.log(f"跳过（目标已存在且更新）: {md_file.name}")
                    else:
                        shutil.copy2(md_file, dest_file)
                        self.log(f"已整理: {md_file.name} -> {safe_sort}/")

                    newly_organized.add(md_file.stem)
                    success_count += 1

                    try:
                        md_file.unlink()
                        self.log(f"  已删除源文件: {md_file.name}")
                    except Exception as del_e:
                        self.log(f"  删除源文件失败: {del_e}")
                except Exception as e:
                    self.log(f"整理文件 {md_file.name} 时出错: {str(e)}")
            else:
                unmatched_files.append(md_file.name)

        if newly_organized:
            organized_files.update(newly_organized)
            self.save_organized_files_record(organized_files)

        if unmatched_files:
            self.log(f"未匹配到分类的文件 ({len(unmatched_files)} 个):")
            for name in unmatched_files[:10]:
                self.log(f"  - {name}")
            if len(unmatched_files) > 10:
                self.log(f"  ... 还有 {len(unmatched_files) - 10} 个文件")

        self.log(f"整理完成，跳过 {skipped_count} 个已整理文件，新处理 {success_count} 个文件")
        return success_count > 0

    def count_target_files(self):
        """统计目标文件夹中的文件数量并保存结果。"""
        if not self.config.get("target_dir"):
            self.log("错误: 未设置目标目录（target_dir）")
            self.log("请使用 --count 模式重新运行并输入目标目录地址")
            return None

        type_name = self.config.get("case_type_name", "")
        target_dir = Path(self.config["target_dir"]) / type_name if type_name else Path(self.config["target_dir"])

        if not target_dir.exists():
            self.log(f"目标目录不存在: {target_dir}")
            return None

        total_count = 0
        dir_stats = {}
        for root, dirs, files in os.walk(target_dir):
            file_count = len(files)
            rel_path = os.path.relpath(root, target_dir)
            if file_count > 0:
                dir_stats[rel_path] = file_count
                total_count += file_count

        update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_date = datetime.now().strftime("%Y-%m-%d")

        md_content = f"# 人民法院案例库统计\n\n## 统计信息\n\n"
        md_content += f"- **更新时间**: {update_time}\n- **总文件数**: {total_count} 个\n"
        md_content += f"- **分类数量**: {len(dir_stats)} 个\n\n## 分类统计\n\n按文件数量降序排列：\n\n"

        sorted_stats = sorted(dir_stats.items(), key=lambda x: x[1], reverse=True)
        for i, (dir_name, count) in enumerate(sorted_stats, 1):
            md_content += f"{i}. **{dir_name}**: {count} 个文件\n"

        stats_file = target_dir / f"统计信息_{update_date}.md"
        try:
            with open(stats_file, "w", encoding="utf-8") as f:
                f.write(md_content)
            self.log(f"统计结果已保存到: {stats_file}")
        except Exception as e:
            self.log(f"保存统计结果时出错: {str(e)}")

        self.log("=" * 60)
        self.log(f"目标目录统计: {target_dir}")
        self.log(f"更新时间: {update_time} | 总文件数: {total_count} | 分类数量: {len(dir_stats)}")
        for i, (dir_name, count) in enumerate(sorted_stats[:20], 1):
            self.log(f"{i:2d}. {dir_name}: {count} 个文件")
        if len(sorted_stats) > 20:
            self.log(f"... 还有 {len(sorted_stats) - 20} 个分类")
        self.log("=" * 60)
        return total_count
