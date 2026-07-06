# -*- coding: utf-8 -*-
"""court_cases（PCC）编号提取、编号清单重建、下载按编号判重的单元测试。"""

import json

from laws_database.sources.court_cases import (
    CASE_TYPES,
    CourtDataProcessor,
    _choose_incremental_scope,
    _run_all_categories_incremental,
)
from laws_database.sources.court_cases_batch import extract_case_no_from_md


def _write_case_md(path, case_no, title="某案"):
    """写一个含「#### 案件信息」段的最小案例 md。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# {title}\n### 基本案情\n略\n#### 案件信息\n{case_no} / 2024.01.01 / 案号 / 入库日期：2024.01.01\n",
        encoding="utf-8",
    )


class TestExtractCaseNoFromMd:
    """extract_case_no_from_md 编号提取测试。"""

    def test_extract_from_case_info_section(self, tmp_path):
        """应从「#### 案件信息」段提取首个编号。"""
        md = tmp_path / "case.md"
        md.write_text(
            "# 某案\n#### 案件信息\n2026-01-2-352-001 / 2024.08.22 / 案号\n",
            encoding="utf-8",
        )
        assert extract_case_no_from_md(md) == "2026-01-2-352-001"

    def test_extract_fallback_fulltext_without_header(self, tmp_path):
        """无「案件信息」标题时，兜底全文检索首个编号。"""
        md = tmp_path / "case.md"
        md.write_text("# 某案\n正文中出现编号 2023-14-2-139-001\n", encoding="utf-8")
        assert extract_case_no_from_md(md) == "2023-14-2-139-001"

    def test_extract_returns_none_when_no_case_no(self, tmp_path):
        """无五段式编号时返回 None（日期 2024-08-22 仅 3 段，不应误匹配）。"""
        md = tmp_path / "case.md"
        md.write_text("# 某案\n日期 2024-08-22 不应被匹配\n", encoding="utf-8")
        assert extract_case_no_from_md(md) is None

    def test_extract_returns_none_for_missing_file(self, tmp_path):
        """文件不存在时返回 None（不抛异常）。"""
        assert extract_case_no_from_md(tmp_path / "nope.md") is None

    def test_extract_handles_varying_segment_widths(self, tmp_path):
        """应兼容各段位数字位数差异的编号。"""
        for no in ["2023-14-2-139-001", "2026-01-2-108-001", "2011-18-2-123-001"]:
            md = tmp_path / f"{no}.md"
            md.write_text(f"#### 案件信息\n{no} / x\n", encoding="utf-8")
            assert extract_case_no_from_md(md) == no


class TestRebuildKnownNos:
    """rebuild_known_nos 编号清单重建测试。"""

    def test_rebuild_collects_unique_case_nos(self, tmp_path):
        """应从 target 目录 md 提取编号，全量覆盖写回 known_case_nos。"""
        target = tmp_path / "kb"
        case_dir = target / "民事" / "借款合同纠纷"
        _write_case_md(case_dir / "案A.md", "2023-16-2-103-021", "案A")
        _write_case_md(case_dir / "案B.md", "2024-11-2-103-001", "案B")
        # 无编号文件（如统计信息）应被忽略，不计入清单
        (case_dir / "统计信息.md").write_text("# 统计\n无编号\n", encoding="utf-8")

        data_dir = tmp_path / "data"
        processor = CourtDataProcessor(data_dir, case_type="civil", target_dir=str(target))
        result = processor.rebuild_known_nos()

        assert result["count"] == 2
        assert result["scanned"] == 3  # 含被忽略的统计 md
        nos_file = data_dir / "downloaded_records" / "known_case_nos_civil.txt"
        assert nos_file.exists()
        lines = {line.strip() for line in nos_file.read_text(encoding="utf-8").splitlines() if line.strip()}
        assert lines == {"2023-16-2-103-021", "2024-11-2-103-001"}

    def test_rebuild_overwrites_stale_records(self, tmp_path):
        """重建应覆盖旧记录（删掉的案例不再残留）。"""
        target = tmp_path / "kb"
        case_dir = target / "民事" / "借款合同纠纷"
        _write_case_md(case_dir / "案A.md", "2023-16-2-103-021", "案A")

        data_dir = tmp_path / "data"
        nos_file = data_dir / "downloaded_records" / "known_case_nos_civil.txt"
        nos_file.parent.mkdir(parents=True, exist_ok=True)
        nos_file.write_text("OLD-STALE-NO\nANOTHER-STALE\n", encoding="utf-8")  # 旧脏数据

        processor = CourtDataProcessor(data_dir, case_type="civil", target_dir=str(target))
        processor.rebuild_known_nos()

        lines = {line.strip() for line in nos_file.read_text(encoding="utf-8").splitlines() if line.strip()}
        assert lines == {"2023-16-2-103-021"}  # 旧脏数据已被覆盖
        assert "OLD-STALE-NO" not in lines

    def test_rebuild_missing_target_returns_empty(self, tmp_path):
        """未设置 target_dir 时返回空字典并记日志，不抛异常。"""
        data_dir = tmp_path / "data"
        processor = CourtDataProcessor(data_dir, case_type="civil", target_dir="")
        assert processor.rebuild_known_nos() == {}


