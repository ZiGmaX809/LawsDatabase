#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PCC（人民法院案例库）案例库统计工具
====================================

对目标目录（target_dir）下已下载的案例 markdown 做全面统计：

1. 各一级分类（民事/刑事/行政/执行/国家赔偿）的 md 数与二级案由数；
2. 编号清单一致性：known_case_nos_<type>.txt 行数 vs 实际 md 数；
3. 重复检查：按案件编号（cpws_al_no）统计唯一编号数与重复组数。

可作为独立命令行工具运行，也被 court_cases 二级菜单（选项 7）调用。

用法：
  python3 laws_database/sources/pcc_stats.py                 # 读配置默认 target
  python3 laws_database/sources/pcc_stats.py --target PATH   # 指定 target
  python3 laws_database/sources/pcc_stats.py --no-records    # 跳过编号清单一致性
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

# 允许直接 `python3 laws_database/sources/pcc_stats.py` 运行：把项目根加入 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from laws_database.sources.court_cases import CASE_TYPES  # noqa: E402
from laws_database.sources.court_cases_batch import extract_case_no_from_md  # noqa: E402


def _disp_width(text: str) -> int:
    """估算字符串在终端的显示宽度（CJK 字符算 2 列）。"""
    return sum(2 if ord(ch) > 127 else 1 for ch in text)


def _pad_cn(text: str, width: int) -> str:
    """按显示宽度右补空格，使中英文混合的列能对齐。"""
    return text + " " * max(0, width - _disp_width(text))


def _count_known_nos(records_dir: Path, case_code: str) -> int | None:
    """读取某分类的 known_case_nos 行数；文件不存在返回 None。"""
    nos_file = records_dir / f"known_case_nos_{case_code}.txt"
    if not nos_file.exists():
        return None
    try:
        return sum(1 for line in nos_file.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return None


def collect_stats(target_dir, records_dir=None) -> dict:
    """收集统计信息，返回结构化字典。

    Args:
        target_dir: 案例库根目录（其下含「民事/刑事/...」一级分类）。
        records_dir: known_case_nos 所在目录；为 None 时跳过一致性检查。

    Returns:
        含 categories / total_md / total_subdirs / 唯一编号 / 重复组 的字典。
    """
    target = Path(target_dir)
    records = Path(records_dir) if records_dir else None

    categories = []
    total_md = 0
    total_subdirs = 0

    for code, (_sort_id, type_name) in CASE_TYPES.items():
        cat_dir = target / type_name
        md_count = 0
        subdir_count = 0
        if cat_dir.exists():
            md_count = sum(1 for _ in cat_dir.rglob("*.md"))
            subdir_count = sum(1 for d in cat_dir.iterdir() if d.is_dir())
        nos_count = _count_known_nos(records, code) if records else None
        categories.append({
            "code": code,
            "name": type_name,
            "md": md_count,
            "subdirs": subdir_count,
            "nos": nos_count,
        })
        total_md += md_count
        total_subdirs += subdir_count

    # 按案件编号做重复检查（跨所有分类）
    by_id: dict[str, list[Path]] = defaultdict(list)
    for cat in categories:
        cat_dir = target / cat["name"]
        if not cat_dir.exists():
            continue
        for md_file in cat_dir.rglob("*.md"):
            no = extract_case_no_from_md(md_file)
            if no:
                by_id[no].append(md_file)

    dup_groups = sum(1 for v in by_id.values() if len(v) > 1)
    dup_files = sum(len(v) for v in by_id.values() if len(v) > 1)

    return {
        "target": str(target),
        "categories": categories,
        "total_md": total_md,
        "total_subdirs": total_subdirs,
        "unique_nos": len(by_id),
        "dup_groups": dup_groups,
        "dup_files": dup_files,
        "has_records": records is not None,
    }


def format_report(stats: dict) -> str:
    """把统计字典格式化为可打印的文本报告。"""
    lines = []
    lines.append("=" * 60)
    lines.append("PCC 案例库统计概览")
    lines.append(f"目标目录: {stats['target']}")
    lines.append("=" * 60)

    # 表头
    header = f"{_pad_cn('分类', 10)}{'md 数':>8}{'二级案由':>10}"
    if stats["has_records"]:
        header += f"{'编号清单':>10}  一致性"
    lines.append(header)
    lines.append("-" * 60)

    for cat in stats["categories"]:
        row = f"{_pad_cn(cat['name'], 10)}{cat['md']:>8}{cat['subdirs']:>10}"
        if stats["has_records"]:
            if cat["nos"] is None:
                row += f"{'-':>10}  -"
            else:
                if cat["nos"] == cat["md"]:
                    consistency = "✓"
                else:
                    diff = cat["md"] - cat["nos"]
                    consistency = f"⚠ 清单缺{diff}" if diff > 0 else f"⚠ 清单多{-diff}"
                row += f"{cat['nos']:>10}  {consistency}"
        lines.append(row)

    lines.append("-" * 60)
    lines.append(f"{_pad_cn('合计', 10)}{stats['total_md']:>8}{stats['total_subdirs']:>10}")

    # 重复检查
    lines.append("")
    lines.append("重复检查（按案件编号 cpws_al_no）:")
    lines.append(f"  唯一编号数 : {stats['unique_nos']}")
    lines.append(f"  重复组数   : {stats['dup_groups']}")
    lines.append(f"  重复文件数 : {stats['dup_files']}")
    if stats["dup_groups"] == 0:
        lines.append("  ✓ 无重复")
    else:
        lines.append(f"  ⚠ 发现 {stats['dup_groups']} 组重复，建议运行 "
                     "dedup_pcc_cases.py --resolve-ambiguous 清理")
    lines.append("=" * 60)
    return "\n".join(lines)


def build_report(target_dir, records_dir=None) -> str:
    """一步完成收集 + 格式化，返回报告文本。"""
    return format_report(collect_stats(target_dir, records_dir))


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="PCC 案例库统计概览")
    parser.add_argument("--target", default=None, help="案例库根目录（默认读配置 target_dir）")
    parser.add_argument("--records", default=None, help="known_case_nos 所在目录（默认读配置）")
    parser.add_argument("--no-records", action="store_true", help="跳过编号清单一致性检查")
    args = parser.parse_args()

    # 从配置读取默认 target 与 records 目录
    from laws_database.config import load_config
    src = load_config(_PROJECT_ROOT)["sources"].get("court_cases", {})
    target = args.target or src.get("target_dir")
    records_default = str(_PROJECT_ROOT / src["data_dir"] / "downloaded_records")

    # --no-records 显式跳过编号清单一致性检查（records 置 None）
    records = None if args.no_records else (args.records or records_default)

    if not target:
        print("错误: 未指定目标目录，且配置中无 target_dir", file=sys.stderr)
        sys.exit(1)

    print(build_report(target, records))


if __name__ == "__main__":
    main()
