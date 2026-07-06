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
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


# 案件编号 cpws_al_no 五段式：年-届-编-案由-序号（各段位数有差异，
# 如 2023-14-2-139-001 / 2026-01-2-108-001），故用宽松位数匹配。
CASE_NO_PATTERN = re.compile(r"(\d{4}-\d{1,2}-\d{1,2}-\d{1,4}-\d{1,4})")
# 「案件信息」标题行（markdown 任意层级标题），案件编号紧随其后。
CASE_INFO_HEADER = re.compile(r"^#+\s*案件信息")


def extract_case_no_from_md(md_path) -> Optional[str]:
    """从案例 markdown 提取案件编号 cpws_al_no（如 ``2023-14-2-139-001``）。

    编号位于「#### 案件信息」标题之后若干行的首字段，源自详情 API 的
    ``cpws_al_infos``。优先解析该段；若文件缺该标题则退化为全文检索首个
    五段式编号——该格式足够独特，误匹配概率极低。

    已在全部 3632 个存量 md 上验证 100% 命中。去重脚本、rebuild_known_nos、
    下载判重三处共用本函数，避免逻辑重复。

    Args:
        md_path: markdown 文件路径（str 或 Path）。

    Returns:
        编号字符串；读取失败或无法提取时返回 None。
    """
    try:
        text = Path(md_path).read_text(encoding="utf-8")
    except OSError:
        return None

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if CASE_INFO_HEADER.match(line.strip()):
            # 标题后 4 行内取首个编号
            for j in range(i + 1, min(i + 5, len(lines))):
                m = CASE_NO_PATTERN.search(lines[j])
                if m:
                    return m.group(1)
            break  # 找到「案件信息」标题但无编号，不再兜底，避免误匹配正文

    # 兜底：全文首个编号（无「案件信息」标题时）
    m = CASE_NO_PATTERN.search(text)
    return m.group(1) if m else None


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

        # 去重基准（ground truth）：目标目录已入库案例的**详情编号**(md_no)集合。
        # 用 md 内嵌编号（详情 API）而非文件名标题判重——标题会因顿号写法、案由目录变化
        # 而不一致；且列表 API 与详情 API 的 cpws_al_no 可能不同，以 md 内嵌的详情编号
        # 为权威（与 rebuild_known_nos / pcc_stats / dedup_pcc_cases 同源）。
        # 一次性递归扫描、O(1) 查找；下载成功后即时追加（见下方），同次运行内也不再重下。
        organized_case_nos = set()
        if target_dir.exists():
            for md_file in target_dir.rglob("*.md"):
                no = extract_case_no_from_md(md_file)
                if no:
                    organized_case_nos.add(no)
        self.log(f"目标目录已入库 {len(organized_case_nos)} 个案件编号（去重基准）")

        known_nos = self.load_known_nos()

        # 自愈：把 known_case_nos 收敛到 target 实际编号（剔除幽灵）。
        # 只删不增，**立即落盘**——不能依赖 _flush_known_nos（它在本次无新下载时早退，
        # 而"全量已完成、无新案"恰是常见状态，那样自愈永不生效）。
        # organized_case_nos 为空（target 未设置/为空）时保守不清空，防配置误删。
        if organized_case_nos:
            pruned = len(known_nos)
            known_nos &= organized_case_nos
            pruned -= len(known_nos)
            if pruned > 0:
                self.save_known_nos(known_nos)
                self.log(f"自愈: 清理 {pruned} 个幽灵编号（target 无对应 md）")

        # 实际判重集合：md_no ∪ 其对应的 list_no（别名展开）。
        # 列表 API 返回 list_no，对编号不一致的案件需展开后才能命中跳过，
        # 否则每次增量都会被当成新案重复下载。effective_case_nos 同时用于
        # 跳过下载（含本次 run 内新增），fetch_case_list 也用同源（_effective_known_nos）。
        effective_case_nos = self._effective_known_nos(organized_case_nos)

        # known_case_nos 只收集"本次下载成功且整理入库"的 md_no，退出时统一写回
        # （见 _flush_known_nos）。仅在整理成功（md 已落 target）时收集，
        # 保证 known_case_nos ⊆ target 实际编号，杜绝幽灵。
        newly_downloaded_nos = set()

        # 本次发现的 list_no→md_no 别名，退出时统一写回 case_no_aliases（见 _flush_aliases）。
        aliases = self.load_aliases()
        aliases_dirty = False

        json_files = [f for f in json_dir.glob("*.json")]
        if not json_files:
            self.log("没有找到JSON文件")
            return False

        success_count = 0
        skipped_count = 0
        organized_count = 0
        failed_count = 0
        save_failed_count = 0  # 详情保存失败（标题缺失等），与 fetch 失败区分
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

                        title = item.get("cpws_al_title", "")
                        case_no = item.get("cpws_al_no", "").strip()

                        # 已下载判据：案件编号（list_no）已在实际判重集中
                        # （md_no 或其对应别名 list_no）。编号缺失时不跳过——
                        # 无法判重则正常下载，避免漏抓。
                        if case_no and case_no in effective_case_nos:
                            skipped_count += 1
                            continue

                        safe_title = self.sanitize_filename(title) if title else ""

                        disp_title = title[:30] if title else "未知标题"
                        self.log(f"[{idx}/{len(cases_list)}] 正在下载: {disp_title}...")

                        case_data = self.fetch_case_content(item["id"])

                        if case_data and case_data.get("daily_limit_reached"):
                            self.log(f"已下载 {success_count} 个新案例，跳过 {skipped_count} 个已下载案例，失败 {failed_count} 个，详情缺失 {save_failed_count} 个")
                            self.log(f"已整理 {organized_count} 个文件")
                            self.log("=" * 60)
                            self.log("达到下载上限，停止下载")
                            if organized_files:
                                self.save_organized_files_record(organized_files)
                            self._flush_known_nos(known_nos, newly_downloaded_nos)
                            self._flush_aliases(aliases, aliases_dirty)
                            return "limit_reached"

                        if not case_data:
                            failed_count += 1
                            consecutive_failures += 1
                            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                                self.log(f"⚠️ 连续 {MAX_CONSECUTIVE_FAILURES} 次下载失败")
                                if organized_files:
                                    self.save_organized_files_record(organized_files)
                                self._flush_known_nos(known_nos, newly_downloaded_nos)
                                self._flush_aliases(aliases, aliases_dirty)
                                return "consecutive_failed"
                            continue

                        consecutive_failures = 0

                        md_file_path = None
                        if self.save_as_markdown(case_data, markdown_dir):
                            success_count += 1
                            organize_ok = False
                            md_no = None
                            persist_no = case_no  # 默认回退用 list_no；提取到 md_no 则覆盖
                            data_content = case_data.get("data", {}).get("data", {})
                            title = data_content.get("cpws_al_title", "")
                            if title:
                                safe_title = self.sanitize_filename(title)
                                md_file_path = markdown_dir / f"{safe_title}.md"

                                # 整理前从 md 提取详情编号（md_no，权威）——这是
                                # known_case_nos 应记录的编号（与 rebuild/stats 同源）。
                                # 必须在 unlink 前提取；提取失败回退 list 的 case_no。
                                if md_file_path.exists():
                                    md_no = extract_case_no_from_md(md_file_path)
                                    if md_no:
                                        persist_no = md_no

                                if title_to_sort and md_file_path.exists():
                                    self.log(f"正在整理: {safe_title}.md")
                                    organize_ok = self.organize_single_file(
                                        md_file_path, title_to_sort, target_dir
                                    )
                                    if organize_ok:
                                        organized_count += 1
                                        organized_files.add(safe_title)
                                        self.log(f"  已整理并记录: {safe_title}")
                                        # 仅在整理成功后删源文件（对齐 organize_case_files
                                        # 批量整理的写法）；失败则保留在 markdown_dir，
                                        # 由"仅整理"流程（菜单选项 3）重试。
                                        try:
                                            md_file_path.unlink()
                                            self.log(f"  已删除源文件: {md_file_path.name}")
                                        except Exception as del_e:
                                            self.log(f"  删除源文件失败: {del_e}")
                                    else:
                                        self.log(
                                            f"  ⚠ 整理失败，保留源文件待重试: {md_file_path.name}"
                                        )

                            # 只在整理成功（md 已落 target）时记录编号——
                            # 保证 known_case_nos ⊆ target 实际编号，从定义上杜绝幽灵。
                            if organize_ok and persist_no:
                                newly_downloaded_nos.add(persist_no)
                                organized_case_nos.add(persist_no)  # 纯 md_no 集（自愈用）
                                effective_case_nos.add(persist_no)
                                # 内存双键：list_no 也并入判重集，避免同次 run 内该案
                                # 在多个 JSON 文件（initial + incremental_*）里被重复下载。
                                if case_no and case_no != persist_no:
                                    effective_case_nos.add(case_no)
                                # 编号不一致 → 记录 list_no→md_no 别名（持久化），
                                # 供后续 run 的 fetch/download 识别 list_no，消除重复下载。
                                if case_no and md_no and case_no != md_no:
                                    if aliases.get(case_no) != md_no:
                                        aliases[case_no] = md_no
                                        aliases_dirty = True
                        else:
                            # 详情保存失败（多为标题缺失，已在 save_as_markdown 内告警）；
                            # 与 fetch 失败分开计数，便于汇总识别"死案例"。
                            save_failed_count += 1

                        time.sleep(random.uniform(*self.config["request_interval"]))
            except Exception as e:
                self.log(f"处理文件 {json_file.name} 时出错: {str(e)}")

        self.log(
            f"下载完成，共处理 {success_count} 个新案例，跳过 {skipped_count} 个已下载案例，"
            f"失败 {failed_count} 个，详情缺失 {save_failed_count} 个，已整理 {organized_count} 个"
        )
        if organized_files:
            self.save_organized_files_record(organized_files)
        self._flush_known_nos(known_nos, newly_downloaded_nos)
        self._flush_aliases(aliases, aliases_dirty)
        return success_count > 0

    def _flush_known_nos(self, known_nos, newly_downloaded_nos):
        """
        把本次下载成功的新案件编号追加到 known_case_nos 并落盘。

        仅当有新增时才写，配合 download_case_details 的三条退出路径（上限/连续失败/正常结束）
        调用，确保"下载成功"的案例才被标记"已知"。

        注意：此处 newly_downloaded_nos 只含 md_no（详情编号，整理成功后才收集），
        不含 list_no——故 known_case_nos 始终为纯 md_no 集合，与 target 目录扫描一致。
        """
        if not newly_downloaded_nos:
            return
        known_nos.update(newly_downloaded_nos)
        self.save_known_nos(known_nos)

    def _effective_known_nos(self, ground_truth_md_nos: set) -> set:
        """返回"实际可用于判重的编号集合" = target 详情编号 ∪ 其对应的列表编号。

        known_case_nos / organized_case_nos 只含 md 内嵌的详情编号（md_no，权威）。
        但列表 API 返回的是 list_no，对编号不一致的案件（list_no≠md_no）会漏判重→
        每次增量被重复下载。这里加载别名映射，把"其 md_no 已在 ground_truth 中"的
        list_no 也并入，使 fetch（新案检测）与 download（跳过下载）共用同一判重集，
        消除双权威源。

        Args:
            ground_truth_md_nos: target 目录扫描出的详情编号集合（md_no）。

        Returns:
            扩展后的编号集合（md_no ∪ 有效 list_no）。
        """
        effective = set(ground_truth_md_nos)
        aliases = self.load_aliases()
        for list_no, md_no in aliases.items():
            if md_no in ground_truth_md_nos:
                effective.add(list_no)
        return effective

    def _flush_aliases(self, aliases: dict, aliases_dirty: bool):
        """有变更时把 list_no→md_no 别名落盘。

        配合 download_case_details 的三条退出路径（上限/连续失败/正常结束）调用，
        确保本次发现的编号不一致关系被持久化，供后续 run 的 fetch/download 识别。
        """
        if aliases_dirty:
            self.save_aliases(aliases)

    def _resolve_dest_filename(self, src_md: Path, dest_dir: Path) -> Path:
        """确定整理目标文件名，避免同名不同编号案例互相覆盖。

        默认目标为 ``dest_dir / src_md.name``。若该文件已存在且与 src 的案件
        编号**不同**（脱敏标题撞车的不同案例，如多个「甲公司与乙公司执行监督案」），
        则在文件名追加 src 编号区分，如 ``某案_2023-17-5-203-024.md``；
        同编号（重试/更新）或无法判定编号时保持原名，交由调用方按 mtime 等策略
        覆盖/跳过。

        Args:
            src_md: 源 markdown 文件。
            dest_dir: 目标分类目录。

        Returns:
            最终目标文件路径（必要时已追加编号后缀）。
        """
        dest_file = dest_dir / src_md.name
        if not dest_file.exists():
            return dest_file
        src_no = extract_case_no_from_md(src_md)
        dst_no = extract_case_no_from_md(dest_file)
        # 同名但编号不同 → 不同案例，追加编号避免覆盖
        if src_no and dst_no and src_no != dst_no:
            return dest_dir / f"{src_md.stem}_{src_no}.md"
        return dest_file

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
            dest_file = self._resolve_dest_filename(md_file, dest_dir)
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
                dest_file = self._resolve_dest_filename(md_file, dest_dir)

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

    def rebuild_known_nos(self) -> dict:
        """从目标目录已下载的 md 重建案件编号清单（known_case_nos）。

        扫描 ``target_dir/<type_name>`` 下所有 ``*.md``，用
        :func:`extract_case_no_from_md` 提取编号，全量覆盖写回
        ``known_case_nos_<type>.txt``。用于去重清理后、或手工增删文件后，
        让下载判重的权威编号清单与磁盘实际保持一致——这是「编号单一权威源」
        的重建入口。

        无编号的 md（如统计信息文件）会被自动忽略，不计入清单。

        Returns:
            ``{"count": 唯一编号数, "scanned": 扫描的 md 数}``；未设置
            target_dir 或目录不存在时返回空字典。
        """
        if not self.config.get("target_dir"):
            self.log("错误: 未设置目标目录（target_dir），请先设置目标目录")
            return {}
        type_name = self.config.get("case_type_name", "")
        target_dir = (
            Path(self.config["target_dir"]) / type_name
            if type_name
            else Path(self.config["target_dir"])
        )
        if not target_dir.exists():
            self.log(f"目标目录不存在: {target_dir}")
            return {}

        self.log(f"开始重建编号清单: {target_dir}")
        nos = set()
        scanned = 0
        for md_file in target_dir.rglob("*.md"):
            scanned += 1
            no = extract_case_no_from_md(md_file)
            if no:
                nos.add(no)

        self.save_known_nos(nos)
        self.log(
            f"重建完成: 扫描 {scanned} 个 md，提取 {len(nos)} 个唯一编号"
            f" -> {self.get_known_nos_file_path().name}"
        )
        return {"count": len(nos), "scanned": scanned}

    def rebuild_organized_files(self) -> dict:
        """从 target 目录已整理的 md 重建 organized_files 记录。

        扫描 ``target_dir/<type_name>`` 下所有 ``*.md``，收集文件名 stem 全量覆盖
        写回 ``organized_files_<type>.txt``。该记录是 ``organize_case_files``
        （菜单选项 3）用来跳过"中间目录里已整理过的文件"的辅助记录，原本为
        追加式累积、rebuild/重整理后不会与 target 自动同步（曾出现 target 已有
        上千文件而记录仅几百的偏差）。本方法让它与 target 实际文件重新对齐，
        让"仅整理"功能的跳过判断更准。

        无编号的 md（如统计信息文件）其 stem 也会被收集——记录的是"文件名"
        而非"编号"，与 organized_files 的原始语义一致。

        Returns:
            ``{"count": 唯一 stem 数, "scanned": 扫描的 md 数}``；未设置
            target_dir 或目录不存在时返回空字典。
        """
        if not self.config.get("target_dir"):
            self.log("错误: 未设置目标目录（target_dir），请先设置目标目录")
            return {}
        type_name = self.config.get("case_type_name", "")
        target_dir = (
            Path(self.config["target_dir"]) / type_name
            if type_name
            else Path(self.config["target_dir"])
        )
        if not target_dir.exists():
            self.log(f"目标目录不存在: {target_dir}")
            return {}

        self.log(f"开始重建已整理文件记录: {target_dir}")
        stems = set()
        scanned = 0
        for md_file in target_dir.rglob("*.md"):
            scanned += 1
            stems.add(md_file.stem)

        self.save_organized_files_record(stems)
        self.log(
            f"重建完成: 扫描 {scanned} 个 md，提取 {len(stems)} 个文件名"
            f" -> {self.get_organized_files_record_path().name}"
        )
        return {"count": len(stems), "scanned": scanned}
