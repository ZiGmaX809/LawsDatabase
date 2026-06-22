# -*- coding: utf-8 -*-
"""law_versions_db 纯函数（extract_base_name / extract_year）的单元测试。"""

from laws_database.sources.law_versions_db import extract_base_name, extract_year


class TestExtractBaseName:
    """extract_base_name 去除年份后缀测试。"""

    def test_full_width_paren_year(self):
        """全角括号年份应被去除。"""
        assert extract_base_name("中华人民共和国民用航空法（2021）") == "中华人民共和国民用航空法"

    def test_half_width_paren_year(self):
        """半角括号年份应被去除。"""
        assert extract_base_name("中华人民共和国民用航空法(2021)") == "中华人民共和国民用航空法"

    def test_year_with_modifier(self):
        """括号内含'修正'等修饰词时，整段应被去除。"""
        assert extract_base_name("中华人民共和国民用航空法（2021修正）") == "中华人民共和国民用航空法"

    def test_no_year_suffix_unchanged(self):
        """无年份后缀时原样返回。"""
        assert extract_base_name("中华人民共和国民法典") == "中华人民共和国民法典"

    def test_empty_string(self):
        """空字符串返回空。"""
        assert extract_base_name("") == ""

    def test_none_returns_empty(self):
        """None 返回空（不抛错）。"""
        assert extract_base_name(None) == ""


class TestExtractYear:
    """extract_year 从公布日期提取年份测试。"""

    def test_iso_date(self):
        """ISO 格式日期（带横线）应提取年份。"""
        assert extract_year("2021-04-29") == "2021"

    def test_compact_date(self):
        """紧凑格式日期（无横线）应提取年份。"""
        assert extract_year("20210429") == "2021"

    def test_empty_string(self):
        """空字符串返回空。"""
        assert extract_year("") == ""

    def test_none_returns_empty(self):
        """None 返回空（不抛错）。"""
        assert extract_year(None) == ""

    def test_short_string_returns_empty(self):
        """不足4位的字符串返回空。"""
        assert extract_year("202") == ""
