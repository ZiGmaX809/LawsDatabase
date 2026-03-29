import os
import sys
import json
import time
import random
import requests
import shutil
import re
import argparse
from pathlib import Path
from datetime import datetime
from urllib.parse import unquote
from bs4 import BeautifulSoup

class CourtDataProcessor:
    """法院案例数据处理主程序"""

    # 案件类型配置：类型名称 -> (sort_id, 中文说明)
    CASE_TYPES = {
        "criminal": ("10000", "刑事"),
        "civil": ("20000", "民事"),
        "administrative": ("30000", "行政"),
        "execution": ("40000", "执行"),
        "compensation": ("50000", "国家赔偿")
    }

    def __init__(self, token=None, case_type=None, incremental=True):
        # 基础配置
        self.base_dir = Path(__file__).parent
        self.config = self.load_config()
        self.incremental_mode = incremental  # 是否启用增量获取模式

        # 日志文件 - 需要在set_case_type之前初始化，因为set_case_type会调用log
        self.logs_dir = self.base_dir / "court_data" / "logs"
        os.makedirs(self.logs_dir, exist_ok=True)
        self.log_file = self.logs_dir / f"processor_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        # 如果提供了命令行token，则覆盖配置文件中的token
        if token:
            self.config["token"] = token

        # 设置案件类型
        if case_type:
            self.set_case_type(case_type)

        # 初始化目录
        self.init_dirs()

    def set_case_type(self, case_type):
        """
        设置案件类型
        Args:
            case_type: 案件类型代码（criminal/civil/administrative/execution/compensation）
        """
        if case_type not in self.CASE_TYPES:
            raise ValueError(f"不支持的案件类型: {case_type}，支持的类型: {list(self.CASE_TYPES.keys())}")

        sort_id, type_name = self.CASE_TYPES[case_type]
        self.config["case_sort_id"] = sort_id
        self.config["case_type_code"] = case_type
        self.config["case_type_name"] = type_name

        # 更新配置中的目录路径，添加案件类型分类
        self.config["markdown_dir"] = f"downloaded_markdown/{type_name}"
        self.config["json_dir"] = f"court_data/pages/{type_name}"
        # target_dir 需要用户通过交互式输入设置，不再自动生成

        self.log(f"已设置案件类型: {type_name} ({case_type}), sort_id: {sort_id}")
        self.log(f"配置已更新 - case_type_code: {self.config['case_type_code']}")
        self.log(f"配置已更新 - json_dir: {self.config['json_dir']}")
        self.log(f"配置已更新 - markdown_dir: {self.config['markdown_dir']}")
        
    def load_config(self):
        """加载配置文件"""
        config_path = self.base_dir / "court_config.json"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 确保配置文件中没有token（安全考虑）
                if "token" in config:
                    del config["token"]
                return config

        # 默认配置
        return {
            "page_size": 300,
            "case_sort_id": "20000",  # 民事20000 执行40000 刑事10000 行政30000 国家赔偿50000
            "json_dir": "court_data/pages",
            "markdown_dir": "downloaded_markdown",
            "target_dir": "",  # 默认空，需要用户通过交互式输入设置
            "user_agents": [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15"
            ],
            "request_interval": [3, 5]  # 请求间隔秒数范围
        }
    
    def init_dirs(self):
        """初始化所需目录"""
        dirs = [
            self.base_dir / self.config["json_dir"],
            self.base_dir / self.config["markdown_dir"],
            self.base_dir / "downloaded_records",  # 下载记录文件夹
            self.logs_dir  # 日志文件夹（已在__init__中创建）
        ]

        # target_dir 可能为空（用户尚未设置），此时跳过
        if self.config.get("target_dir"):
            dirs.append(Path(self.config["target_dir"]))

        for dir_path in dirs:
            os.makedirs(dir_path, exist_ok=True)
    
    def log(self, message):
        """记录日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} - {message}"

        print(log_entry)
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry + "\n")

    def get_state_file_path(self):
        """获取状态文件路径"""
        case_type_code = self.config.get("case_type_code", "civil")
        state_file = self.base_dir / f"court_data" / f"case_state_{case_type_code}.json"
        self.log(f"状态文件路径: {state_file} (case_type_code: {case_type_code})")
        return state_file

    def get_known_nos_file_path(self):
        """获取已知案件编号记录文件路径（用 cpws_al_no 做稳定标识）"""
        case_type_code = self.config.get("case_type_code", "civil")
        return self.base_dir / "downloaded_records" / f"known_case_nos_{case_type_code}.txt"

    def load_known_nos(self):
        """从 txt 文件加载已知案件编号集合（cpws_al_no）"""
        nos_file = self.get_known_nos_file_path()
        if nos_file.exists():
            with open(nos_file, 'r', encoding='utf-8') as f:
                nos = {line.strip() for line in f if line.strip()}
            self.log(f"已加载 {len(nos)} 个已知案件编号（cpws_al_no）")
            return nos
        self.log("已知案件编号文件不存在，将从零开始")
        return set()

    def save_known_nos(self, nos):
        """将已知案件编号集合追加写入 txt 文件"""
        nos_file = self.get_known_nos_file_path()
        os.makedirs(nos_file.parent, exist_ok=True)
        with open(nos_file, 'w', encoding='utf-8') as f:
            for no in sorted(nos):
                f.write(f"{no}\n")
        self.log(f"已保存 {len(nos)} 个已知案件编号")

    def get_organized_files_record_path(self):
        """获取已整理文件记录路径"""
        case_type_code = self.config.get("case_type_code", "civil")
        return self.base_dir / "court_data" / f"organized_files_{case_type_code}.txt"

    def load_case_state(self):
        """
        加载案件状态
        Returns:
            dict: 包含 known_case_ids 和 last_fetch_time 的状态字典
        """
        state_file = self.get_state_file_path()
        default_state = {
            "known_case_ids": set(),
            "last_fetch_time": None,
            "case_type": self.config.get("case_type_code", "civil")
        }

        if state_file.exists():
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 将列表转换为set，同时对所有ID做URL解码归一化
                    # 防止 state 文件存的是 %3D 而 API 返回的是 = 导致比较失败
                    data["known_case_ids"] = {unquote(id_) for id_ in data.get("known_case_ids", [])}
                    self.log(f"成功加载状态文件: {state_file}")
                    self.log(f"状态文件中的案件类型: {data.get('case_type')}")
                    self.log(f"状态文件中的已知案件数: {len(data['known_case_ids'])}")
                    return data
            except Exception as e:
                self.log(f"加载状态文件失败: {e}，将使用默认状态")
                return default_state

        self.log(f"状态文件不存在: {state_file}，将使用默认状态")
        return default_state

    def save_case_state(self, state):
        """
        保存案件状态
        Args:
            state: 包含 known_case_ids 和 last_fetch_time 的状态字典
        """
        state_file = self.get_state_file_path()
        try:
            # 确保状态文件目录存在
            os.makedirs(state_file.parent, exist_ok=True)

            # 将set转换为列表以便JSON序列化，统一存储URL解码后的ID
            save_data = state.copy()
            save_data["known_case_ids"] = [unquote(id_) for id_ in state["known_case_ids"]]
            save_data["last_fetch_time"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            save_data["case_type"] = self.config.get("case_type_code", "civil")

            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)

            self.log(f"已保存状态文件: {state_file}")
            self.log(f"状态文件中的案件类型: {save_data['case_type']}")
            self.log(f"状态文件中的已知案件数: {len(save_data['known_case_ids'])}")
        except Exception as e:
            self.log(f"保存状态文件失败: {e}")
    
    def sanitize_filename(self, name):
        """清理文件名"""
        sanitized = re.sub(r'[\\/:*?"<>|]', '_', name)
        sanitized = sanitized.strip()
        return sanitized or "未命名"

    def save_config(self):
        """保存配置到文件（只保存需要持久化的配置项，不包括token）"""
        config_path = self.base_dir / "court_config.json"
        try:
            # 定义需要持久化的配置项（不包括token，出于安全考虑）
            persistent_keys = {
                "page_size", "case_sort_id", "json_dir", "markdown_dir",
                "target_dir", "user_agents", "request_interval"
            }

            # 只保存持久化的配置项
            save_config = {}
            for key in persistent_keys:
                if key in self.config:
                    save_config[key] = self.config[key]

            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(save_config, f, ensure_ascii=False, indent=2)
            self.log("配置已保存（token已排除，出于安全考虑）")
        except Exception as e:
            self.log(f"保存配置失败: {str(e)}")

    def get_headers(self):
        """获取请求头"""
        if not self.config["token"]:
            raise ValueError("未提供token，请使用--token参数提供有效的token")

        # 确保 token 是字符串类型且正确编码
        token = str(self.config["token"])

        return {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'User-Agent': random.choice(self.config["user_agents"]),
            'faxin-cpws-al-token': token,
            'Content-Type': 'application/json'
        }
    
    def fetch_case_list(self):
        """
        获取案例列表 - 支持增量获取

        增量模式:
            - 只获取新的案件，跳过已知的案件
            - 自动保存已获取的案件ID

        全量模式:
            - 获取所有案件
            - 更新案件ID记录
        """
        # 用 cpws_al_no 作为稳定标识符，API 的 id 字段每次请求会变化，不可靠
        known_nos = self.load_known_nos()

        mode_str = "增量" if self.incremental_mode else "全量"
        self.log(f"开始获取案例列表 ({mode_str}模式)...")
        self.log(f"已知案件数量: {len(known_nos)}")

        url = "https://rmfyalk.court.gov.cn/cpws_al_api/api/cpwsAl/search"
        page_size = self.config["page_size"]
        page = 1
        all_cases = []
        new_cases = []  # 新案件列表
        consecutive_known_count = 0  # 连续全部已知的页数计数

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
                    "sort_id_cpwsAl": self.config["case_sort_id"]
                }
            }

            try:
                response = requests.post(url, headers=self.get_headers(), json=payload, verify=True)
                response.raise_for_status()
                data = response.json()

                if data.get('code') != 0:
                    self.log(f"获取第{page}页失败: {data.get('msg')}")
                    break

                # 获取当前页的案例数据
                cases = data.get('data', {}).get('datas', [])
                if not cases:
                    self.log(f"第{page}页没有数据，停止获取")
                    break

                page_new_cases = []
                page_known_count = 0

                for case in cases:
                    # 用 cpws_al_no 做存量判断，该字段在同一案件的多次请求中保持不变
                    case_no = case.get('cpws_al_no', '').strip()
                    if not case_no:
                        # 极少数没有 no 的案件，回退用 title 去重
                        case_no = case.get('cpws_al_title', '').strip()
                    all_cases.append(case)
                    if case_no and case_no in known_nos:
                        page_known_count += 1
                    else:
                        page_new_cases.append(case)
                        new_cases.append(case)

                self.log(f"第{page}页: 总数 {len(cases)}, 新案件 {len(page_new_cases)}, 已知 {page_known_count}")

                # 增量模式：连续3页全是已知案件，说明已到达上次获取位置
                if self.incremental_mode:
                    if len(page_new_cases) == 0:
                        consecutive_known_count += 1
                        if consecutive_known_count >= 3:
                            self.log(f"连续 {consecutive_known_count} 页都是已知案件，停止获取")
                            break
                    else:
                        consecutive_known_count = 0

                # 检查是否还有更多数据
                if len(cases) < page_size:
                    self.log(f"第{page}页返回 {len(cases)} 个案例（少于页大小 {page_size}），已获取全部")
                    break

                # API 返回的 total 字段不可靠，设置为最大页数限制防止无限循环
                if page >= 100:
                    self.log(f"已达到最大页数限制（100页），停止获取")
                    break

                page += 1
                time.sleep(random.uniform(*self.config["request_interval"]))

            except Exception as e:
                self.log(f"获取第{page}页时出错: {str(e)}")
                break

        # 将新案件的 cpws_al_no 追加到已知集合并保存
        if new_cases:
            new_nos = set()
            for case in new_cases:
                no = case.get('cpws_al_no', '').strip() or case.get('cpws_al_title', '').strip()
                if no:
                    new_nos.add(no)
            known_nos.update(new_nos)
            self.save_known_nos(known_nos)
            self.log(f"已更新已知案件编号，新增 {len(new_nos)} 条")

        # 保存完整数据（包含新案件）
        if all_cases:
            # 保存新案件到增量文件
            if new_cases:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                incremental_file = self.base_dir / self.config["json_dir"] / f"incremental_{timestamp}.json"
                incremental_data = {
                    "code": 0,
                    "data": {
                        "datas": new_cases,
                        "total": len(new_cases),
                        "page_size": page_size,
                        "pages": (len(new_cases) + page_size - 1) // page_size,
                        "fetch_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                }
                with open(incremental_file, 'w', encoding='utf-8') as f:
                    json.dump(incremental_data, f, ensure_ascii=False, indent=2)
                self.log(f"新案件保存到: {incremental_file}")

            # 保存完整的合并数据到 initial_response.json
            output_file = self.base_dir / self.config["json_dir"] / "initial_response.json"
            merged_data = {
                "code": 0,
                "data": {
                    "datas": all_cases,
                    "total": len(all_cases),
                    "page_size": page_size,
                    "pages": (len(all_cases) + page_size - 1) // page_size,
                    "new_count": len(new_cases),
                    "fetch_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
            }

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(merged_data, f, ensure_ascii=False, indent=2)

            self.log(f"获取完成: 总数 {len(all_cases)}, 新案件 {len(new_cases)}, 已知 {len(all_cases) - len(new_cases)}")
            return merged_data
        else:
            self.log("未获取到任何案例数据")
            return None
    
    def download_case_details(self):
        """
        下载案例详情并转为Markdown
        下载一个文件后立即整理到目标目录

        Returns:
            bool/str: True(成功下载新文件), False(没有新文件或失败),
                     "limit_reached"(达到上限), "consecutive_failed"(连续失败)
        """
        self.log("开始下载案例详情...")

        # 检查是否已设置目标目录
        if not self.config.get("target_dir"):
            self.log("错误: 未设置目标目录，无法整理文件")
            self.log("请重新运行并设置目标目录")
            return False

        json_dir = self.base_dir / self.config["json_dir"]
        markdown_dir = self.base_dir / self.config["markdown_dir"]
        target_dir = Path(self.config["target_dir"])

        # 加载标题到分类的映射（用于实时整理）
        title_to_sort = {}
        for json_file in json_dir.glob('*.json'):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'data' in data and 'datas' in data['data']:
                        for item in data['data']['datas']:
                            if 'cpws_al_title' in item and 'cpws_al_sort_name' in item:
                                title_to_sort[item['cpws_al_title']] = item['cpws_al_sort_name']
            except Exception as e:
                self.log(f"处理JSON文件 {json_file.name} 时出错: {str(e)}")

        if not title_to_sort:
            self.log("警告: 没有找到有效的标题到分类的映射，将无法整理文件")
        else:
            self.log(f"已加载 {len(title_to_sort)} 个标题到分类的映射")

        # 加载已整理文件记录（避免重复整理）
        organized_files = self.load_organized_files_record()

        # 记录已下载的文件 - 按案件类型分类
        case_type_code = self.config.get("case_type_code", "civil")
        record_file = self.base_dir / "downloaded_records" / f"downloaded_records_{case_type_code}.txt"
        downloaded_files = set()

        if record_file.exists():
            with open(record_file, 'r', encoding='utf-8') as f:
                downloaded_files = set(line.strip() for line in f)
            self.log(f"已下载记录文件存在，已跳过 {len(downloaded_files)} 个案例")

        # 处理所有JSON文件
        json_files = [f for f in json_dir.glob('*.json')]
        if not json_files:
            self.log("没有找到JSON文件")
            return False

        success_count = 0
        skipped_count = 0
        organized_count = 0
        failed_count = 0
        total_cases = 0
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 10

        for json_file in sorted(json_files, reverse=True):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                    if 'data' not in data or 'datas' not in data['data']:
                        continue

                    cases_list = data['data']['datas']
                    total_cases += len(cases_list)
                    self.log(f"正在处理 {json_file.name}，共 {len(cases_list)} 个案例")

                    for idx, item in enumerate(cases_list, 1):
                        if 'id' not in item:
                            continue

                        # 检查是否已下载
                        if item['id'][:10] in {x[:10] for x in downloaded_files}:
                            skipped_count += 1
                            continue

                        # 显示当前进度
                        title = item.get('cpws_al_title', '未知标题')[:30]
                        self.log(f"[{idx}/{len(cases_list)}] 正在下载: {title}...")

                        # 下载案例详情
                        case_data = self.fetch_case_content(item['id'])

                        # 检查是否达到每日下载上限
                        if case_data and case_data.get('daily_limit_reached'):
                            self.log(f"已下载 {success_count} 个新案例，跳过 {skipped_count} 个已下载案例，失败 {failed_count} 个")
                            self.log(f"已整理 {organized_count} 个文件")
                            self.log("=" * 60)
                            self.log("达到下载上限，停止下载")
                            self.log(f"本次成功下载 {success_count} 个新文件，已整理 {organized_count} 个")
                            self.log("=" * 60)
                            # 保存已整理文件记录
                            if organized_files:
                                self.save_organized_files_record(organized_files)
                            return "limit_reached"

                        if not case_data:
                            failed_count += 1
                            consecutive_failures += 1
                            # 连续失败达到阈值，停止下载
                            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                                self.log(f"⚠️ 连续 {MAX_CONSECUTIVE_FAILURES} 次下载失败")
                                self.log(f"已下载 {success_count} 个新案例，跳过 {skipped_count} 个已下载案例，失败 {failed_count} 个")
                                self.log(f"已整理 {organized_count} 个文件")
                                self.log("=" * 60)
                                self.log("连续下载失败，停止下载")
                                self.log(f"本次成功下载 {success_count} 个新文件，已整理 {organized_count} 个")
                                self.log("=" * 60)
                                # 保存已整理文件记录
                                if organized_files:
                                    self.save_organized_files_record(organized_files)
                                return "consecutive_failed"
                            continue

                        # 重置连续失败计数
                        consecutive_failures = 0

                        # 保存为Markdown
                        md_file_path = None
                        if self.save_as_markdown(case_data, markdown_dir):
                            success_count += 1

                            # 获取保存的文件路径
                            data_content = case_data.get('data', {}).get('data', {})
                            title = data_content.get('cpws_al_title', '')
                            if title:
                                safe_title = self.sanitize_filename(title)
                                md_file_path = markdown_dir / f"{safe_title}.md"

                                # 立即整理该文件
                                if title_to_sort and md_file_path.exists():
                                    self.log(f"正在整理: {safe_title}.md")
                                    if self.organize_single_file(md_file_path, title_to_sort, target_dir):
                                        organized_count += 1
                                        # 记录已整理的文件
                                        organized_files.add(safe_title)
                                        self.log(f"  已整理并记录: {safe_title}")

                            # 记录已下载
                            case_id_short = item['id'][:10]
                            with open(record_file, 'a', encoding='utf-8') as f:
                                f.write(f"{case_id_short}\n")
                            downloaded_files.add(case_id_short)

                        # 随机间隔
                        time.sleep(random.uniform(*self.config["request_interval"]))

            except Exception as e:
                self.log(f"处理文件 {json_file.name} 时出错: {str(e)}")

        self.log(f"下载完成，共处理 {success_count} 个新案例，跳过 {skipped_count} 个已下载案例，失败 {failed_count} 个，已整理 {organized_count} 个")

        # 保存已整理文件记录
        if organized_files:
            self.save_organized_files_record(organized_files)

        return success_count > 0
    
    def fetch_case_content(self, case_id):
        """获取案例内容"""
        url = "https://rmfyalk.court.gov.cn/cpws_al_api/api/cpwsAl/content"
        payload = {"gid": case_id}

        try:
            # 确保正确处理编码，设置超时时间为30秒
            response = requests.post(url, headers=self.get_headers(), json=payload, timeout=30, verify=True)
            response.raise_for_status()
            data = response.json()

            # 检查是否返回错误信息
            if data.get('code') != 0:
                error_msg = data.get('msg', '')

                # 检查是否超出每日下载上限
                if any(keyword in error_msg for keyword in ['上限', '超出', '每日', '下载次数', '超过']):
                    self.log("=" * 60)
                    self.log("⚠️  已达到每日下载上限！")
                    self.log(f"错误信息: {error_msg}")
                    self.log("=" * 60)
                    # 返回特殊标记，用于中断下载流程
                    return {'daily_limit_reached': True, 'error_msg': error_msg}

                self.log(f"获取案例 {case_id} 失败: {error_msg}")
                return None

            return data

        except requests.Timeout:
            self.log(f"获取案例 {case_id} 超时")
            return None
        except Exception as e:
            self.log(f"获取案例 {case_id} 内容时出错: {str(e)}")
            return None
    
    def save_as_markdown(self, content_data, output_dir):
        """将案例内容保存为Markdown"""
        try:
            data = content_data.get('data', {}).get('data', {})
            title = data.get('cpws_al_title', 'Untitled')

            if not title or title == 'Untitled':
                return False

            # 清理HTML标签
            def clean_html(text):
                text = text.replace("<p>", "").replace("</p>", "")
                text = text.replace("<br/>", "\n")
                text = text.replace("　　　　", "　　")
                return text

            # 构建Markdown内容
            md_content = f"# {title}\n"
            md_content += f"## {data.get('cpws_al_sub_title', '')}\n"
            md_content += f"### 关键字\n{' '.join(data.get('cpws_al_keyword', []))}\n"
            md_content += f"### 基本案情\n{clean_html(data.get('cpws_al_jbaq', ''))}\n"
            md_content += f"### 裁判理由\n{clean_html(data.get('cpws_al_cply', ''))}\n"
            md_content += f"### 裁判要旨\n{clean_html(data.get('cpws_al_cpyz', ''))}\n"
            md_content += f"### 关联索引\n{clean_html(data.get('cpws_al_glsy', ''))}\n"
            md_content += f"#### 案件信息\n{data.get('cpws_al_infos', '')}\n"

            # 保存文件
            safe_title = self.sanitize_filename(title)
            output_file = output_dir / f"{safe_title}.md"

            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(md_content)

            self.log(f"成功保存案例: {output_file.name}")
            return True

        except Exception as e:
            self.log(f"保存Markdown文件时出错: {str(e)}")
            return False

    def organize_single_file(self, md_file, title_to_sort, target_dir):
        """
        整理单个文件到分类目录

        Args:
            md_file: markdown文件路径
            title_to_sort: 标题到分类的映射字典
            target_dir: 目标目录

        Returns:
            bool: 是否成功整理
        """
        # 获取文件名（不含扩展名）
        file_title = md_file.stem

        # 尝试匹配标题
        sort_name = None

        # 直接匹配
        if file_title in title_to_sort:
            sort_name = title_to_sort[file_title]
        else:
            # 尝试模糊匹配
            for title, sn in title_to_sort.items():
                clean_title = self.sanitize_filename(title)
                if file_title == clean_title or file_title in clean_title or clean_title in file_title:
                    sort_name = sn
                    break

        if sort_name:
            safe_sort = self.sanitize_filename(sort_name)
            dest_dir = target_dir / safe_sort
            os.makedirs(dest_dir, exist_ok=True)

            dest_file = dest_dir / md_file.name

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
    
    def load_organized_files_record(self):
        """
        加载已整理文件记录
        Returns:
            set: 已整理文件的文件名集合（不含扩展名）
        """
        record_file = self.get_organized_files_record_path()
        organized = set()

        if record_file.exists():
            try:
                with open(record_file, 'r', encoding='utf-8') as f:
                    organized = set(line.strip() for line in f if line.strip())
                self.log(f"已加载 {len(organized)} 个已整理文件记录")
            except Exception as e:
                self.log(f"加载已整理文件记录失败: {e}")

        return organized

    def save_organized_files_record(self, organized_files):
        """
        保存已整理文件记录
        Args:
            organized_files: 已整理文件的集合
        """
        record_file = self.get_organized_files_record_path()
        try:
            os.makedirs(record_file.parent, exist_ok=True)
            with open(record_file, 'w', encoding='utf-8') as f:
                for filename in sorted(organized_files):
                    f.write(f"{filename}\n")
            self.log(f"已保存 {len(organized_files)} 个已整理文件记录")
        except Exception as e:
            self.log(f"保存已整理文件记录失败: {e}")

    def organize_case_files(self):
        """
        整理案例文件到分类目录

        逻辑：
        1. 加载已整理文件记录，跳过已整理的文件
        2. 从 JSON 文件中提取标题到分类的映射
        3. 扫描 markdown 目录中的所有 .md 文件
        4. 根据标题匹配，将文件复制到对应的分类目录
        5. 保存已整理文件的记录
        6. 对于无法匹配的文件，记录到日志
        """
        # 检查是否已设置目标目录
        if not self.config.get("target_dir"):
            self.log("错误: 未设置目标目录（target_dir）")
            self.log("请使用 --organize 模式重新运行并输入目标目录地址")
            return False

        self.log("开始整理案例文件...")

        # 加载已整理文件记录
        organized_files = self.load_organized_files_record()

        json_dir = self.base_dir / self.config["json_dir"]
        markdown_dir = self.base_dir / self.config["markdown_dir"]
        target_dir = Path(self.config["target_dir"])

        # 检查目录是否存在
        if not json_dir.exists():
            self.log(f"JSON目录 {json_dir} 不存在")
            return False

        if not markdown_dir.exists():
            self.log(f"Markdown目录 {markdown_dir} 不存在")
            return False

        # 创建目标目录
        os.makedirs(target_dir, exist_ok=True)

        # 从JSON文件中提取标题到分类的映射
        title_to_sort = {}

        for json_file in json_dir.glob('*.json'):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                    if 'data' in data and 'datas' in data['data']:
                        for item in data['data']['datas']:
                            if 'cpws_al_title' in item and 'cpws_al_sort_name' in item:
                                title_to_sort[item['cpws_al_title']] = item['cpws_al_sort_name']
            except Exception as e:
                self.log(f"处理JSON文件 {json_file.name} 时出错: {str(e)}")

        if not title_to_sort:
            self.log("没有找到有效的标题到分类的映射")
            return False

        self.log(f"从JSON中提取了 {len(title_to_sort)} 个标题到分类的映射")

        # 扫描markdown目录中的所有文件
        md_files = list(markdown_dir.glob('*.md'))
        self.log(f"在markdown目录中找到 {len(md_files)} 个文件")

        if not md_files:
            self.log("markdown目录中没有文件需要整理")
            return False

        # 过滤掉已整理的文件
        pending_files = [f for f in md_files if f.stem not in organized_files]
        skipped_count = len(md_files) - len(pending_files)

        if skipped_count > 0:
            self.log(f"跳过已整理的 {skipped_count} 个文件")

        if not pending_files:
            self.log("没有需要整理的新文件")
            return False

        self.log(f"待整理文件数: {len(pending_files)}")

        # 整理文件
        sort_dirs = {}
        success_count = 0
        unmatched_files = []
        newly_organized = set()

        for md_file in pending_files:
            # 获取文件名（不含扩展名）
            file_title = md_file.stem

            # 尝试匹配标题
            sort_name = None
            matched_title = None

            # 直接匹配
            if file_title in title_to_sort:
                sort_name = title_to_sort[file_title]
                matched_title = file_title
            else:
                # 尝试模糊匹配（去除文件名中的"案"字等）
                for title, sn in title_to_sort.items():
                    # 清理标题用于比较
                    clean_title = self.sanitize_filename(title)
                    if file_title == clean_title or file_title in clean_title or clean_title in file_title:
                        sort_name = sn
                        matched_title = title
                        break

            if sort_name:
                safe_sort = self.sanitize_filename(sort_name)

                # 创建分类目录
                if safe_sort not in sort_dirs:
                    dest_dir = target_dir / safe_sort
                    os.makedirs(dest_dir, exist_ok=True)
                    sort_dirs[safe_sort] = dest_dir
                else:
                    dest_dir = sort_dirs[safe_sort]

                # 复制文件到目标目录
                dest_file = dest_dir / md_file.name

                try:
                    # 检查目标文件是否已存在（避免重复复制）
                    if dest_file.exists():
                        # 比较文件修改时间，如果源文件更新则覆盖
                        if md_file.stat().st_mtime > dest_file.stat().st_mtime:
                            shutil.copy2(md_file, dest_file)
                            self.log(f"已更新: {md_file.name} -> {safe_sort}/")
                        else:
                            self.log(f"跳过（目标已存在且更新）: {md_file.name}")
                    else:
                        shutil.copy2(md_file, dest_file)
                        self.log(f"已整理: {md_file.name} -> {safe_sort}/")

                    # 记录已整理的文件
                    newly_organized.add(md_file.stem)
                    success_count += 1
                except Exception as e:
                    self.log(f"整理文件 {md_file.name} 时出错: {str(e)}")
            else:
                unmatched_files.append(md_file.name)

        # 保存已整理文件记录
        if newly_organized:
            organized_files.update(newly_organized)
            self.save_organized_files_record(organized_files)

        # 报告未匹配的文件
        if unmatched_files:
            self.log(f"未匹配到分类的文件 ({len(unmatched_files)} 个):")
            for name in unmatched_files[:10]:  # 只显示前10个
                self.log(f"  - {name}")
            if len(unmatched_files) > 10:
                self.log(f"  ... 还有 {len(unmatched_files) - 10} 个文件")

        self.log(f"整理完成，跳过 {skipped_count} 个已整理文件，新处理 {success_count} 个文件")
        return success_count > 0
    
    def count_target_files(self):
        """统计目标文件夹中的文件数量并保存结果"""
        # 检查是否已设置目标目录
        if not self.config.get("target_dir"):
            self.log("错误: 未设置目标目录（target_dir）")
            self.log("请使用 --count 模式重新运行并输入目标目录地址")
            return None

        target_dir = Path(self.config["target_dir"])

        if not target_dir.exists():
            self.log(f"目标目录不存在: {target_dir}")
            return None

        # 统计总文件数和各子目录文件数
        total_count = 0
        dir_stats = {}

        # 遍历目标目录及其所有子目录
        for root, dirs, files in os.walk(target_dir):
            file_count = len(files)
            # 计算相对路径作为目录名
            rel_path = os.path.relpath(root, target_dir)

            if file_count > 0:
                dir_stats[rel_path] = file_count
                total_count += file_count

        # 获取当前时间作为更新时间
        update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        update_date = datetime.now().strftime('%Y-%m-%d')

        # 构建Markdown内容
        md_content = f"# 人民法院案例库统计\n\n"
        md_content += f"## 统计信息\n\n"
        md_content += f"- **更新时间**: {update_time}\n"
        md_content += f"- **总文件数**: {total_count} 个\n"
        md_content += f"- **分类数量**: {len(dir_stats)} 个\n\n"
        md_content += f"## 分类统计\n\n"
        md_content += f"按文件数量降序排列：\n\n"

        # 按文件数量降序排列
        sorted_stats = sorted(dir_stats.items(), key=lambda x: x[1], reverse=True)
        for i, (dir_name, count) in enumerate(sorted_stats, 1):
            md_content += f"{i}. **{dir_name}**: {count} 个文件\n"

        # 保存统计结果到Markdown文件（按日期命名，覆盖旧的）
        stats_file = target_dir / f"统计信息_{update_date}.md"
        try:
            with open(stats_file, 'w', encoding='utf-8') as f:
                f.write(md_content)
            self.log(f"统计结果已保存到: {stats_file}")
        except Exception as e:
            self.log(f"保存统计结果时出错: {str(e)}")

        # 输出统计结果到控制台和日志
        self.log("=" * 60)
        self.log(f"目标目录统计: {target_dir}")
        self.log(f"更新时间: {update_time}")
        self.log("=" * 60)
        self.log(f"总文件数: {total_count}")
        self.log(f"分类数量: {len(dir_stats)}")
        self.log("-" * 60)

        # 按文件数量降序显示各子目录统计（显示前20个）
        for i, (dir_name, count) in enumerate(sorted_stats[:20], 1):
            self.log(f"{i:2d}. {dir_name}: {count} 个文件")

        if len(sorted_stats) > 20:
            self.log(f"... 还有 {len(sorted_stats) - 20} 个分类")

        self.log("=" * 60)
        return total_count

    def run(self):
        """运行主流程"""
        self.log("法院案例数据处理程序启动")

        # 检查是否有token
        if not self.config["token"]:
            self.log("错误: 未提供token，请使用--token参数提供有效的token")
            return False

        # 1. 获取案例列表
        if not self.fetch_case_list():
            return False

        # 2. 下载案例详情（下载一个整理一个）
        download_result = self.download_case_details()
        # download_result 可能是: True(成功), False(没有新文件), "limit_reached"(达到上限), "consecutive_failed"(连续失败)

        if download_result in ["limit_reached", "consecutive_failed"]:
            self.log("下载中断")
            return True
        elif download_result is False:
            self.log("没有新文件需要处理")
            return False

        self.log("所有处理流程完成")
        return True

    def run_organize_only(self):
        """仅运行整理流程"""
        self.log("开始整理案例文件...")
        result = self.organize_case_files()
        if result:
            self.log("整理完成")
        else:
            self.log("整理失败或没有需要整理的文件")
        return result

def get_case_type_choice():
    """
    交互式选择案件类型
    Returns:
        str: 案件类型代码
    """
    print("\n请选择要下载的案件类型:")
    case_list = list(CourtDataProcessor.CASE_TYPES.items())
    for i, (code, (sort_id, name)) in enumerate(case_list, 1):
        print(f"  {i}. {name} ({code})")

    while True:
        try:
            choice = input(f"\n请输入选项 (1-{len(case_list)}) 或直接输入类型代码: ").strip()

            # 尝试直接输入类型代码
            if choice in CourtDataProcessor.CASE_TYPES:
                return choice

            # 尝试输入数字选项
            choice_num = int(choice)
            if 1 <= choice_num <= len(case_list):
                return case_list[choice_num - 1][0]

            print(f"无效输入，请输入 1-{len(case_list)} 之间的数字")
        except ValueError:
            print("无效输入，请输入数字")
        except KeyboardInterrupt:
            print("\n\n操作已取消")
            sys.exit(0)


def get_token_input():
    """
    交互式获取token
    Returns:
        str: 用户输入的token
    """
    print("\n请输入token")
    print("提示: token可从浏览器开发者工具中获取")
    print("      1. 打开浏览器开发者工具 (F12)")
    print("      2. 切换到 Application/存储 标签")
    print("      3. 查看 Cookies 或 Local Storage")
    print("      4. 找到 faxin-cpws-al-token 的值")

    while True:
        try:
            token = input("\ntoken: ").strip()
            if token:
                return token
            print("token不能为空，请重新输入")
        except KeyboardInterrupt:
            print("\n\n操作已取消")
            sys.exit(0)


def get_target_dir_input(case_type_name):
    """
    交互式获取目标目录地址
    Args:
        case_type_name: 案件类型中文名称（如"刑事"、"民事"等）
    Returns:
        str: 用户输入的目标目录路径
    """
    print("\n请输入目标目录地址（用于存放整理后的案例文件）")
    print(f"提示: 建议为不同案件类型创建独立目录")
    print(f"      例如: /Users/你的用户名/Documents/律师材料/人民法院案例库/{case_type_name}")
    print("\n操作提示:")
    print("  - Mac用户: 在Finder中右键点击文件夹 -> 按住Option键 -> 将'xxx'拷贝为路径名称")
    print("  - 或者直接拖拽文件夹到终端窗口")

    while True:
        try:
            target_dir = input(f"\n目标目录地址: ").strip()

            if not target_dir:
                print("目标目录地址不能为空，请重新输入")
                continue

            # 验证路径格式（基本检查）
            target_path = Path(target_dir)

            # 检查路径是否包含非法字符（跨平台兼容）
            if any(char in str(target_path) for char in ['\0', '\n', '\r']):
                print("路径包含非法字符，请重新输入")
                continue

            # 尝试创建或验证目录
            try:
                os.makedirs(target_path, exist_ok=True)
                print(f"\n目录已准备就绪: {target_path}")
                return str(target_path)
            except PermissionError:
                print("权限不足，无法在该目录创建文件夹，请重新输入")
            except Exception as e:
                print(f"目录创建失败: {e}")
                print("请检查路径是否正确，或选择其他目录")

        except KeyboardInterrupt:
            print("\n\n操作已取消")
            sys.exit(0)


def main():
    """主函数 - 交互式流程"""
    print("=" * 60)
    print(" " * 15 + "人民法院案例库数据处理程序")
    print("=" * 60)

    # 命令行参数
    parser = argparse.ArgumentParser(
        description='人民法院案例库数据处理程序',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False  # 禁用默认帮助，自定义帮助信息
    )
    parser.add_argument('--config', type=str, help='可选的配置文件路径')
    parser.add_argument('--count', action='store_true', help='统计目标文件夹中的文件数量')
    parser.add_argument('--organize', action='store_true', help='仅整理已下载的文件（不下载新文件）')
    parser.add_argument('--full', action='store_true', help='全量模式：获取所有案件（默认增量模式）')
    parser.add_argument('--help', '-h', action='store_true', help='显示帮助信息')

    args = parser.parse_args()

    # 显示帮助信息
    if args.help:
        print("""