class TestDownloadDedupByCaseNo:
    """download_case_details 按案件编号判重测试（核心：编号替代标题判重）。"""

    def _setup_processor(self, tmp_path, existing_nos):
        """构造 processor：target 已有 existing_nos 的案例 md，json 列表含这些编号 + 新编号。"""
        target = tmp_path / "kb"
        type_dir = target / "民事" / "借款合同纠纷"
        data_dir = tmp_path / "data"
        json_dir = data_dir / "court_data" / "pages" / "民事"

        datas = []
        for no in existing_nos:
            _write_case_md(type_dir / f"{no}.md", no, no)
            datas.append({  # 已存在的也放进列表，验证它会被跳过
                "id": f"id-{no}",
                "cpws_al_title": no,
                "cpws_al_no": no,
                "cpws_al_sort_name": "借款合同纠纷",
            })
        # 新案例 B（不在 target）
        new_no = "2024-11-2-103-001"
        datas.append({
            "id": "id-new-B",
            "cpws_al_title": "新案B",
            "cpws_al_no": new_no,
            "cpws_al_sort_name": "借款合同纠纷",
        })
        json_dir.mkdir(parents=True, exist_ok=True)
        (json_dir / "initial_response.json").write_text(
            json.dumps({"data": {"datas": datas}}), encoding="utf-8"
        )
        return target, data_dir, new_no

    def test_skips_existing_case_no_and_downloads_new(self, tmp_path, monkeypatch):
        """target 已有编号 A 时，列表中的 A 应被跳过，仅下载新编号 B。"""
        target, data_dir, new_no = self._setup_processor(tmp_path, ["2023-16-2-103-021"])

        fetched_ids = []

        def fake_fetch(case_id):
            fetched_ids.append(case_id)
            return {"data": {"data": {  # 返回新案 B 的详情
                "cpws_al_title": "新案B",
                "cpws_al_sub_title": "",
                "cpws_al_keyword": [],
                "cpws_al_jbaq": "", "cpws_al_cply": "", "cpws_al_cpyz": "",
                "cpws_al_glsy": "", "cpws_al_infos": f"{new_no} / x",
            }}}

        def fake_save(content_data, output_dir):
            output_dir.mkdir(parents=True, exist_ok=True)
            title = content_data["data"]["data"]["cpws_al_title"]
            (output_dir / f"{title}.md").write_text("# " + title, encoding="utf-8")
            return True

        processor = CourtDataProcessor(
            data_dir, token="fake-token", case_type="civil", target_dir=str(target)
        )
        monkeypatch.setattr(processor, "fetch_case_content", fake_fetch)
        monkeypatch.setattr(processor, "save_as_markdown", fake_save)
        monkeypatch.setattr(processor, "organize_single_file", lambda md, tts, td: True)

        processor.download_case_details()

        # 已存在的 A 未触发 fetch，只下载了新案 B
        assert fetched_ids == ["id-new-B"]

    def test_case_without_no_is_not_skipped(self, tmp_path, monkeypatch):
        """列表项缺 cpws_al_no 时不应被判重跳过（无法判重则正常下载）。"""
        target = tmp_path / "kb"
        (target / "民事" / "借款合同纠纷").mkdir(parents=True)
        data_dir = tmp_path / "data"
        json_dir = data_dir / "court_data" / "pages" / "民事"
        json_dir.mkdir(parents=True, exist_ok=True)
        # 列表只有 1 项，且无 cpws_al_no
        (json_dir / "initial_response.json").write_text(json.dumps({"data": {"datas": [
            {"id": "id-no-no", "cpws_al_title": "无编号案", "cpws_al_sort_name": "借款合同纠纷"},
        ]}}), encoding="utf-8")

        fetched_ids = []
        monkeypatch.setattr(
            CourtDataProcessor, "fetch_case_content",
            lambda self, case_id: fetched_ids.append(case_id) or {"data": {"data": {
                "cpws_al_title": "无编号案", "cpws_al_sub_title": "", "cpws_al_keyword": [],
                "cpws_al_jbaq": "", "cpws_al_cply": "", "cpws_al_cpyz": "",
                "cpws_al_glsy": "", "cpws_al_infos": "",
            }}},
        )
        monkeypatch.setattr(CourtDataProcessor, "save_as_markdown", lambda self, cd, od: True)

        processor = CourtDataProcessor(
            data_dir, token="fake-token", case_type="civil", target_dir=str(target)
        )
        processor.download_case_details()

        # 无编号不应被跳过，应触发下载
        assert fetched_ids == ["id-no-no"]


