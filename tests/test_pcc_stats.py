# -*- coding: utf-8 -*-
"""pcc_stats 统计收集与报告格式化的单元测试。"""

from laws_database.sources.pcc_stats import build_report, collect_stats


def _write_case(path, case_no):
    """写一个含「#### 案件信息」段的最小案例 md。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#### 案件信息\n{case_no} / x\n", encoding="utf-8")


class TestCollectStats:
    """collect_stats 计数与重复检测测试。"""

    def test_counts_md_and_subdirs(self, tmp_path):
        """应正确统计各分类 md 数与二级案由数。"""
        target = tmp_path / "kb"
        _write_case(target / "民事" / "借款合同纠纷" / "a.md", "2023-16-2-103-021")
        _write_case(target / "民事" / "侵权纠纷" / "b.md", "2024-11-2-103-001")
        # 未创建的分类应记 0
        stats = collect_stats(target)
        civil = next(c for c in stats["categories"] if c["code"] == "civil")
        assert civil["md"] == 2
        assert civil["subdirs"] == 2
        assert stats["total_md"] == 2
        assert stats["total_subdirs"] == 2

    def test_duplicate_detection(self, tmp_path):
        """同编号多个 md 应被识别为重复组。"""
        target = tmp_path / "kb"
        _write_case(target / "民事" / "借款合同纠纷" / "x.md", "2023-16-2-103-021")
        _write_case(target / "民事" / "侵权纠纷" / "y.md", "2023-16-2-103-021")
        stats = collect_stats(target)
        assert stats["unique_nos"] == 1
        assert stats["dup_groups"] == 1
        assert stats["dup_files"] == 2

    def test_no_duplicate_when_unique(self, tmp_path):
        """不同编号不应判为重复。"""
        target = tmp_path / "kb"
        _write_case(target / "民事" / "借款" / "a.md", "2023-16-2-103-021")
        _write_case(target / "民事" / "借款" / "b.md", "2024-11-2-103-001")
        stats = collect_stats(target)
        assert stats["dup_groups"] == 0
        assert stats["unique_nos"] == 2

    def test_known_nos_consistency(self, tmp_path):
        """应对比 known_case_nos 行数与 md 数。"""
        target = tmp_path / "kb"
        _write_case(target / "民事" / "借款" / "a.md", "2023-16-2-103-021")
        records = tmp_path / "records"
        records.mkdir()
        (records / "known_case_nos_civil.txt").write_text("2023-16-2-103-021\n", encoding="utf-8")
        stats = collect_stats(target, records)
        civil = next(c for c in stats["categories"] if c["code"] == "civil")
        assert civil["nos"] == 1
        assert stats["has_records"] is True

    def test_no_records_skips_consistency(self, tmp_path):
        """records_dir=None 时应跳过编号清单一致性（nos 为 None）。"""
        target = tmp_path / "kb"
        _write_case(target / "民事" / "借款" / "a.md", "2023-16-2-103-021")
        stats = collect_stats(target, records_dir=None)
        civil = next(c for c in stats["categories"] if c["code"] == "civil")
        assert civil["nos"] is None
        assert stats["has_records"] is False


class TestFormatReport:
    """format_report / build_report 报告输出测试。"""

    def test_report_contains_key_sections(self, tmp_path):
        """报告应含标题、分类名、重复检查等关键段落。"""
        target = tmp_path / "kb"
        _write_case(target / "民事" / "借款" / "a.md", "2023-16-2-103-021")
        report = build_report(target)
        assert "PCC 案例库统计概览" in report
        assert "民事" in report
        assert "重复检查" in report
        assert "无重复" in report

    def test_report_flags_inconsistency(self, tmp_path):
        """编号清单与 md 数不一致时，报告应标 ⚠ 并指出差额。"""
        target = tmp_path / "kb"
        _write_case(target / "民事" / "借款" / "a.md", "2023-16-2-103-021")
        records = tmp_path / "records"
        records.mkdir()
        # 清单 2 个编号，target 仅 1 个 md → 差 1
        (records / "known_case_nos_civil.txt").write_text(
            "2023-16-2-103-021\n2024-11-2-103-001\n", encoding="utf-8"
        )
        report = build_report(target, records)
        assert "⚠" in report
        assert "清单多1" in report  # 清单 2 个、md 1 个 → 清单多 1
