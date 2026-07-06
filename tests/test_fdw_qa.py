# -*- coding: utf-8 -*-
"""FDWScraper 翻页相关纯函数单元测试。

覆盖法答网抓取的两类历史 bug：
1. ``parse_links`` 误把分页导航链接（首页/上一页/下一页/尾页）当文章下载，
   导致 "No title found" 失败；
2. ``download`` 只抓第 1 页、从不翻页 —— 这里通过 ``parse_total_pages`` 与
   ``_build_page_url`` 间接保证翻页所需的页数解析与 URL 构造正确。
"""

import pytest

from laws_database.sources.fdw_qa import FDWScraper


# 模拟搜索结果页：2 篇文章 + 分页栏（首页/上一页/下一页/尾页）
SAMPLE_HTML = """
<html><body>
<div class="search_list">
  <li><a href="/zixun/xiangqing/488441.html">法答网精选答问（第三十七批）——执行工作专题</a></li>
  <li><a href="/zixun/xiangqing/487091.html">法答网精选答问（第三十六批）——国家赔偿专题</a></li>
  <li><a href="/search.html?content=法答网精选答问&page=1">首页</a></li>
  <li><a href="/search.html?content=法答网精选答问&page=1">上一页</a></li>
  <li><a href="/search.html?content=法答网精选答问&page=2">下一页</a></li>
  <li><a href="/search.html?content=法答网精选答问&page=2">尾页</a></li>
</div>
</body></html>
"""


@pytest.fixture
def scraper(tmp_path):
    """构造一个指向临时目录的抓取器实例（避免污染真实数据目录）。"""
    return FDWScraper(
        data_dir=tmp_path,
        base_url="https://www.court.gov.cn",
        search_url="https://www.court.gov.cn/search.html?content=%E6%B3%95",
    )


class TestParseLinks:
    """parse_links 过滤分页导航链接测试。"""

    def test_filters_pagination_links(self, scraper):
        """应只保留 /zixun/xiangqing/ 文章链接，丢弃 4 个 page= 分页链接。"""
        links = scraper.parse_links(SAMPLE_HTML)
        assert links == [
            "/zixun/xiangqing/488441.html",
            "/zixun/xiangqing/487091.html",
        ]

    def test_empty_html_returns_empty(self, scraper):
        """空 HTML 返回空列表。"""
        assert scraper.parse_links("") == []

    def test_none_html_returns_empty(self, scraper):
        """None 返回空列表（不抛错）。"""
        assert scraper.parse_links(None) == []

    def test_no_search_list_returns_empty(self, scraper):
        """无 search_list 容器时返回空列表。"""
        assert scraper.parse_links("<html><body>no list here</body></html>") == []


class TestParseTotalPages:
    """parse_total_pages 从尾页链接提取总页数测试。"""

    def test_extracts_from_last_page_link(self, scraper):
        """尾页 page=2 → 总页数 2。"""
        assert scraper.parse_total_pages(SAMPLE_HTML) == 2

    def test_fallback_when_no_last_link(self, scraper):
        """无尾页链接时安全降级为 1（只抓第 1 页，绝不死循环）。"""
        html = "<html><body><div class='search_list'><li><a href='/x.html'>a</a></li></div></body></html>"
        assert scraper.parse_total_pages(html) == 1

    def test_empty_html_returns_one(self, scraper):
        """空 HTML 降级为 1。"""
        assert scraper.parse_total_pages("") == 1

    def test_none_html_returns_one(self, scraper):
        """None 降级为 1。"""
        assert scraper.parse_total_pages(None) == 1


class TestBuildPageUrl:
    """_build_page_url 翻页 URL 构造测试。"""

    def test_appends_with_ampersand_when_has_query(self, scraper):
        """search_url 已含 ?content= 时用 & 拼接 page。"""
        assert scraper._build_page_url(2) == (
            "https://www.court.gov.cn/search.html?content=%E6%B3%95&page=2"
        )

    def test_appends_with_question_mark_when_no_query(self, tmp_path):
        """search_url 无查询串时用 ? 起始 page。"""
        scraper = FDWScraper(
            data_dir=tmp_path,
            base_url="https://www.court.gov.cn",
            search_url="https://www.court.gov.cn/search.html",
        )
        assert scraper._build_page_url(3) == "https://www.court.gov.cn/search.html?page=3"