class TestOrganizeSameTitleProtection:
    """organize 同名不同编号案例的覆盖保护测试（脱敏标题撞车场景）。"""

    def _make(self, tmp_path, dest_no=None, src_no="2023-17-5-203-024", src_name="甲案.md"):
        """构造 processor + type_dir，可选地在 target 预置一个同名 md。"""
        target_root = tmp_path / "kb"
        type_dir = target_root / "执行"
        sort_dir = type_dir / "执行监督案件"
        sort_dir.mkdir(parents=True)
        if dest_no is not None:
            (sort_dir / "甲案.md").write_text(
                f"#### 案件信息\n{dest_no} / x\n", encoding="utf-8"
            )
        data_dir = tmp_path / "data"
        md_dir = data_dir / "downloaded_markdown" / "执行"
        md_dir.mkdir(parents=True)
        src = md_dir / src_name
        src.write_text(f"#### 案件信息\n{src_no} / x\n", encoding="utf-8")
        processor = CourtDataProcessor(data_dir, case_type="execution", target_dir=str(target_root))
        return processor, src, type_dir, sort_dir

    def test_same_title_different_no_not_overwrite(self, tmp_path):
        """同名不同编号应追加编号区分，原文件不被覆盖。"""
        processor, src, type_dir, sort_dir = self._make(tmp_path, dest_no="2024-17-5-203-036")
        ok = processor.organize_single_file(src, {"甲案": "执行监督案件"}, type_dir)
        assert ok is True
        # 原 036 完好
        assert extract_case_no_from_md(sort_dir / "甲案.md") == "2024-17-5-203-036"
        # 新 024 追加编号存为新文件
        new_file = sort_dir / "甲案_2023-17-5-203-024.md"
        assert new_file.exists()
        assert extract_case_no_from_md(new_file) == "2023-17-5-203-024"

    def test_same_title_same_no_overwrites(self, tmp_path):
        """同编号（重试/更新）应正常覆盖，不加后缀。"""
        processor, src, type_dir, sort_dir = self._make(
            tmp_path, dest_no="2024-17-5-203-036", src_no="2024-17-5-203-036"
        )
        ok = processor.organize_single_file(src, {"甲案": "执行监督案件"}, type_dir)
        assert ok is True
        assert (sort_dir / "甲案.md").exists()
        # 同编号不应产生带后缀的副本
        assert not (sort_dir / "甲案_2024-17-5-203-036.md").exists()

    def test_new_title_keeps_plain_name(self, tmp_path):
        """无冲突的新案例保持原名，不加编号后缀（向后兼容现有命名）。"""
        processor, src, type_dir, sort_dir = self._make(tmp_path, dest_no=None, src_name="新案.md")
        ok = processor.organize_single_file(src, {"新案": "执行监督案件"}, type_dir)
        assert ok is True
        assert (sort_dir / "新案.md").exists()
        assert not (sort_dir / "新案_2023-17-5-203-024.md").exists()


