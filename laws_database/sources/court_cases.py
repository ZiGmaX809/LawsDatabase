# -*- coding: utf-8 -*-
"""
人民法院案例库处理器（PCC）
============================

从 https://rmfyalk.court.gov.cn 按案件类型抓取案例，转 Markdown，
整理到分类目录。需 token 认证（``faxin-cpws-al-token``），token 仅运行时
输入、**绝不持久化**（沿用原安全设计）。

重构自原 ``PCC_Database/court_data_processor.py``，整合点：

- 日志 / 文件名清理 / 下载记录统一到 :mod:`laws_database.core`；
- 批处理（下载详情、整理、统计）拆到 :mod:`laws_database.sources.court_cases_batch`；
- 路径解耦：``data_dir``、目标目录等由构造参数注入，不再从 ``__file__`` 推导；
- token 不写配置文件，每次运行时输入或命令行传入。

入口：

- :func:`run`：交互式总菜单调用（二级菜单）。
- :func:`main`：命令行模式，``python -m laws_database.sources.court_cases``。
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import requests

from laws_database.core.file_utils import sanitize_filename as _sanitize_filename
from laws_database.core.logger import Logger
from laws_database.core.record_store import RecordStore
from laws_database.sources.court_cases_batch import CourtBatchOps

# 案件类型配置：类型代码 -> (sort_id, 中文名)
CASE_TYPES = {
    "criminal": ("10000", "刑事"),
    "civil": ("20000", "民事"),
    "administrative": ("30000", "行政"),
    "execution": ("40000", "执行"),
    "compensation": ("50000", "国家赔偿"),
}

# 默认 User-Agent 池
_DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
]

# API 基址
API_BASE_URL = "https://rmfyalk.court.gov.cn/cpws_al_api/api/cpwsAl"


class CourtDataProcessor(CourtBatchOps):
    """人民法院案例库数据处理主程序。"""

    def __init__(
        self,
        data_dir,
        token=None,
        case_type=None,
        incremental=True,
        target_dir=None,
        request_interval=None,
        page_size: int = 300,
        user_agents=None,
    ):
        """
        初始化处理器。

        Args:
            data_dir: 数据根目录（如 ``data/court_cases``）。
            token: 认证 token（运行时输入，不持久化）。
            case_type: 案件类型代码（criminal/civil/...）。
            incremental: 是否增量模式。
            target_dir: 整理目标目录（外部知识库）。
            request_interval: 请求间隔 ``[min, max]`` 秒。
            page_size: API 每页数量。
            user_agents: UA 池。
        """
        self.base_dir = Path(data_dir)
        self.incremental_mode = incremental
        self.config = {
            "token": token or "",
            "target_dir": target_dir or "",
            "request_interval": list(request_interval) if request_interval else [3, 5],
            "page_size": page_size,
            "user_agents": list(user_agents) if user_agents else list(_DEFAULT_USER_AGENTS),
            # 默认目录（case_type 未设置时）
            "json_dir": "court_data/pages",
            "markdown_dir": "downloaded_markdown",
        }

        self.logs_dir = self.base_dir / "court_data" / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.logger = Logger(self.logs_dir, name="pcc")

        if case_type:
            self.set_case_type(case_type)

        self.init_dirs()

    def set_case_type(self, case_type):
        """设置案件类型，更新 sort_id 与分类目录路径。"""
        if case_type not in CASE_TYPES:
            raise ValueError(f"不支持的案件类型: {case_type}，支持: {list(CASE_TYPES.keys())}")
        sort_id, type_name = CASE_TYPES[case_type]
        self.config["case_sort_id"] = sort_id
        self.config["case_type_code"] = case_type
        self.config["case_type_name"] = type_name
        self.config["markdown_dir"] = f"downloaded_markdown/{type_name}"
        self.config["json_dir"] = f"court_data/pages/{type_name}"
        self.log(f"已设置案件类型: {type_name} ({case_type}), sort_id: {sort_id}")

    def init_dirs(self):
        """初始化所需目录。"""
        dirs = [
            self.base_dir / self.config["json_dir"],
            self.base_dir / self.config["markdown_dir"],
            self.base_dir / "downloaded_records",
            self.logs_dir,
        ]
        if self.config.get("target_dir"):
            dirs.append(Path(self.config["target_dir"]))
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    # ---- 向后兼容转发：保持原调用点 self.log / self.sanitize_filename 不变 ----

    def log(self, message: str):
        """记录日志（转发到统一日志器）。"""
        self.logger.log(message)

    def sanitize_filename(self, name: str) -> str:
        """清理文件名（转发到 core.file_utils）。"""
        return _sanitize_filename(name)

    # ---- 状态文件 ----

    def get_state_file_path(self) -> Path:
        """获取案件状态文件路径。"""
        case_type_code = self.config.get("case_type_code", "civil")
        return self.base_dir / "court_data" / f"case_state_{case_type_code}.json"

    def get_known_nos_file_path(self) -> Path:
        """获取已知案件编号记录文件路径（用 cpws_al_no 做稳定标识）。"""
        case_type_code = self.config.get("case_type_code", "civil")
        return self.base_dir / "downloaded_records" / f"known_case_nos_{case_type_code}.txt"

    def load_known_nos(self) -> set:
        """加载已知案件编号集合（cpws_al_no）。"""
        nos = RecordStore(self.get_known_nos_file_path(), fmt="txt").load()
        self.log(f"已加载 {len(nos)} 个已知案件编号（cpws_al_no）")
        return nos

    def save_known_nos(self, nos: set):
        """保存已知案件编号集合。"""
        RecordStore(self.get_known_nos_file_path(), fmt="txt").save_all(nos)
        self.log(f"已保存 {len(nos)} 个已知案件编号")

    def get_organized_files_record_path(self) -> Path:
        """获取已整理文件记录路径。"""
        case_type_code = self.config.get("case_type_code", "civil")
        return self.base_dir / "court_data" / f"organized_files_{case_type_code}.txt"

    def load_organized_files_record(self) -> set:
        """加载已整理文件记录集合。"""
        organized = RecordStore(self.get_organized_files_record_path(), fmt="txt").load()
        if organized:
            self.log(f"已加载 {len(organized)} 个已整理文件记录")
        return organized

    def save_organized_files_record(self, organized_files: set):
        """保存已整理文件记录集合。"""
        RecordStore(self.get_organized_files_record_path(), fmt="txt").save_all(organized_files)
        self.log(f"已保存 {len(organized_files)} 个已整理文件记录")

    def load_case_state(self) -> dict:
        """
        加载案件状态。

        Returns:
            包含 known_case_ids 与 last_fetch_time 的状态字典。
        """
        state_file = self.get_state_file_path()
        default_state = {
            "known_case_ids": set(),
            "last_fetch_time": None,
            "case_type": self.config.get("case_type_code", "civil"),
        }

        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 对所有 ID 做 URL 解码归一化，防止 state 存 %3D 而 API 返回 = 导致比较失败
                    data["known_case_ids"] = {unquote(id_) for id_ in data.get("known_case_ids", [])}
                    self.log(f"成功加载状态文件，已知案件数: {len(data['known_case_ids'])}")
                    return data
            except Exception as e:
                self.log(f"加载状态文件失败: {e}，将使用默认状态")
                return default_state

        self.log(f"状态文件不存在: {state_file}，将使用默认状态")
        return default_state

    def save_case_state(self, state: dict):
        """保存案件状态。"""
        state_file = self.get_state_file_path()
        try:
            os.makedirs(state_file.parent, exist_ok=True)
            save_data = state.copy()
            save_data["known_case_ids"] = [unquote(id_) for id_ in state["known_case_ids"]]
            save_data["last_fetch_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_data["case_type"] = self.config.get("case_type_code", "civil")
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            self.log(f"已保存状态文件，已知案件数: {len(save_data['known_case_ids'])}")
        except Exception as e:
            self.log(f"保存状态文件失败: {e}")

    # ---- 请求 ----

    def get_headers(self) -> dict:
        """获取带 token 的请求头。"""
        if not self.config["token"]:
            raise ValueError("未提供token，请提供有效的token")
        return {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "User-Agent": random.choice(self.config["user_agents"]),
            "faxin-cpws-al-token": str(self.config["token"]),
            "Content-Type": "application/json",
        }

    def fetch_case_list(self):
        """获取案例列表（支持增量 / 全量）。"""
        known_nos = self.load_known_nos()
        mode_str = "增量" if self.incremental_mode else "全量"
        self.log(f"开始获取案例列表 ({mode_str}模式)... 已知案件数量: {len(known_nos)}")

        url = f"{API_BASE_URL}/search"
        page_size = self.config["page_size"]
        page = 1
        all_cases = []
        new_cases = []
        consecutive_known_count = 0

        while True:
            payload = {
                "page": page,
                "size": page_size,
                "lib": "qb",
                "searchParams": {
                    "userSearchType": 1,
                    "isAdvSearch": "0",
                    "selectValue": "qw",
                    "lib": "cpwsAl_qb",
                    "sort_field": "",
                    "sort_id_cpwsAl": self.config["case_sort_id"],
                },
            }
            try:
                response = requests.post(url, headers=self.get_headers(), json=payload, verify=True, timeout=30)
                response.raise_for_status()
                data = response.json()

                if data.get("code") != 0:
                    self.log(f"获取第{page}页失败: {data.get('msg')}")
                    break

                cases = data.get("data", {}).get("datas", [])
                if not cases:
                    self.log(f"第{page}页没有数据，停止获取")
                    break

                page_new_cases = []
                page_known_count = 0
                for case in cases:
                    # 用 cpws_al_no 做存量判断（同案件多次请求保持不变）
                    case_no = case.get("cpws_al_no", "").strip()
                    if not case_no:
                        case_no = case.get("cpws_al_title", "").strip()
                    all_cases.append(case)
                    if case_no and case_no in known_nos:
                        page_known_count += 1
                    else:
                        page_new_cases.append(case)
                        new_cases.append(case)

                self.log(f"第{page}页: 总数 {len(cases)}, 新案件 {len(page_new_cases)}, 已知 {page_known_count}")

                # 增量模式：连续 3 页全是已知，说明已到达上次获取位置
                if self.incremental_mode:
                    if len(page_new_cases) == 0:
                        consecutive_known_count += 1
                        if consecutive_known_count >= 3:
                            self.log(f"连续 {consecutive_known_count} 页都是已知案件，停止获取")
                            break
                    else:
                        consecutive_known_count = 0

                if len(cases) < page_size:
                    self.log(f"第{page}页返回 {len(cases)} 个案例（少于页大小），已获取全部")
                    break
                if page >= 100:
                    self.log("已达到最大页数限制（100页），停止获取")
                    break

                page += 1
                time.sleep(random.uniform(*self.config["request_interval"]))
            except Exception as e:
                self.log(f"获取第{page}页时出错: {str(e)}")
                break

        # 新案件编号追加到已知集合并保存
        if new_cases:
            new_nos = set()
            for case in new_cases:
                no = case.get("cpws_al_no", "").strip() or case.get("cpws_al_title", "").strip()
                if no:
                    new_nos.add(no)
            known_nos.update(new_nos)
            self.save_known_nos(known_nos)
            self.log(f"已更新已知案件编号，新增 {len(new_nos)} 条")

        if all_cases:
            if new_cases:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                incremental_file = self.base_dir / self.config["json_dir"] / f"incremental_{timestamp}.json"
                incremental_data = {
                    "code": 0,
                    "data": {
                        "datas": new_cases,
                        "total": len(new_cases),
                        "page_size": page_size,
                        "pages": (len(new_cases) + page_size - 1) // page_size,
                        "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                }
                with open(incremental_file, "w", encoding="utf-8") as f:
                    json.dump(incremental_data, f, ensure_ascii=False, indent=2)
                self.log(f"新案件保存到: {incremental_file}")

            output_file = self.base_dir / self.config["json_dir"] / "initial_response.json"
            merged_data = {
                "code": 0,
                "data": {
                    "datas": all_cases,
                    "total": len(all_cases),
                    "page_size": page_size,
                    "pages": (len(all_cases) + page_size - 1) // page_size,
                    "new_count": len(new_cases),
                    "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
            }
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(merged_data, f, ensure_ascii=False, indent=2)

            self.log(f"获取完成: 总数 {len(all_cases)}, 新案件 {len(new_cases)}")
            return merged_data
        else:
            self.log("未获取到任何案例数据")
            return None

    def fetch_case_content(self, case_id):
        """获取案例内容（达到每日上限时返回特殊标记）。"""
        url = f"{API_BASE_URL}/content"
        payload = {"gid": case_id}
        try:
            response = requests.post(url, headers=self.get_headers(), json=payload, timeout=30, verify=True)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 0:
                error_msg = data.get("msg", "")
                if any(kw in error_msg for kw in ["上限", "超出", "每日", "下载次数", "超过"]):
                    self.log("=" * 60)
                    self.log("⚠️  已达到每日下载上限！")
                    self.log(f"错误信息: {error_msg}")
                    self.log("=" * 60)
                    return {"daily_limit_reached": True, "error_msg": error_msg}
                self.log(f"获取案例 {case_id} 失败: {error_msg}")
                return None
            return data
        except requests.Timeout:
            self.log(f"获取案例 {case_id} 超时")
            return None
        except Exception as e:
            self.log(f"获取案例 {case_id} 内容时出错: {str(e)}")
            return None

    def save_as_markdown(self, content_data, output_dir: Path) -> bool:
        """将案例内容保存为 Markdown。"""
        try:
            data = content_data.get("data", {}).get("data", {})
            title = data.get("cpws_al_title", "Untitled")
            if not title or title == "Untitled":
                return False

            def clean_html(text):
                text = text.replace("<p>", "").replace("</p>", "")
                text = text.replace("<br/>", "\n")
                text = text.replace("　　　　", "　　")
                return text

            md_content = f"# {title}\n"
            md_content += f"## {data.get('cpws_al_sub_title', '')}\n"
            md_content += f"### 关键字\n{' '.join(data.get('cpws_al_keyword', []))}\n"
            md_content += f"### 基本案情\n{clean_html(data.get('cpws_al_jbaq', ''))}\n"
            md_content += f"### 裁判理由\n{clean_html(data.get('cpws_al_cply', ''))}\n"
            md_content += f"### 裁判要旨\n{clean_html(data.get('cpws_al_cpyz', ''))}\n"
            md_content += f"### 关联索引\n{clean_html(data.get('cpws_al_glsy', ''))}\n"
            md_content += f"#### 案件信息\n{data.get('cpws_al_infos', '')}\n"

            safe_title = self.sanitize_filename(title)
            output_file = output_dir / f"{safe_title}.md"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(md_content)
            self.log(f"成功保存案例: {output_file.name}")
            return True
        except Exception as e:
            self.log(f"保存Markdown文件时出错: {str(e)}")
            return False

    def run(self) -> bool:
        """运行主流程：获取列表 → 下载详情（即时整理）。"""
        self.log("法院案例数据处理程序启动")
        if not self.config["token"]:
            self.log("错误: 未提供token")
            return False
        if not self.fetch_case_list():
            return False

        download_result = self.download_case_details()
        if download_result in ["limit_reached", "consecutive_failed"]:
            self.log("下载中断")
            return True
        elif download_result is False:
            self.log("没有新文件需要处理")
            return False

        self.log("所有处理流程完成")
        return True

    def run_organize_only(self) -> bool:
        """仅运行整理流程。"""
        self.log("开始整理案例文件...")
        result = self.organize_case_files()
        self.log("整理完成" if result else "整理失败或没有需要整理的文件")
        return result


# ===== 交互式输入函数 =====

def get_case_type_choice() -> str:
    """交互式选择案件类型，返回类型代码。"""
    print("\n请选择案件类型:")
    case_list = list(CASE_TYPES.items())
    for i, (code, (sort_id, name)) in enumerate(case_list, 1):
        print(f"  {i}. {name} ({code})")
    while True:
        try:
            choice = input(f"\n请输入选项 (1-{len(case_list)}) 或直接输入类型代码: ").strip()
            if choice in CASE_TYPES:
                return choice
            choice_num = int(choice)
            if 1 <= choice_num <= len(case_list):
                return case_list[choice_num - 1][0]
            print(f"无效输入，请输入 1-{len(case_list)} 之间的数字")
        except ValueError:
            print("无效输入，请输入数字")
        except KeyboardInterrupt:
            print("\n\n操作已取消")
            sys.exit(0)


def get_token_input() -> str:
    """交互式获取 token。"""
    print("\n请输入token（可从浏览器开发者工具获取 faxin-cpws-al-token）")
    while True:
        try:
            token = input("token: ").strip()
            if token:
                return token
            print("token不能为空，请重新输入")
        except KeyboardInterrupt:
            print("\n\n操作已取消")
            sys.exit(0)


def get_target_dir_input(case_type_name: str) -> str:
    """交互式获取目标目录地址。"""
    print("\n请输入目标目录地址（用于存放整理后的案例文件）")
    print(f"      例如: /Users/你的用户名/Documents/律师材料/人民法院案例库/{case_type_name}")
    while True:
        try:
            target_dir = input("\n目标目录地址: ").strip()
            if not target_dir:
                print("目标目录地址不能为空，请重新输入")
                continue
            target_path = Path(target_dir)
            if any(char in str(target_path) for char in ["\0", "\n", "\r"]):
                print("路径包含非法字符，请重新输入")
                continue
            try:
                os.makedirs(target_path, exist_ok=True)
                print(f"\n目录已准备就绪: {target_path}")
                return str(target_path)
            except PermissionError:
                print("权限不足，无法在该目录创建文件夹，请重新输入")
            except Exception as e:
                print(f"目录创建失败: {e}，请检查路径")
        except KeyboardInterrupt:
            print("\n\n操作已取消")
            sys.exit(0)


def _ensure_target_dir(src: dict, case_type: str, project_root: Path) -> str:
    """确保 target_dir 已设置，未设置则交互输入并持久化到 local 配置。"""
    target_dir = src.get("target_dir")
    if target_dir:
        return target_dir
    _, case_name = CASE_TYPES[case_type]
    target_dir = get_target_dir_input(case_name)
    from laws_database.config import save_source_local
    save_source_local(project_root, "court_cases", {"target_dir": target_dir})
    src["target_dir"] = target_dir
    return target_dir


# ===== 入口 =====

def run(config: dict):
    """交互式菜单入口（由总菜单调用）。"""
    project_root = Path(config["_project_root"])
    src = config["sources"]["court_cases"]
    data_dir = project_root / src["data_dir"]

    while True:
        print("\n" + "=" * 50)
        print("        人民法院案例库 (PCC)")
        print("=" * 50)
        print("  1. 下载案例（增量）")
        print("  2. 下载案例（全量）")
        print("  3. 仅整理已下载文件")
        print("  4. 统计目标目录文件数")
        print("  5. 设置目标目录")
        print("  0. 返回上级菜单")
        print("=" * 50)
        choice = input("请选择: ").strip()

        if choice == "0":
            break
        try:
            if choice in ("1", "2"):
                incremental = choice == "1"
                token = get_token_input()
                case_type = get_case_type_choice()
                target_dir = _ensure_target_dir(src, case_type, project_root)
                processor = CourtDataProcessor(
                    data_dir, token=token, case_type=case_type, incremental=incremental,
                    target_dir=target_dir, request_interval=src.get("request_interval"),
                    page_size=src.get("page_size", 300), user_agents=src.get("user_agents"),
                )
                _, case_name = CASE_TYPES[case_type]
                print(f"\n已选择: {case_name}案件 | 目标: {target_dir}")
                processor.run()
            elif choice == "3":
                case_type = get_case_type_choice()
                target_dir = _ensure_target_dir(src, case_type, project_root)
                CourtDataProcessor(data_dir, case_type=case_type, target_dir=target_dir).run_organize_only()
            elif choice == "4":
                case_type = get_case_type_choice()
                target_dir = _ensure_target_dir(src, case_type, project_root)
                CourtDataProcessor(data_dir, case_type=case_type, target_dir=target_dir).count_target_files()
            elif choice == "5":
                case_type = get_case_type_choice()
                _ensure_target_dir(src, case_type, project_root)
                print(f"✓ 目标目录已设置: {src['target_dir']}")
            else:
                print("无效选择")
        except KeyboardInterrupt:
            print("\n操作已取消")
        except Exception as e:
            print(f"操作失败: {e}")


def main():
    """命令行入口（python -m laws_database.sources.court_cases）。"""
    parser = argparse.ArgumentParser(description="人民法院案例库数据处理程序", add_help=False)
    parser.add_argument("--count", action="store_true", help="统计目标文件夹中的文件数量")
    parser.add_argument("--organize", action="store_true", help="仅整理已下载文件")
    parser.add_argument("--full", action="store_true", help="全量模式（默认增量）")
    parser.add_argument("--token", type=str, help="提供 token（否则交互输入）")
    parser.add_argument("--help", "-h", action="store_true")
    args = parser.parse_args()

    if args.help:
        print("""
用法: python -m laws_database.sources.court_cases [选项]

选项:
  --count     统计目标文件夹中的文件数量
  --organize  仅整理已下载的文件（不下载新文件）
  --full      全量模式（默认增量模式）
  --token T   提供 token（否则交互输入）
  --help, -h  显示此帮助
        """)
        return

    project_root = Path(__file__).resolve().parent.parent.parent
    from laws_database.config import load_config
    config = load_config(project_root)
    src = config["sources"]["court_cases"]
    data_dir = project_root / src["data_dir"]

    case_type = get_case_type_choice()
    target_dir = _ensure_target_dir(src, case_type, project_root)

    # count/organize 不需要 token（不请求 API），其余需要
    token = args.token or (None if (args.count or args.organize) else get_token_input())
    processor = CourtDataProcessor(
        data_dir, token=token, case_type=case_type, incremental=not args.full,
        target_dir=target_dir, request_interval=src.get("request_interval"),
        page_size=src.get("page_size", 300), user_agents=src.get("user_agents"),
    )

    if args.count:
        processor.count_target_files()
    elif args.organize:
        processor.run_organize_only()
    else:
        processor.run()


if __name__ == "__main__":
    main()
