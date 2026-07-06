#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PCC（人民法院案例库）Markdown 案例去重工具
==========================================

去重依据：md 文件「#### 案件信息」一节中的案例编号 cpws_al_no
（形如 2023-14-2-139-001，五段式「年-届-编-案由-序号」）。
同一编号存在多个 md 文件即视为重复。

保留规则：
  - 明确组（同编号下既有带「、」又有不带「、」的文件名）：保留带「、」的版本。
  - 边界组（同编号下文件名都带 / 都不带「、」，通常是同一案例被整理进了
    不同二级案由目录）：默认只报告不删；加 --resolve-ambiguous 后按回退链
    「带「、」优先 → 文件名更短 → mtime 更新 → 路径字节序最小」每组保留 1 个。
    路径字节序兜底可正确处理 Unicode 规范化（NFC/NFD）差异导致的「肉眼相同」
    但实际是两个文件的情形。

编号提取复用 laws_database.sources.court_cases_batch.extract_case_no_from_md，
与 rebuild_known_nos、下载判重同源，避免逻辑重复。

用法：
  python3 dedup_pcc_cases.py                                   # dry-run 扫描
  python3 dedup_pcc_cases.py --resolve-ambiguous               # 含边界组回退链解析
  python3 dedup_pcc_cases.py --resolve-ambiguous --report FILE # 输出完整清单
  python3 dedup_pcc_cases.py --resolve-ambiguous --execute     # 执行删除
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

# 复用项目内编号提取函数（与 rebuild / 下载判重同源）
from laws_database.sources.court_cases_batch import extract_case_no_from_md

# 默认目标目录（与 configs/pcc_config.local.json 的 target_dir 一致）
DEFAULT_TARGET = "/Users/zigma/Documents/律师材料/知识库/人民法院案例库"


def scan(target: Path):
    """扫描全部 md，返回 (所有文件, 按编号分组, 无编号文件)。"""
    all_files = sorted(target.rglob("*.md"))
    by_id: dict[str, list[Path]] = defaultdict(list)
    no_id: list[Path] = []
    for p in all_files:
        cid = extract_case_no_from_md(p)
        if cid:
            by_id[cid].append(p)
        else:
            no_id.append(p)
    return all_files, by_id, no_id


def top_category(target: Path, file_path: Path) -> str:
    """取一级分类名（target 直接子目录），用于分类统计。"""
    try:
        return file_path.relative_to(target).parts[0]
    except ValueError:
        return "?"


def pick_keeper(paths: list[Path]):
    """按回退链从同编号文件组选出唯一保留项。

    排序键（升序，第一项即保留）：
      1. 含「、」优先（带=0 / 无=1）
      2. 文件名 stem 更短优先
      3. mtime 更新优先
      4. 路径字节序最小（稳定兜底，兼容 Unicode 规范化差异）

    Returns:
        (keeper, to_delete) —— 保留项与待删除项列表。
    """
    def rank_key(p: Path):
        has_dunhao = 0 if "、" in p.stem else 1
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (has_dunhao, len(p.stem), -mtime, os.fsencode(str(p)))

    ordered = sorted(paths, key=rank_key)
    return ordered[0], ordered[1:]


def keeper_reason(keeper: Path) -> str:
    """生成保留依据的简短描述。"""
    dunhao = "带、「、」" if "、" in keeper.stem else "无「、」"
    return f"{dunhao}，文件名 {len(keeper.stem)} 字"


def build_plan(by_id: dict[str, list[Path]], resolve_ambiguous: bool = False):
    """生成删除计划。

    Returns:
        to_delete: 计划删除的文件列表
        explicit_groups: 明确组 [(cid, [keepers], [deleted])]
        ambiguous_groups: 边界组；resolve 时 (cid, keeper, [deleted], reason)，
                          未 resolve 时 (cid, None, [], "")
    """
    to_delete: list[Path] = []
    explicit_groups = []
    ambiguous_groups = []

    for cid, paths in by_id.items():
        if len(paths) < 2:
            continue
        with_d = [p for p in paths if "、" in p.stem]
        without_d = [p for p in paths if "、" not in p.stem]

        if with_d and without_d:
            # 明确：保留带顿号，删不带顿号
            explicit_groups.append((cid, sorted(with_d), sorted(without_d)))
            to_delete.extend(without_d)
        else:
            # 边界：全带或全不带
            if resolve_ambiguous:
                keeper, dels = pick_keeper(paths)
                ambiguous_groups.append((cid, keeper, dels, keeper_reason(keeper)))
                to_delete.extend(dels)
            else:
                ambiguous_groups.append((cid, None, [], ""))

    return to_delete, explicit_groups, ambiguous_groups