# ===== 编号一致性修复（列表编号 vs 详情编号）测试 =====


def _make_detail(case_no_in_md, title="某案"):
    """构造详情 API 返回：cpws_al_infos 内嵌 case_no_in_md（写进 md 的编号）。"""
    return {"data": {"data": {
        "cpws_al_title": title, "cpws_al_sub_title": "", "cpws_al_keyword": [],
        "cpws_al_jbaq": "", "cpws_al_cply": "", "cpws_al_cpyz": "",
        "cpws_al_glsy": "", "cpws_al_infos": f"{case_no_in_md} / x",
    }}}


def _build_scenario(tmp_path, items, case_type="civil", type_name="民事"):
    """构建下载场景：json 列表含 items（每个含 list_no/title/sort_name）。

    返回 (target_root, data_dir)。target 初始为空目录。
    """
    target = tmp_path / "kb"
    data_dir = tmp_path / "data"
    json_dir = data_dir / "court_data" / "pages" / type_name
    json_dir.mkdir(parents=True, exist_ok=True)
    (json_dir / "initial_response.json").write_text(
        json.dumps({"data": {"datas": items}}), encoding="utf-8"
    )
    return target, data_dir


def _known_nos(data_dir, case_type):
    """读取某分类 known_case_nos 文件内容为集合；文件不存在返回空集。"""
    f = data_dir / "downloaded_records" / f"known_case_nos_{case_type}.txt"
    if not f.exists():
        return set()
    return {l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()}


def _aliases(data_dir, case_type):
    """读取某分类 case_no_aliases 文件的 aliases dict。"""
    import json as _json
    f = data_dir / "downloaded_records" / f"case_no_aliases_{case_type}.json"
    return _json.loads(f.read_text(encoding="utf-8")).get("aliases", {})


class TestRecordMdNo:
    """下载成功后只记录 md 内嵌的详情编号（md_no），且仅在整理成功时记录。"""

    def _processor(self, data_dir, target, monkeypatch, fetch_impl, organize_ok=True):
        processor = CourtDataProcessor(
            data_dir, token="fake-token", case_type="civil",
            target_dir=str(target), request_interval=[0, 0],
        )
        monkeypatch.setattr(processor, "fetch_case_content", fetch_impl)
        monkeypatch.setattr(processor, "organize_single_file", lambda md, tts, td: organize_ok)
        return processor

    def test_known_no_uses_md_no_not_list_no(self, tmp_path, monkeypatch):
        """列表 cpws_al_no=X、详情 md 内嵌 Y(X≠Y) → known_case_nos 记 Y 不记 X。"""
        target, data_dir = _build_scenario(tmp_path, [{
            "id": "id-1", "cpws_al_title": "某案",
            "cpws_al_no": "2023-04-1-291-001",  # 列表编号 X
            "cpws_al_sort_name": "借款合同纠纷",
        }])
        processor = self._processor(
            data_dir, target, monkeypatch,
            lambda cid: _make_detail("2023-04-1-290-001"),  # 详情编号 Y
        )
        processor.download_case_details()
        nos = _known_nos(data_dir, "civil")
        assert "2023-04-1-290-001" in nos   # 记 md_no
        assert "2023-04-1-291-001" not in nos  # 不记 list_no

    def test_fallback_to_list_no_when_md_has_no_case_no(self, tmp_path, monkeypatch):
        """md 无编号时回退记录 list_no。"""
        target, data_dir = _build_scenario(tmp_path, [{
            "id": "id-1", "cpws_al_title": "某案",
            "cpws_al_no": "2023-04-1-291-001", "cpws_al_sort_name": "借款合同纠纷",
        }])
        processor = self._processor(
            data_dir, target, monkeypatch,
            lambda cid: _make_detail(""),  # 详情无编号
        )
        processor.download_case_details()
        assert "2023-04-1-291-001" in _known_nos(data_dir, "civil")

    def test_record_only_on_organize_success(self, tmp_path, monkeypatch):
        """整理失败 → 不记录编号，且源 md 保留在 markdown_dir（覆盖 organize-unlink 修复）。"""
        target, data_dir = _build_scenario(tmp_path, [{
            "id": "id-1", "cpws_al_title": "某案",
            "cpws_al_no": "2023-04-1-291-001", "cpws_al_sort_name": "借款合同纠纷",
        }])
        processor = self._processor(
            data_dir, target, monkeypatch,
            lambda cid: _make_detail("2023-04-1-290-001"), organize_ok=False,
        )
        processor.download_case_details()
        # 未记录
        assert _known_nos(data_dir, "civil") == set()
        # 源 md 仍在 markdown_dir（未被删除）
        md_dir = data_dir / "downloaded_markdown" / "民事"
        assert any(md_dir.glob("*.md"))


