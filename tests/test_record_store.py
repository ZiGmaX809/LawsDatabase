# -*- coding: utf-8 -*-
"""record_store.RecordStore 与 add_records 的单元测试。"""

import json

import pytest

from laws_database.core.record_store import RecordStore, add_records


class TestRecordStoreTxt:
    """txt 格式读写测试。"""

    def test_load_nonexistent_returns_empty_set(self, tmp_path):
        """文件不存在时应返回空集合。"""
        store = RecordStore(tmp_path / "missing.txt", fmt="txt")
        assert store.load() == set()

    def test_save_and_reload_roundtrip(self, tmp_path):
        """保存后重新加载应得到相同集合。"""
        path = tmp_path / "rec.txt"
        store = RecordStore(path, fmt="txt")
        store.save_all({"a", "b", "c"})
        assert store.load() == {"a", "b", "c"}

    def test_txt_format_each_key_one_line(self, tmp_path):
        """txt 格式应为每行一个 key。"""
        path = tmp_path / "rec.txt"
        RecordStore(path, fmt="txt").save_all({"x", "y"})
        lines = set(path.read_text(encoding="utf-8").strip().split("\n"))
        assert lines == {"x", "y"}

    def test_load_skips_blank_lines(self, tmp_path):
        """加载时应跳过空行与纯空白行。"""
        path = tmp_path / "rec.txt"
        path.write_text("a\n\n  \nb\n", encoding="utf-8")
        assert RecordStore(path, fmt="txt").load() == {"a", "b"}

    def test_contains(self, tmp_path):
        """contains 应正确判断成员关系。"""
        path = tmp_path / "rec.txt"
        store = RecordStore(path, fmt="txt")
        store.save_all({"hello"})
        assert store.contains("hello") is True
        assert store.contains("world") is False


class TestRecordStoreJson:
    """json 格式读写测试（兼容 Laws 的 download_state.json）。"""

    def test_save_writes_downloaded_structure(self, tmp_path):
        """json 格式应写入 {"downloaded": [...], ...} 结构。"""
        path = tmp_path / "state.json"
        RecordStore(path, fmt="json").save_all({"bb1", "bb2"})
        data = json.loads(path.read_text(encoding="utf-8"))
        assert set(data["downloaded"]) == {"bb1", "bb2"}
        assert data["total_count"] == 2
        assert "last_update" in data

    def test_load_legacy_download_state_format(self, tmp_path):
        """应能读取 Laws 原有的 download_state.json 结构。"""
        path = tmp_path / "state.json"
        path.write_text(
            json.dumps({"downloaded": ["a", "b"], "last_update": "x"}),
            encoding="utf-8",
        )
        assert RecordStore(path, fmt="json").load() == {"a", "b"}

    def test_load_corrupt_json_returns_empty(self, tmp_path):
        """损坏的 json 文件应返回空集合而非抛错。"""
        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        assert RecordStore(path, fmt="json").load() == set()


class TestRecordStoreGeneral:
    """跨格式通用行为测试。"""

    def test_save_creates_parent_dir(self, tmp_path):
        """保存时应自动创建多级父目录。"""
        path = tmp_path / "nested" / "dir" / "rec.txt"
        RecordStore(path, fmt="txt").save_all({"a"})
        assert path.exists()
        assert RecordStore(path, fmt="txt").load() == {"a"}

    def test_invalid_format_raises(self):
        """不支持的格式应抛出 ValueError。"""
        with pytest.raises(ValueError):
            RecordStore("/tmp/whatever", fmt="yaml")


class TestAddRecords:
    """add_records 不可变风格测试。"""

    def test_returns_new_set_without_mutating_original(self):
        """应返回新集合，且不修改原集合（不可变）。"""
        original = {"a", "b"}
        result = add_records(original, "c")
        assert result == {"a", "b", "c"}
        assert original == {"a", "b"}

    def test_multiple_keys(self):
        """应支持一次添加多个键。"""
        assert add_records(set(), "x", "y", "z") == {"x", "y", "z"}

    def test_idempotent(self):
        """重复添加已存在的键应为幂等。"""
        assert add_records({"a"}, "a") == {"a"}