class TestFormatContent:
    """_format_content 正文转 Markdown 测试。"""

    def test_question_lines_become_h2(self, scraper):
        """以'问题'开头且含'：'的行应转为二级标题。"""
        out = scraper._format_content("标题", "问题1：问\n普通行")
        assert out == "# 标题\n\n## 问题1：问\n普通行\n"

    def test_plain_lines_unchanged(self, scraper):
        """普通行原样保留，以一级标题起始。"""
        out = scraper._format_content("T", "第一行\n第二行")
        assert out == "# T\n\n第一行\n第二行\n"


class TestUrlIndex:
    """URL→文件名 索引持久化测试。"""

    def test_save_load_roundtrip(self, scraper):
        """保存的索引应能完整读回。"""
        scraper._save_url_index({"/a/1.html": "标题一", "/a/2.html": "标题二"})
        assert scraper._load_url_index() == {"/a/1.html": "标题一", "/a/2.html": "标题二"}

    def test_load_missing_returns_empty(self, scraper):
        """索引文件不存在时返回空 dict。"""
        assert scraper._load_url_index() == {}

    def test_load_corrupt_returns_empty(self, scraper):
        """索引文件损坏时返回空 dict（不抛错，安全降级）。"""
        scraper._index_path().write_text("{不是合法json", encoding="utf-8")
        assert scraper._load_url_index() == {}


class TestSaveToMarkdownTwoPhase:
    """save_to_markdown 两阶段（URL 判断 + 增量下载）集成测试。"""

    ARTICLE_HTML = """
    <html><body>
      <div class="title">法答网精选答问（第一批）</div>
      <div class="txt big">问题1：提问内容
回答内容</div>
    </body></html>
    """

    def test_first_run_downloads_and_indexes(self, scraper, monkeypatch):
        """首次：索引为空 → 抓取 → 写文件 + 建立 URL 索引。"""
        safe = scraper.get_safe_filename("法答网精选答问（第一批）")
        calls = []

        def fake_fetch(url):
            calls.append(url)
            return TestSaveToMarkdownTwoPhase.ARTICLE_HTML

        monkeypatch.setattr(scraper, "fetch_page", fake_fetch)
        scraper.save_to_markdown(["/x/1.html"])

        assert (scraper.output_dir / f"{safe}.md").exists()
        assert scraper._load_url_index() == {"/x/1.html": safe}
        assert len(calls) == 1  # 仅抓取一次

    def test_second_run_skips_via_index_no_fetch(self, scraper, monkeypatch):
        """二次：URL 索引命中 → 完全不抓取（已下载零冗余）。"""
        safe = scraper.get_safe_filename("法答网精选答问（第一批）")
        scraper._save_url_index({"/x/1.html": safe})
        calls = []
        monkeypatch.setattr(scraper, "fetch_page", lambda url: calls.append(url) or "不应被调用")

        scraper.save_to_markdown(["/x/1.html"])

        assert calls == []  # 未发起任何请求

    def test_existing_file_migrates_index_without_rewrite(self, scraper, monkeypatch):
        """迁移期：索引缺失但文件已存在 → 只补全索引，不覆盖文件内容。"""
        safe = scraper.get_safe_filename("法答网精选答问（第一批）")
        (scraper.output_dir / f"{safe}.md").write_text("# 旧内容\n", encoding="utf-8")
        monkeypatch.setattr(scraper, "fetch_page", lambda url: TestSaveToMarkdownTwoPhase.ARTICLE_HTML)

        scraper.save_to_markdown(["/x/1.html"])

        assert scraper._load_url_index() == {"/x/1.html": safe}  # 索引被补全
        # 文件内容未被新下载覆盖
        assert (scraper.output_dir / f"{safe}.md").read_text(encoding="utf-8") == "# 旧内容\n"

    def test_missing_file_redownloads_even_if_recorded(self, scraper, monkeypatch):
        """以文件系统为准：文件丢失时，即使旧 txt 记录已登记也重新下载补回。"""
        safe = scraper.get_safe_filename("法答网精选答问（第一批）")
        scraper.record_store.save_all({safe})  # 旧记录有，但无文件、无 URL 索引
        monkeypatch.setattr(scraper, "fetch_page", lambda url: TestSaveToMarkdownTwoPhase.ARTICLE_HTML)

        scraper.save_to_markdown(["/x/1.html"])

        assert (scraper.output_dir / f"{safe}.md").exists()  # 重新下载补回
        assert scraper._load_url_index() == {"/x/1.html": safe}