class TestSelfHealKnownNos:
    """自愈：把 known_case_nos 收敛到 target 实际编号。"""

    def test_self_heal_prunes_ghost_not_in_target(self, tmp_path, monkeypatch):
        """known 含幽灵 G + 真实 R → 跑后只剩 R。"""
        target, data_dir = _build_scenario(tmp_path, [])  # 空 json，无新下载
        # target 预置真实 R 的 md
        _write_case_md(target / "民事" / "借款合同纠纷" / "R.md", "2023-16-2-103-021", "R")
        # known 预置 R + 幽灵 G
        nos_file = data_dir / "downloaded_records" / "known_case_nos_civil.txt"
        nos_file.parent.mkdir(parents=True, exist_ok=True)
        nos_file.write_text("2023-16-2-103-021\nGHOST-NO\n", encoding="utf-8")

        processor = CourtDataProcessor(
            data_dir, token="fake-token", case_type="civil",
            target_dir=str(target), request_interval=[0, 0],
        )
        processor.download_case_details()
        assert _known_nos(data_dir, "civil") == {"2023-16-2-103-021"}

    def test_self_heal_persists_even_without_new_downloads(self, tmp_path, monkeypatch):
        """无新下载（json 全命中 target）时自愈仍立即落盘（覆盖 _flush 早退陷阱）。"""
        target, data_dir = _build_scenario(tmp_path, [{
            "id": "id-1", "cpws_al_title": "R",
            "cpws_al_no": "2023-16-2-103-021", "cpws_al_sort_name": "借款合同纠纷",
        }])
        _write_case_md(target / "民事" / "借款合同纠纷" / "R.md", "2023-16-2-103-021", "R")
        nos_file = data_dir / "downloaded_records" / "known_case_nos_civil.txt"
        nos_file.parent.mkdir(parents=True, exist_ok=True)
        nos_file.write_text("2023-16-2-103-021\nGHOST-NO\n", encoding="utf-8")

        processor = CourtDataProcessor(
            data_dir, token="fake-token", case_type="civil",
            target_dir=str(target), request_interval=[0, 0],
        )
        processor.download_case_details()
        # 幽灵被清理并落盘（即便本次没有任何新下载）
        assert _known_nos(data_dir, "civil") == {"2023-16-2-103-021"}

    def test_self_heal_skipped_when_target_empty(self, tmp_path, monkeypatch):
        """target 为空 → 守卫生效，不清空 known_case_nos（防配置误删）。"""
        target, data_dir = _build_scenario(tmp_path, [])
        # target 存在但无 md（organized_case_nos 为空）
        (target / "民事").mkdir(parents=True)
        nos_file = data_dir / "downloaded_records" / "known_case_nos_civil.txt"
        nos_file.parent.mkdir(parents=True, exist_ok=True)
        nos_file.write_text("2023-16-2-103-021\nGHOST-NO\n", encoding="utf-8")

        processor = CourtDataProcessor(
            data_dir, token="fake-token", case_type="civil",
            target_dir=str(target), request_interval=[0, 0],
        )
        processor.download_case_details()
        # 未被清空
        assert _known_nos(data_dir, "civil") == {"2023-16-2-103-021", "GHOST-NO"}


