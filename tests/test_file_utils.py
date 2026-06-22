# -*- coding: utf-8 -*-
"""file_utils.sanitize_filename 的单元测试。"""

from laws_database.core.file_utils import sanitize_filename


class TestSanitizeFilename:
    """sanitize_filename 行为测试。"""

    def test_normal_name_unchanged(self):
        """正常文件名（含中文括号）应保持不变。"""
        assert sanitize_filename("法答网精选答问（第三批）") == "法答网精选答问（第三批）"

    def test_none_returns_placeholder(self):
        """None 应返回占位名。"""
        assert sanitize_filename(None) == "未命名"

    def test_empty_string_returns_placeholder(self):
        """空字符串应返回占位名。"""
        assert sanitize_filename("") == "未命名"

    def test_whitespace_only_returns_placeholder(self):
        """纯空白应返回占位名。"""
        assert sanitize_filename("   ") == "未命名"

    def test_replaces_all_forbidden_chars(self):
        """所有文件系统非法字符（\\ / : * ? " < > |）应被替换为下划线。"""
        result = sanitize_filename('a\\b/c:d*e?f"g<h>i|j')
        for ch in '\\/:*?"<>|':
            assert ch not in result

    def test_all_forbidden_chars_replaced_to_underscores(self):
        """全为非法字符时，应替换为下划线串（非占位名，因替换后非空）。"""
        assert sanitize_filename("///") == "___"

    def test_custom_replacement(self):
        """应支持自定义替换字符。"""
        assert sanitize_filename("a:b", replacement="-") == "a-b"

    def test_strips_whitespace(self):
        """应去除首尾空白。"""
        assert sanitize_filename("  民法典  ") == "民法典"

    def test_truncates_long_name(self):
        """超长文件名应被截断到 200 字符。"""
        result = sanitize_filename("法" * 300)
        assert len(result) == 200

    def test_returns_string_type(self):
        """返回值应为字符串类型。"""
        assert isinstance(sanitize_filename("x"), str)
        assert isinstance(sanitize_filename(None), str)