def print_summary(target, all_files, by_id, no_id, to_delete, explicit_groups, ambiguous_groups, resolve_ambiguous):
    """打印扫描摘要 + 待删除示例 + 边界组保留决策示例。"""
    print("=" * 60)
    print("PCC 去重扫描（dry-run，不会删除任何文件）")
    print(f"目标目录: {target}")
    if resolve_ambiguous:
        print("模式: 含边界组回退链解析（--resolve-ambiguous）")
    print("=" * 60)

    print(f"\nmd 文件总数          : {len(all_files)}")
    print(f"成功提取编号的文件数 : {sum(len(v) for v in by_id.values())}")
    print(f"未提取到编号的文件数 : {len(no_id)}")
    print(f"唯一编号数          : {len(by_id)}")

    print(f"\n>>> 明确重复组（带/无顿号混合）  : {len(explicit_groups)} 组")
    amb_note = "（已按回退链解析）" if resolve_ambiguous else "（未解析，加 --resolve-ambiguous 处理）"
    print(f">>> 边界重复组（全带/全不带顿号）: {len(ambiguous_groups)} 组 {amb_note}")
    print(f">>> 合计计划删除文件数            : {len(to_delete)}")

    if to_delete:
        cat_count: dict[str, int] = defaultdict(int)
        for p in to_delete:
            cat_count[top_category(target, p)] += 1
        print("\n--- 计划删除文件按一级分类 ---")
        for cat in sorted(cat_count):
            print(f"  {cat:<8}: {cat_count[cat]}")

        print("\n--- 待删除文件示例（最多 20 条，完整清单用 --report）---")
        for p in to_delete[:20]:
            print(f"  [删] {p.relative_to(target)}")

    # 边界组保留决策示例（让用户看清回退链如何抉择）
    resolved = [g for g in ambiguous_groups if g[1] is not None]
    if resolved:
        print("\n--- 边界组保留决策示例（最多 10 组）---")
        for cid, keeper, dels, reason in resolved[:10]:
            print(f"  {cid}  保留依据：{reason}")
            print(f"    [保留] {keeper.relative_to(target)}")
            for p in dels:
                print(f"    [删除] {p.relative_to(target)}")


def write_report(target, path, to_delete, explicit_groups, ambiguous_groups, resolve_ambiguous):
    """输出完整清单到文件，便于逐条审查。"""
    lines = [
        f"PCC 去重完整清单",
        f"目标目录: {target}",
        f"模式: {'含边界组回退链解析' if resolve_ambiguous else '仅明确组'}",
        f"计划删除总数: {len(to_delete)}\n",
    ]

    lines.append(f"\n=== 明确重复组（{len(explicit_groups)} 组，删无顿号保带顿号）===\n")
    for cid, keepers, deleted in explicit_groups:
        lines.append(f"# {cid}")
        for p in keepers:
            lines.append(f"  [保留] {p.relative_to(target)}")
        for p in deleted:
            lines.append(f"  [删除] {p.relative_to(target)}")
        lines.append("")

    lines.append(f"\n=== 边界重复组（{len(ambiguous_groups)} 组）===\n")
    for g in ambiguous_groups:
        if g[1] is not None:
            cid, keeper, dels, reason = g
            lines.append(f"# {cid}  （保留依据：{reason}）")
            lines.append(f"  [保留] {keeper.relative_to(target)}")
            for p in dels:
                lines.append(f"  [删除] {p.relative_to(target)}")
        else:
            lines.append(f"# {g[0]}（未解析）")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n完整清单已写入: {path}")


def execute_delete(to_delete: list[Path]):
    """真正执行删除。"""
    deleted, failed = 0, 0
    for p in to_delete:
        try:
            p.unlink()
            deleted += 1
        except Exception as e:
            print(f"删除失败: {p} ({e})")
            failed += 1
    print(f"\n删除完成: 成功 {deleted} 个，失败 {failed} 个")


def main():
    parser = argparse.ArgumentParser(description="PCC Markdown 案例去重")
    parser.add_argument("--target", default=DEFAULT_TARGET, help="目标目录")
    parser.add_argument("--resolve-ambiguous", action="store_true", help="对边界组按回退链自动保留1个")
    parser.add_argument("--execute", action="store_true", help="真正执行删除（默认仅扫描）")
    parser.add_argument("--report", help="输出完整清单到该文件")
    args = parser.parse_args()

    target = Path(args.target).expanduser()
    if not target.is_dir():
        print(f"错误: 目标目录不存在: {target}", file=sys.stderr)
        sys.exit(1)

    all_files, by_id, no_id = scan(target)
    to_delete, explicit_groups, ambiguous_groups = build_plan(by_id, resolve_ambiguous=args.resolve_ambiguous)

    print_summary(target, all_files, by_id, no_id, to_delete, explicit_groups, ambiguous_groups, args.resolve_ambiguous)

    if args.report:
        write_report(target, Path(args.report), to_delete, explicit_groups, ambiguous_groups, args.resolve_ambiguous)

    if args.execute:
        if not to_delete:
            print("\n没有可删除的文件，程序退出。")
            return
        print(f"\n即将删除 {len(to_delete)} 个文件，是否继续？")
        confirm = input("输入 yes 确认删除: ").strip().lower()
        if confirm == "yes":
            execute_delete(to_delete)
        else:
            print("已取消删除。")
    else:
        print("\n（dry-run 模式：未删除任何文件。加 --execute 执行删除。）")


if __name__ == "__main__":
    main()