class TestCaseNoAlias:
    """别名映射：消除列表编号≠详情编号案件的重复下载。"""

    def test_alias_recorded_when_list_no_neq_md_no(self, tmp_path, monkeypatch):
        """下载 X→Y(X≠Y) → case_no_aliases 记 {X: Y}。"""
        target, data_dir = _build_scenario(tmp_path, [{
            "id": "id-1", "cpws_al_title": "某案",
            "cpws_al_no": "2023-04-1-291-001", "cpws_al_sort_name": "借款合同纠纷",
        }])
        processor = CourtDataProcessor(
            data_dir, token="fake-token", case_type="civil",
            target_dir=str(target), request_interval=[0, 0],
        )
        monkeypatch.setattr(processor, "fetch_case_content", lambda cid: _make_detail("2023-04-1-290-001"))
        monkeypatch.setattr(processor, "organize_single_file", lambda md, tts, td: True)
        processor.download_case_details()
        assert _aliases(data_dir, "civil") == {"2023-04-1-291-001": "2023-04-1-290-001"}

    def test_effective_known_expands_by_alias(self, tmp_path, monkeypatch):
        """target 有 md_no Y、别名 {X:Y} → 列表给 X 时被跳过，不下载。"""
        target, data_dir = _build_scenario(tmp_path, [{
            "id": "id-1", "cpws_al_title": "某案",
            "cpws_al_no": "2023-04-1-291-001",  # 列表给 X
            "cpws_al_sort_name": "借款合同纠纷",
        }])
        # target 预置 Y 的 md（已下载）
        _write_case_md(target / "民事" / "借款合同纠纷" / "某案.md", "2023-04-1-290-001", "某案")
        processor = CourtDataProcessor(
            data_dir, token="fake-token", case_type="civil",
            target_dir=str(target), request_interval=[0, 0],
        )
        # 预置别名 {X: Y}
        processor.save_aliases({"2023-04-1-291-001": "2023-04-1-290-001"})
        fetched = []
        monkeypatch.setattr(processor, "fetch_case_content", lambda cid: fetched.append(cid) or None)
        processor.download_case_details()
        assert fetched == []  # X 经别名展开命中跳过，未触发下载

    def test_same_run_dual_key_no_redownload(self, tmp_path, monkeypatch):
        """同一案以 list_no X 出现在 2 个 JSON 文件 → 只下载一次（内存双键）。"""
        target, data_dir = _build_scenario(tmp_path, [{
            "id": "id-1", "cpws_al_title": "某案",
            "cpws_al_no": "2023-04-1-291-001", "cpws_al_sort_name": "借款合同纠纷",
        }])
        # 第二个 JSON 也含同一 list_no
        import json as _json
        (data_dir / "court_data" / "pages" / "民事" / "second.json").write_text(
            _json.dumps({"data": {"datas": [{
                "id": "id-1", "cpws_al_title": "某案",
                "cpws_al_no": "2023-04-1-291-001", "cpws_al_sort_name": "借款合同纠纷",
            }]}}), encoding="utf-8")
        processor = CourtDataProcessor(
            data_dir, token="fake-token", case_type="civil",
            target_dir=str(target), request_interval=[0, 0],
        )
        fetched = []
        monkeypatch.setattr(processor, "fetch_case_content",
                            lambda cid: fetched.append(cid) or _make_detail("2023-04-1-290-001"))
        monkeypatch.setattr(processor, "organize_single_file", lambda md, tts, td: True)
        processor.download_case_details()
        assert len(fetched) == 1  # 两个 JSON 都含 X，但只下载一次