用法: python court_data_processor.py [选项]

选项:
  --config PATH    可选的配置文件路径
  --count          统计目标文件夹中的文件数量
  --organize       仅整理已下载的文件（不下载新文件）
  --full           全量模式：获取所有案件（默认增量模式）
  --help, -h       显示此帮助信息

交互式流程:
  1. 输入token（从浏览器开发者工具获取）
  2. 选择要下载的案件类型
  3. 输入目标目录地址（用于存放整理后的案例文件）
  4. 自动执行下载和整理流程

Token获取说明:
  1. 在浏览器中登录人民法院案例库
  2. 打开开发者工具 (F12)
  3. 切换到 Application/存储 标签
  4. 查看 Cookies 或 Local Storage
  5. 找到 faxin-cpws-al-token 的值并复制
  6. Token会自动保存到配置文件 court_config.json

案件类型说明:
  1. criminal     刑事案件 (sort_id: 10000)
  2. civil        民事案件 (sort_id: 20000)
  3. administrative  行政案件 (sort_id: 30000)
  4. execution    执行案件 (sort_id: 40000)
  5. compensation 国家赔偿案件 (sort_id: 50000)

增量模式说明:
  - 默认启用增量模式，只获取新案件
  - 状态保存在 court_data/case_state_*.json 文件中
  - 使用 --full 参数可切换到全量模式
        """)
        return

    # 确定是否使用增量模式
    incremental_mode = not args.full

    # 如果是统计模式，需要先选择案件类型
    if args.count:
        print("\n[统计模式]")
        case_type = get_case_type_choice()
        processor = CourtDataProcessor(token=None, case_type=case_type)

        # 检查是否需要设置目标目录
        if not processor.config.get("target_dir"):
            _, case_name = CourtDataProcessor.CASE_TYPES[case_type]
            target_dir = get_target_dir_input(case_name)
            processor.config["target_dir"] = target_dir
            # 保存配置
            processor.save_config()

        processor.count_target_files()
        return

    # 如果是整理模式，需要先选择案件类型
    if args.organize:
        print("\n[整理模式]")
        case_type = get_case_type_choice()
        processor = CourtDataProcessor(token=None, case_type=case_type)

        # 检查是否需要设置目标目录
        if not processor.config.get("target_dir"):
            _, case_name = CourtDataProcessor.CASE_TYPES[case_type]
            target_dir = get_target_dir_input(case_name)
            processor.config["target_dir"] = target_dir
            # 保存配置
            processor.save_config()

        processor.run_organize_only()
        print("\n" + "=" * 60)
        print("整理完成！")
        print("=" * 60)
        return

    # 正常下载流程
    print("\n[下载模式]")

    # 检查配置文件中是否已有token
    temp_processor = CourtDataProcessor(token=None, case_type=None)
    existing_token = temp_processor.config.get("token", "").strip()

    if existing_token:
        print("\n检测到配置文件中已有保存的token")
        use_existing = input("是否使用已保存的token? (y/n，默认y): ").strip().lower()
        if use_existing in ['', 'y', 'yes']:
            token = existing_token
            print(f"已使用已保存的token: {token[:10]}...")
        else:
            # 获取新的token
            token = get_token_input()
    else:
        # 获取token
        token = get_token_input()

    # 选择案件类型
    case_type = get_case_type_choice()

    # 实例化处理器（先不设置target_dir）
    processor = CourtDataProcessor(token=token, case_type=case_type, incremental=incremental_mode)

    # 检查是否需要设置目标目录
    if not processor.config.get("target_dir"):
        _, case_name = CourtDataProcessor.CASE_TYPES[case_type]
        target_dir = get_target_dir_input(case_name)
        processor.config["target_dir"] = target_dir
        # 保存配置（包含target_dir）
        processor.save_config()

    # 显示确认信息
    _, case_name_final = CourtDataProcessor.CASE_TYPES[case_type]
    print(f"\n已选择: {case_name_final}案件")
    print(f"目标目录: {processor.config['target_dir']}")
    print(f"token: {token[:10]}..." if len(token) > 10 else f"token: {token}")
    print("\n开始处理...")

    # 运行处理流程
    processor.run()

    print("\n" + "=" * 60)
    print("处理完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()