class TestChooseIncrementalScope:
    """选项 1 增量下载的范围子菜单分发。"""

    def test_returns_all_on_choice_1(self, monkeypatch):
        """子菜单选 1 → 返回 'all'（全部分类）。"""
        inputs = iter(["1"])
        monkeypatch.setattr("builtins.input", lambda *a, **k: next(inputs))
        assert _choose_incremental_scope() == "all"

    def test_returns_single_case_type_on_choice_2(self, monkeypatch):
        """子菜单选 2 → 进入单分类选择，再选 1 → 返回 criminal。"""
        inputs = iter(["2", "1"])  # 2=单个分类, 1=criminal
        monkeypatch.setattr("builtins.input", lambda *a, **k: next(inputs))
        assert _choose_incremental_scope() == "criminal"

    def test_reprompts_on_invalid_then_all(self, monkeypatch):
        """非法输入后重新提示，最终选 1 返回 'all'。"""
        inputs = iter(["x", "1"])
        monkeypatch.setattr("builtins.input", lambda *a, **k: next(inputs))
        assert _choose_incremental_scope() == "all"


class TestAllCategoriesIncremental:
    """全部分类增量下载：一次 token 循环 5 分类，命中上限立即停止。"""

    def test_all_types_break_on_limit_reached(self, tmp_path, monkeypatch):
        """criminal 命中上限 → 后续分类不再执行。"""
        calls = []

        def fake_fetch(self):
            calls.append(("fetch", self.config.get("case_type_code")))
            return {"data": {"datas": []}}

        def fake_download(self):
            calls.append(("download", self.config.get("case_type_code")))
            return "limit_reached" if self.config.get("case_type_code") == "criminal" else True

        monkeypatch.setattr(CourtDataProcessor, "fetch_case_list", fake_fetch)
        monkeypatch.setattr(CourtDataProcessor, "download_case_details", fake_download)

        result = _run_all_categories_incremental(tmp_path, "fake-token", str(tmp_path), {})
        assert result is False
        downloaded = [c[1] for c in calls if c[0] == "download"]
        assert downloaded == ["criminal"]  # 只到第一个分类

    def test_all_types_processes_all_when_no_limit(self, tmp_path, monkeypatch):
        """无上限 → 5 个分类全部执行。"""
        calls = []
        monkeypatch.setattr(
            CourtDataProcessor, "fetch_case_list",
            lambda self: calls.append("fetch") or {"data": {"datas": []}},
        )
        monkeypatch.setattr(
            CourtDataProcessor, "download_case_details",
            lambda self: calls.append("download") or True,
        )
        result = _run_all_categories_incremental(tmp_path, "fake-token", str(tmp_path), {})
        assert result is True
        assert calls.count("download") == len(CASE_TYPES)


class TestSaveAsMarkdown:
    """save_as_markdown 对详情标题缺失（源站死案例）的处理。"""

    def test_empty_title_returns_false(self, tmp_path):
        """详情 cpws_al_title 为空 → 返回 False（不写文件）。"""
        processor = CourtDataProcessor(tmp_path, case_type="civil", target_dir=str(tmp_path))
        content = {"data": {"data": {
            "cpws_al_title": "", "cpws_al_sub_title": "", "cpws_al_keyword": [],
            "cpws_al_jbaq": "", "cpws_al_cply": "", "cpws_al_cpyz": "",
            "cpws_al_glsy": "", "cpws_al_infos": "",
        }}}
        assert processor.save_as_markdown(content, tmp_path / "md") is False

    def test_missing_title_returns_false(self, tmp_path):
        """详情无 cpws_al_title 字段 → 返回 False。"""
        processor = CourtDataProcessor(tmp_path, case_type="civil", target_dir=str(tmp_path))
        content = {"data": {"data": {
            "cpws_al_sub_title": "", "cpws_al_keyword": [],
            "cpws_al_jbaq": "", "cpws_al_cply": "", "cpws_al_cpyz": "",
            "cpws_al_glsy": "", "cpws_al_infos": "",
        }}}
        assert processor.save_as_markdown(content, tmp_path / "md") is False


class TestDeadCaseNotRecorded:
    """详情标题缺失的死案例：下载流程不应记录、不应残留源文件。"""

    def test_empty_detail_title_not_recorded(self, tmp_path, monkeypatch):
        """详情标题空 → save 失败 → known_case_nos 不含、无源文件残留。"""
        target, data_dir = _build_scenario(tmp_path, [{
            "id": "id-1", "cpws_al_title": "某案",
            "cpws_al_no": "2023-04-1-291-001", "cpws_al_sort_name": "借款合同纠纷",
        }])
        processor = CourtDataProcessor(
            data_dir, token="fake-token", case_type="civil",
            target_dir=str(target), request_interval=[0, 0],
        )
        def dead_detail(_cid):
            return {"data": {"data": {
                "cpws_al_title": "",  # 源站详情数据缺失
                "cpws_al_sub_title": "", "cpws_al_keyword": [],
                "cpws_al_jbaq": "", "cpws_al_cply": "", "cpws_al_cpyz": "",
                "cpws_al_glsy": "", "cpws_al_infos": "",
            }}}

        monkeypatch.setattr(processor, "fetch_case_content", dead_detail)
        processor.download_case_details()
        assert _known_nos(data_dir, "civil") == set()  # 不记录
        md_dir = data_dir / "downloaded_markdown" / "民事"
        assert not any(md_dir.glob("*.md"))  # 无源文件残留


class TestRebuildOrganizedFiles:
    """rebuild_organized_files：从 target md 重建 organized_files 记录。"""

    def test_rebuild_collects_stems(self, tmp_path):
        """应从 target md 收集文件名 stem，全量覆盖写回 organized_files。"""
        target = tmp_path / "kb"
        case_dir = target / "民事" / "借款合同纠纷"
        _write_case_md(case_dir / "案A.md", "2023-16-2-103-021", "案A")
        _write_case_md(case_dir / "案B.md", "2024-11-2-103-001", "案B")

        data_dir = tmp_path / "data"
        processor = CourtDataProcessor(data_dir, case_type="civil", target_dir=str(target))
        result = processor.rebuild_organized_files()

        assert result["count"] == 2
        assert result["scanned"] == 2
        rec_file = data_dir / "court_data" / "organized_files_civil.txt"
        stems = {l.strip() for l in rec_file.read_text(encoding="utf-8").splitlines() if l.strip()}
        assert stems == {"案A", "案B"}

    def test_rebuild_overwrites_stale(self, tmp_path):
        """重建应覆盖旧记录（target 已删的文件不再残留）。"""
        target = tmp_path / "kb"
        case_dir = target / "民事" / "借款合同纠纷"
        _write_case_md(case_dir / "案A.md", "2023-16-2-103-021", "案A")

        data_dir = tmp_path / "data"
        rec_file = data_dir / "court_data" / "organized_files_civil.txt"
        rec_file.parent.mkdir(parents=True, exist_ok=True)
        rec_file.write_text("OLD-STALE\nANOTHER\n", encoding="utf-8")  # 旧脏数据

        processor = CourtDataProcessor(data_dir, case_type="civil", target_dir=str(target))
        processor.rebuild_organized_files()

        stems = {l.strip() for l in rec_file.read_text(encoding="utf-8").splitlines() if l.strip()}
        assert stems == {"案A"}  # 旧脏数据已被覆盖
        assert "OLD-STALE" not in stems

    def test_rebuild_missing_target_returns_empty(self, tmp_path):
        """未设置 target_dir 时返回空字典，不抛异常。"""
        data_dir = tmp_path / "data"
        processor = CourtDataProcessor(data_dir, case_type="civil", target_dir="")
        assert processor.rebuild_organized_files() == {}
