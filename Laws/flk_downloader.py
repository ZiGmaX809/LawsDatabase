#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家法律法规数据库下载脚本
从 https://flk.npc.gov.cn 下载法律文件并转换为Markdown格式
"""

import os
import sys
import json
import time
import random
import requests
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple

# 代理设置（如果需要）
# PROXIES = {
#     'http': 'http://127.0.0.1:7890',
#     'https': 'http://127.0.0.1:7890',
# }
PROXIES = {}

# 法律法规分类配置
LAW_CATEGORIES = {
    "constitution": {
        "name": "宪法",
        "flfgCodeId": [100],
        "description": "宪法及修正案"
    },
    "law": {
        "name": "法律",
        "flfgCodeId": [101, 102, 110, 120, 130, 140, 150, 160, 170, 180, 190, 195, 200],
        "description": "全国人大及其常委会制定的法律"
    },
    "administrative_regulation": {
        "name": "行政法规",
        "flfgCodeId": [201, 210, 215],
        "description": "国务院制定的行政法规"
    },
    "supervision_regulation": {
        "name": "监察法规",
        "flfgCodeId": [220],
        "description": "监察委员会制定的监察法规"
    },
    "local_regulation": {
        "name": "地方法规",
        "flfgCodeId": [221, 222, 230, 260, 270, 290, 295, 300, 305, 310],
        "description": "地方性法规"
    },
    "judicial_interpretation": {
        "name": "司法解释",
        "flfgCodeId": [311, 320, 330, 340, 350],
        "description": "最高人民法院、最高人民检察院的司法解释"
    }
}


class FLKDownloader:
    """国家法律法规数据库下载器"""

    # API端点配置
    API_BASE = "https://flk.npc.gov.cn"
    API_ENDPOINTS = {
        "search_list": "/law-search/search/list",
        "detail": "/law-search/search/flfgDetails",
        "preview_link": "/law-search/amazonFile/previewLink",
        "ofd_generate": "/law-search/amazonFile/ofdGenerateLink",
    }

    def __init__(self, output_dir: str = "./laws_data", page_size: int = 100,
                 min_delay: float = 0, max_delay: float = 0.5, concurrent: int = 1):
        """
        初始化下载器

        Args:
            output_dir: 输出目录路径
            page_size: 每页获取的数量
            min_delay: 最小延迟时间（秒），0表示无延迟
            max_delay: 最大延迟时间（秒）
            concurrent: 并发下载数量
        """
        self.output_dir = Path(output_dir)
        self.page_size = page_size
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.concurrent = concurrent
        self.session = requests.Session()

        # 设置请求头
        self.headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Content-Type': 'application/json;charset=UTF-8',
            'Origin': 'https://flk.npc.gov.cn',
            'Referer': 'https://flk.npc.gov.cn/search',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
            'sec-ch-ua': '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
        }

        # 创建必要的目录
        self.init_dirs()

        # 日志文件（放在logs文件夹中）
        os.makedirs(self.output_dir / "logs", exist_ok=True)
        self.log_file = self.output_dir / "logs" / f"download_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        # 状态文件
        self.state_file = self.output_dir / "download_state.json"

        # 加载下载状态
        self.downloaded_files = self.load_state()

    def init_dirs(self):
        """初始化输出目录结构"""
        dirs = [
            self.output_dir,
            self.output_dir / "docx",
            self.output_dir / "markdown",
            self.output_dir / "json",
            self.output_dir / "json" / "laws",  # 存储单个法律的JSON
        ]
        for dir_path in dirs:
            os.makedirs(dir_path, exist_ok=True)

    def log(self, message: str):
        """记录日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} - {message}"
        print(log_entry)
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry + "\n")

    def load_state(self) -> set:
        """加载下载状态，返回已下载文件的bbbs集合"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    return set(state.get('downloaded', []))
            except Exception as e:
                self.log(f"加载状态文件失败: {e}")
        return set()

    def save_state(self):
        """保存下载状态"""
        try:
            state = {
                'downloaded': list(self.downloaded_files),
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'total_count': len(self.downloaded_files)
            }
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"保存状态文件失败: {e}")

    def sanitize_filename(self, name: str) -> str:
        """
        清理文件名，移除非法字符

        Args:
            name: 原始文件名

        Returns:
            清理后的文件名
        """
        # 移除或替换非法字符
        illegal_chars = r'[<>:"/\\|?*]'
        sanitized = re.sub(illegal_chars, '_', name)
        # 移除首尾空格
        sanitized = sanitized.strip()
        # 限制文件名长度
        if len(sanitized) > 200:
            sanitized = sanitized[:200]
        return sanitized or "未命名"

    def get_law_type_folder(self, flxz: str) -> str:
        """
        根据法律类型获取文件夹名称

        Args:
            flxz: 法律类型字符串

        Returns:
            安全的文件夹名称
        """
        if not flxz:
            return "未知类型"
        # 清理作为文件夹名
        return self.sanitize_filename(flxz)

    def get_law_list(self, category_key: str, page: int = 1) -> Optional[Dict]:
        """
        获取法律列表

        Args:
            category_key: 分类key（如 'constitution', 'law' 等）
            page: 页码

        Returns:
            API响应数据，失败返回None
        """
        if category_key not in LAW_CATEGORIES:
            self.log(f"错误: 不支持的分类 {category_key}")
            return None

        category = LAW_CATEGORIES[category_key]

        # 构建请求参数
        payload = {
            "searchRange": 1,
            "sxrq": [],
            "gbrq": [],
            "searchType": 2,
            "sxx": [],
            "gbrqYear": [],
            "flfgCodeId": category["flfgCodeId"],
            "zdjgCodeId": [],
            "searchContent": "",
            "orderByParam": {"order": "-1", "sort": ""},
            "pageNum": page,
            "pageSize": self.page_size
        }

        url = f"{self.API_BASE}{self.API_ENDPOINTS['search_list']}"

        try:
            response = self.session.post(
                url,
                headers=self.headers,
                json=payload,
                proxies=PROXIES,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            if data.get('code') == 200:
                total = data.get('total', 0)
                rows = data.get('rows', [])
                self.log(f"获取 {category['name']} 第{page}页: {len(rows)}条，总计 {total} 条")
                return data
            else:
                self.log(f"获取列表失败: {data.get('msg')}")
                return None

        except Exception as e:
            self.log(f"请求失败: {e}")
            return None

    def get_law_detail(self, bbbs: str) -> Optional[Dict]:
        """
        获取法律详情，包含文件路径

        Args:
            bbbs: 法律的唯一标识

        Returns:
            详情数据，失败返回None
        """
        url = f"{self.API_BASE}{self.API_ENDPOINTS['detail']}"

        try:
            response = self.session.get(
                url,
                headers=self.headers,
                params={'bbbs': bbbs},
                proxies=PROXIES,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            if data.get('code') == 200:
                return data.get('data')
            else:
                self.log(f"获取详情失败: {data.get('msg')}")
                return None

        except Exception as e:
            self.log(f"获取详情出错: {e}")
            return None

    def get_download_url(self, file_path: str) -> Optional[str]:
        """
        获取下载URL（使用直接下载API）

        该API直接返回docx文件内容，不需要签名URL

        Args:
            file_path: 文件路径（如 'prod/20180311/xxx.docx'）

        Returns:
            下载URL，失败返回None
        """
        # 确保路径以 / 开头
        if not file_path.startswith('/'):
            file_path = '/' + file_path

        # 使用URL编码
        from urllib.parse import quote
        encoded_path = quote(file_path, safe='')

        # 使用直接下载API：/law-search/file/download
        # 这个API直接返回文件内容，不需要签名URL
        return f"{self.API_BASE}/law-search/file/download?filePath={encoded_path}"

    def download_docx(self, download_url: str, output_path: Path) -> bool:
        """
        下载docx文件

        Args:
            download_url: 下载URL（直接下载API）
            output_path: 输出文件路径

        Returns:
            是否下载成功
        """
        try:
            response = self.session.get(
                download_url,
                headers={'User-Agent': self.headers['User-Agent']},
                proxies=PROXIES,
                timeout=60,
                stream=True
            )
            response.raise_for_status()

            # 检查是否返回了错误
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' in content_type:
                # 可能返回了错误信息
                try:
                    error_data = response.json()
                    if error_data.get('code') == 500:
                        self.log(f"下载失败: {error_data.get('msg', 'Unknown error')}")
                        return False
                except:
                    pass

            # 写入文件
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            self.log(f"下载成功: {output_path.name}")
            return True

        except Exception as e:
            self.log(f"下载失败: {e}")
            return False

    def convert_doc_to_markdown_fallback(self, doc_path: Path, md_path: Path, law_info: Dict) -> bool:
        """
        尝试使用其他方法转换旧版 .doc 文件

        Args:
            doc_path: doc文件路径
            md_path: 输出markdown文件路径
            law_info: 法律信息字典

        Returns:
            是否转换成功
        """
        import platform
        import subprocess

        # 检测操作系统
        system = platform.system()

        # 创建临时转换文件
        temp_docx = doc_path.parent / f"{doc_path.stem}_temp.docx"

        try:
            if system == "Darwin":  # macOS
                # 使用 textutil 转换 .doc 到 .docx
                result = subprocess.run(
                    ['textutil', '-convert', 'docx', '-stdout', str(doc_path)],
                    capture_output=True, timeout=30
                )
                if result.returncode == 0:
                    with open(temp_docx, 'wb') as f:
                        f.write(result.stdout)
                    # 使用转换后的 docx 文件
                    success = self._convert_docx_file(temp_docx, md_path, law_info)
                    # 清理临时文件
                    try:
                        temp_docx.unlink()
                    except:
                        pass
                    return success
            elif system == "Linux":
                # 尝试使用 libreoffice
                result = subprocess.run(
                    ['libreoffice', '--headless', '--convert-to', 'docx',
                     '--outdir', str(doc_path.parent), str(doc_path)],
                    capture_output=True, timeout=30
                )
                temp_docx_path = doc_path.parent / f"{doc_path.stem}.docx"
                if temp_docx_path.exists():
                    success = self._convert_docx_file(temp_docx_path, md_path, law_info)
                    try:
                        temp_docx_path.unlink()
                    except:
                        pass
                    return success

            self.log(f"无法转换.doc文件，系统: {system}，建议安装 LibreOffice 或使用 macOS")
            return False

        except FileNotFoundError:
            self.log(f"转换工具未找到，无法转换.doc文件: {doc_path.name}")
            return False
        except Exception as e:
            self.log(f".doc文件转换失败: {e}")
            return False

    def _convert_docx_file(self, docx_path: Path, md_path: Path, law_info: Dict) -> bool:
        """内部方法：转换已确认是 docx 格式的文件"""
        try:
            from docx import Document
            doc = Document(docx_path)

            # 构建Markdown内容
            md_content = []

            # 添加标题和元数据
            title = law_info.get('title', '未知标题')
            md_content.append(f"# {title}\n")

            # 添加元数据
            md_content.append("## 元数据\n")
            md_content.append(f"- **公布日期**: {law_info.get('gbrq', '未知')}\n")
            md_content.append(f"- **生效日期**: {law_info.get('sxrq', '未知')}\n")
            md_content.append(f"- **制定机关**: {law_info.get('zdjgName', '未知')}\n")
            md_content.append(f"- **法律类型**: {law_info.get('flxz', '未知')}\n")
            # 时效性映射: 1=已废止, 2=已修改, 3=有效, 4=尚未生效
            sxx = law_info.get('sxx', 0)
            sxx_map = {1: '已废止', 2: '已修改', 3: '有效', 4: '尚未生效'}
            shixiaoxing = sxx_map.get(sxx, '未知')
            md_content.append(f"- **时效性**: {shixiaoxing}\n")
            md_content.append(f"- **唯一标识**: {law_info.get('bbbs', '')}\n")
            md_content.append("\n---\n")

            # 添加正文内容
            md_content.append("## 正文\n\n")

            # 跳过目录部分（识别后跳过直到正文开始）
            in_toc = False
            toc_buffer = []
            toc_keywords = ['目录', 'contents', '索引']
            MAX_TOC_LINES = 100

            # 遍历段落
            for para in doc.paragraphs:
                text = para.text.strip()
                if not text:
                    continue

                # 检查是否是目录
                if any(keyword in text for keyword in toc_keywords) or re.match(r'目\s*录', text):
                    in_toc = True
                    toc_buffer = []
                    continue

                # 如果在目录中
                if in_toc:
                    toc_line_count = len(toc_buffer) + 1
                    if ('条' in text and text.startswith('第') and re.match(r'第[一二三四五六七八九十百零千]+条', text)) or toc_line_count > MAX_TOC_LINES:
                        # 找到正文起点，先输出缓存中最后一个"编/章"
                        last_chapter = None
                        for cached_text in reversed(toc_buffer):
                            if cached_text.startswith('第') and ('编' in cached_text or '章' in cached_text):
                                last_chapter = cached_text
                                break
                        if last_chapter:
                            md_content.append(f"### {last_chapter}\n\n")
                        toc_buffer = []
                        in_toc = False
                    else:
                        toc_buffer.append(text)
                        if len(toc_buffer) > MAX_TOC_LINES:
                            in_toc = False
                            toc_buffer = []
                        continue

                # 识别标题层级
                heading_level = None

                if '编' in text and text.startswith('第'):
                    if re.match(r'第[一二三四五六七八九十百零千]+编', text):
                        heading_level = 3
                elif '章' in text and text.startswith('第'):
                    if not any(c in text for c in ['编', '节', '条']) and re.match(r'第[一二三四五六七八九十百零千]+章', text):
                        heading_level = 3
                    else:
                        heading_level = 4
                elif '节' in text and text.startswith('第'):
                    heading_level = 4
                elif text in ['附则', '附录']:
                    heading_level = 3

                # 强制：所有"第x条"都作为普通正文，不作为标题
                if '条' in text and text.startswith('第') and re.match(r'第[一二三四五六七八九十百零千]+条', text):
                    heading_level = None

                if heading_level:
                    md_content.append(f"{'#' * heading_level} {text}\n\n")
                else:
                    md_content.append(f"{text}\n\n")

            # 写入markdown文件
            with open(md_path, 'w', encoding='utf-8') as f:
                f.writelines(md_content)

            self.log(f"转换成功: {md_path.name}")
            return True

        except Exception as e:
            error_msg = str(e)
            if 'relationship' in error_msg.lower():
                self.log(f"转换失败: 文件可能已损坏或格式异常 ({docx_path.name})")
            else:
                self.log(f"转换失败: {e} ({docx_path.name})")
            return False

    def convert_docx_to_markdown(self, docx_path: Path, md_path: Path, law_info: Dict) -> bool:
        """
        将docx/doc文件转换为Markdown格式

        Args:
            docx_path: docx/doc文件路径
            md_path: 输出markdown文件路径
            law_info: 法律信息字典

        Returns:
            是否转换成功
        """
        try:
            import zipfile

            # 检查文件是否是有效的 docx 文件（docx 实际上是 zip 文件）
            is_docx = False
            try:
                with zipfile.ZipFile(docx_path, 'r') as zip_ref:
                    has_doc = any('[Content_Types].xml' in f for f in zip_ref.namelist())
                    if has_doc:
                        is_docx = True
            except (zipfile.BadZipFile, Exception):
                is_docx = False

            if is_docx:
                # 检测为有效的 docx 文件，先尝试直接转换
                result = self._convert_docx_file(docx_path, md_path, law_info)
                if result:
                    return True
                # docx 转换失败，可能是伪装的 doc 格式，尝试 fallback
                self.log(f"docx转换失败，尝试作为.doc文件处理: {docx_path.name}")
                return self.convert_doc_to_markdown_fallback(docx_path, md_path, law_info)
            else:
                # 不是有效的 docx zip 结构，可能是旧版 .doc 格式
                self.log(f"检测到非标准docx格式，尝试作为.doc文件处理: {docx_path.name}")
                return self.convert_doc_to_markdown_fallback(docx_path, md_path, law_info)

        except Exception as e:
            self.log(f"文件转换失败: {e} ({docx_path.name})")
            # 最后尝试 fallback 方法
            self.log(f"最后尝试使用系统工具转换: {docx_path.name}")
            try:
                return self.convert_doc_to_markdown_fallback(docx_path, md_path, law_info)
            except:
                return False

    def save_law_info(self, law: Dict, detail: Dict, category_key: str = None) -> bool:
        """
        保存法律信息到JSON文件

        Args:
            law: 列表中的法律信息
            detail: 详情API返回的数据
            category_key: 分类key（用于确定分类名称子文件夹）

        Returns:
            是否保存成功
        """
        try:
            bbbs = law.get('bbbs') or ''
            title = law.get('title', '未知')

            # 构建完整的信息字典
            law_info = {
                'bbbs': bbbs,
                'title': title,
                'gbrq': law.get('gbrq', ''),
                'sxrq': law.get('sxrq') or '',
                'sxx': law.get('sxx', 0),
                'zdjgName': law.get('zdjgName') or '',
                'flxz': law.get('flxz', ''),
                'zdjgCodeId': law.get('zdjgCodeId', 0),
                'flfgCodeId': law.get('flfgCodeId', 0),
                'detail': detail,
                'fetch_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            # 保存单个文件的JSON
            safe_title = self.sanitize_filename(title)
            gbrq = (law.get('gbrq') or '').replace('-', '')
            flxz = law.get('flxz') or '未知类型'
            law_type_folder = self.get_law_type_folder(flxz)

            # 获取分类名称（两层目录结构: 分类名称/法律类型/）
            if category_key and category_key in LAW_CATEGORIES:
                category_name = LAW_CATEGORIES[category_key]['name']
            else:
                category_name = '未分类'

            json_filename = f"{safe_title}_{gbrq}_{bbbs[:10]}.json"
            json_path = self.output_dir / "json" / "laws" / category_name / law_type_folder / json_filename

            # 确保子目录存在
            os.makedirs(json_path.parent, exist_ok=True)

            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(law_info, f, ensure_ascii=False, indent=2)

            return True

        except Exception as e:
            self.log(f"保存JSON失败: {e}")
            return False

    def convert_existing_docx(self, docx_dir: Path = None, md_dir: Path = None) -> Dict:
        """
        转换已下载的docx文件为Markdown格式

        Args:
            docx_dir: docx文件目录，默认为输出目录/docx
            md_dir: markdown输出目录，默认为输出目录/markdown

        Returns:
            处理统计信息
        """
        if docx_dir is None:
            docx_dir = self.output_dir / "docx"
        if md_dir is None:
            md_dir = self.output_dir / "markdown"

        # 确保输出目录存在
        os.makedirs(md_dir, exist_ok=True)

        self.log(f"开始转换docx文件: {docx_dir}")

        stats = {
            'total': 0,
            'converted': 0,
            'skipped': 0,
            'failed': 0
        }

        # 获取所有docx文件（递归查找子目录）
        docx_files = list(docx_dir.rglob('*.docx'))
        if not docx_files:
            self.log("没有找到docx文件")
            return stats

        self.log(f"找到 {len(docx_files)} 个docx文件")

        for docx_file in docx_files:
            stats['total'] += 1

            # 获取相对于docx_dir的子目录路径（用于确定目录结构）
            rel_path = docx_file.relative_to(docx_dir)
            if len(rel_path.parts) > 1:
                # 有子目录，使用相同的子目录结构保存markdown
                # 新结构: 分类名称/法律类型/
                if len(rel_path.parts) >= 3:
                    # 两层子目录: category/law_type/
                    subfolders = rel_path.parts[0:2]
                    md_file = md_dir
                    for folder in subfolders:
                        md_file = md_file / folder
                    md_file = md_file / f"{docx_file.stem}.md"
                else:
                    # 单层子目录（旧结构兼容）
                    subfolder = rel_path.parts[0]
                    md_file = md_dir / subfolder / f"{docx_file.stem}.md"
                os.makedirs(md_file.parent, exist_ok=True)
            else:
                # 没有子目录，直接保存到md_dir
                md_file = md_dir / f"{docx_file.stem}.md"

            # 从文件名解析基本信息
            # 文件名格式: {标题}_{日期}_{bbbs前10位}.docx
            stem = docx_file.stem
            parts = stem.rsplit('_', 2)

            if len(parts) >= 2:
                title = parts[0]
                gbrq = parts[1]

                # 重建日期格式
                if len(gbrq) == 8:
                    formatted_date = f"{gbrq[:4]}-{gbrq[4:6]}-{gbrq[6:8]}"
                else:
                    formatted_date = gbrq
            else:
                title = stem
                formatted_date = ''

            # 检查是否已存在
            if md_file.exists():
                stats['skipped'] += 1
                continue

            # 尝试从JSON文件读取完整元数据（从子目录查找）
            json_dir = self.output_dir / "json" / "laws"
            json_file = None
            # 先尝试从对应的子目录查找（匹配两层结构）
            if len(rel_path.parts) >= 3:
                subfolders = rel_path.parts[0:2]
                json_file = json_dir
                for folder in subfolders:
                    json_file = json_file / folder
                json_file = json_file / f"{docx_file.stem}.json"
            elif len(rel_path.parts) > 1:
                # 单层子目录（旧结构兼容）
                subfolder = rel_path.parts[0]
                json_file = json_dir / subfolder / f"{docx_file.stem}.json"
            # 如果找不到，递归查找
            if json_file is None or not json_file.exists():
                json_file = json_dir / f"{docx_file.stem}.json"
                if not json_file.exists():
                    for jf in json_dir.rglob(f"{docx_file.stem}.json"):
                        json_file = jf
                        break

            law_info = None

            if json_file and json_file.exists():
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                        # 提取需要的元数据
                        law_info = {
                            'title': json_data.get('title', title),
                            'gbrq': json_data.get('gbrq', formatted_date),
                            'sxrq': json_data.get('sxrq', formatted_date),
                            'zdjgName': json_data.get('zdjgName', ''),
                            'flxz': json_data.get('flxz', ''),
                            'bbbs': json_data.get('bbbs', ''),
                            'sxx': json_data.get('sxx', 0)
                        }
                        self.log(f"从JSON读取元数据: {title}")
                except Exception as e:
                    self.log(f"读取JSON失败: {e}，使用文件名解析")

            # 如果JSON不存在或读取失败，使用文件名解析
            if law_info is None:
                law_info = {
                    'title': title,
                    'gbrq': formatted_date,
                    'sxrq': formatted_date,
                    'zdjgName': '',
                    'flxz': '',
                    'bbbs': '',
                    'sxx': 0
                }

            # 转换文件
            if self.convert_docx_to_markdown(docx_file, md_file, law_info):
                stats['converted'] += 1
            else:
                stats['failed'] += 1

            # 随机延迟（转换模式）
            if self.max_delay > 0:
                delay = max(self.min_delay, random.uniform(0, 0.1))
                time.sleep(delay)

        self.log(f"转换完成: 总计 {stats['total']}, 转换 {stats['converted']}, "
                f"跳过 {stats['skipped']}, 失败 {stats['failed']}")

        return stats

    def process_category(self, category_key: str, max_pages: int = None, save_json_only: bool = False) -> Dict:
        """
        处理指定分类的法律下载

        Args:
            category_key: 分类key
            max_pages: 最大页数，None表示全部
            save_json_only: 仅保存JSON信息，不下载文件（用于下载URL问题未解决时）

        Returns:
            处理统计信息
        """
        category = LAW_CATEGORIES[category_key]
        self.log(f"开始处理分类: {category['name']}")

        stats = {
            'total': 0,
            'downloaded': 0,
            'skipped': 0,
            'failed': 0
        }

        page = 1
        while True:
            # 获取当前页列表
            list_data = self.get_law_list(category_key, page)
            if not list_data:
                break

            rows = list_data.get('rows', [])
            if not rows:
                self.log(f"第{page}页无数据，停止")
                break

            for law in rows:
                stats['total'] += 1
                bbbs = law.get('bbbs') or ''

                # 检查是否已下载
                if bbbs in self.downloaded_files:
                    stats['skipped'] += 1
                    continue

                # 获取详情
                detail = self.get_law_detail(bbbs)
                if not detail:
                    stats['failed'] += 1
                    continue

                # 保存JSON信息
                self.save_law_info(law, detail, category_key)

                # 如果是仅保存JSON模式，跳过下载
                if save_json_only:
                    stats['downloaded'] += 1
                    self.downloaded_files.add(bbbs)
                    # 定期保存状态
                    if stats['downloaded'] % 10 == 0:
                        self.save_state()
                    if self.max_delay > 0:
                        time.sleep(random.uniform(self.min_delay, min(self.max_delay, 1.5)))
                    continue

                # 获取文件路径
                oss_file = detail.get('ossFile', {})
                docx_path = oss_file.get('ossWordPath') or ''

                if not docx_path:
                    self.log(f"无docx文件路径: {law.get('title')}")
                    stats['failed'] += 1
                    continue

                # 获取下载URL
                download_url = self.get_download_url(docx_path)
                if not download_url:
                    stats['failed'] += 1
                    continue

                # 生成文件名
                title = law.get('title', '未知')
                safe_title = self.sanitize_filename(title)
                gbrq = (law.get('gbrq') or '').replace('-', '')
                flxz = law.get('flxz', '未知类型')
                law_type_folder = self.get_law_type_folder(flxz)
                # 获取分类名称
                category_name = LAW_CATEGORIES[category_key]['name']

                docx_filename = f"{safe_title}_{gbrq}_{bbbs[:10]}.docx"
                md_filename = f"{safe_title}_{gbrq}_{bbbs[:10]}.md"

                # 使用两层目录结构: 分类名称/法律类型/
                docx_output = self.output_dir / "docx" / category_name / law_type_folder / docx_filename
                md_output = self.output_dir / "markdown" / category_name / law_type_folder / md_filename

                # 确保子目录存在
                os.makedirs(docx_output.parent, exist_ok=True)
                os.makedirs(md_output.parent, exist_ok=True)

                # 下载文件
                if self.download_docx(download_url, docx_output):
                    # 转换为markdown
                    law_info = {
                        'title': title,
                        'bbbs': bbbs,
                        'gbrq': law.get('gbrq', ''),
                        'sxrq': law.get('sxrq') or '',
                        'zdjgName': law.get('zdjgName') or '',
                        'flxz': law.get('flxz') or '未知类型',
                        'sxx': law.get('sxx', 0),
                    }

                    if self.convert_docx_to_markdown(docx_output, md_output, law_info):
                        stats['downloaded'] += 1
                        self.downloaded_files.add(bbbs)

                        # 定期保存状态
                        if stats['downloaded'] % 10 == 0:
                            self.save_state()
                    else:
                        # 转换失败，删除已下载的文件以便下次重试
                        self.log(f"转换失败，删除文件以便重试: {docx_output.name}")
                        try:
                            docx_output.unlink()
                        except Exception:
                            pass
                        stats['failed'] += 1

                # 随机延迟（避免请求过快，如果设置了延迟）
                if self.max_delay > 0:
                    time.sleep(random.uniform(self.min_delay, self.max_delay))

            # 检查是否还有下一页
            if len(rows) < self.page_size:
                break

            # 检查页数限制
            if max_pages and page >= max_pages:
                break

            # 防止无限循环
            if page >= 1000:
                self.log("达到最大页数限制，停止")
                break

            page += 1
            # 页面间延迟
            if self.max_delay > 0:
                time.sleep(random.uniform(self.min_delay, min(self.max_delay * 2, 4)))

        # 保存状态
        self.save_state()

        self.log(f"分类 {category['name']} 处理完成: 总计 {stats['total']}, "
                f"下载 {stats['downloaded']}, 跳过 {stats['skipped']}, 失败 {stats['failed']}")

        return stats

    def process_all(self, categories: List[str] = None) -> Dict:
        """
        处理所有或指定分类

        Args:
            categories: 分类列表，None表示处理所有分类

        Returns:
            总体统计信息
        """
        if categories is None:
            categories = list(LAW_CATEGORIES.keys())

        total_stats = {
            'categories': len(categories),
            'total': 0,
            'downloaded': 0,
            'skipped': 0,
            'failed': 0
        }

        for category_key in categories:
            stats = self.process_category(category_key)
            for key in ['total', 'downloaded', 'skipped', 'failed']:
                total_stats[key] += stats.get(key, 0)

        self.log(f"全部处理完成: 总计 {total_stats['total']}, "
                f"下载 {total_stats['downloaded']}, 跳过 {total_stats['skipped']}, 失败 {total_stats['failed']}")

        return total_stats


def print_usage():
    """打印使用说明"""
    print("""
国家法律法规数据库下载脚本
========================

用法:
    python flk_downloader.py [选项]

选项:
    --category CAT     指定分类 (constitution, law, administrative_regulation,
                       supervision_regulation, local_regulation, judicial_interpretation)
    --all              下载所有分类
    --pages N          限制下载页数（用于测试）
    --page-size N      每页获取的数量（默认: 100）
    --fast             快速模式（无延迟，适合批量下载）
    --min-delay SEC    最小延迟时间（秒），默认0
    --max-delay SEC    最大延迟时间（秒），默认0.5，设为0则无延迟
    --concurrent N     并发下载数量（默认: 1）
    --output DIR       指定输出目录（默认: ./laws_data）
    --help             显示此帮助信息

分类说明:
    constitution            宪法
    law                    法律
    administrative_regulation  行政法规
    supervision_regulation     监察法规
    local_regulation          地方法规
    judicial_interpretation   司法解释

示例:
    # 只下载宪法
    python flk_downloader.py --category constitution

    # 下载法律和行政法规
    python flk_downloader.py --category law --category administrative_regulation

    # 下载所有分类（限制前2页，每页50条）
    python flk_downloader.py --all --pages 2 --page-size 50

    # 快速模式批量下载（无延迟）
    python flk_downloader.py --all --fast

    # 自定义延迟（每次请求间隔0.1-0.3秒）
    python flk_downloader.py --all --min-delay 0.1 --max-delay 0.3

    # 指定输出目录
    python flk_downloader.py --all --output /path/to/output

    # 仅保存JSON信息（不下载文件，用于获取法律元数据）
    python flk_downloader.py --all --json-only

    # 仅转换已下载的docx文件
    python flk_downloader.py --convert

    # 指定docx目录和markdown输出目录进行转换
    python flk_downloader.py --convert --docx-dir /path/to/docx --md-dir /path/to/markdown

依赖安装:
    pip install requests python-docx

注意事项:
    1. 下载过程中会自动保存状态，支持断点续传
    2. 已下载的文件会被自动跳过
    3. 日志文件保存在输出目录中
    4. 建议使用--pages参数先测试少量数据
    5. --convert 模式可以单独转换已下载的docx文件

转换规则说明:
    - 有"第x编"时，编为 h3
    - 没有"编"时，"第x章"为 h3
    - "第x节"为 h4
    - "第x条"为 h5
    - 自动跳过目录部分
    """)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(
        description='国家法律法规数据库下载脚本',
        add_help=False
    )
    parser.add_argument('--category', action='append', dest='categories',
                       help='指定分类')
    parser.add_argument('--all', action='store_true',
                       help='下载所有分类')
    parser.add_argument('--pages', type=int, default=None,
                       help='限制下载页数')
    parser.add_argument('--page-size', type=int, default=100,
                       help='每页获取的数量（默认: 100）')
    parser.add_argument('--min-delay', type=float, default=0,
                       help='最小延迟时间（秒），默认0')
    parser.add_argument('--max-delay', type=float, default=0.5,
                       help='最大延迟时间（秒），默认0.5，设为0则无延迟')
    parser.add_argument('--concurrent', type=int, default=1,
                       help='并发下载数量（默认: 1）')
    parser.add_argument('--fast', action='store_true',
                       help='快速模式：无延迟，适合批量下载')
    parser.add_argument('--output', type=str, default='./laws_data',
                       help='输出目录')
    parser.add_argument('--json-only', action='store_true',
                       help='仅保存JSON信息，不下载文件（用于获取法律元数据）')
    parser.add_argument('--convert', action='store_true',
                       help='仅转换已下载的docx文件为markdown')
    parser.add_argument('--docx-dir', type=str,
                       help='docx文件目录（用于--convert模式）')
    parser.add_argument('--md-dir', type=str,
                       help='markdown输出目录（用于--convert模式）')
    parser.add_argument('--help', '-h', action='store_true',
                       help='显示帮助信息')

    args = parser.parse_args()

    # 显示帮助
    if args.help:
        print_usage()
        return 0

    # 转换模式：仅转换已下载的docx文件
    if args.convert:
        downloader = FLKDownloader(output_dir=args.output, page_size=args.page_size,
                                    min_delay=args.min_delay, max_delay=args.max_delay)
        docx_dir = Path(args.docx_dir) if args.docx_dir else None
        md_dir = Path(args.md_dir) if args.md_dir else None
        downloader.convert_existing_docx(docx_dir, md_dir)
        return 0

    # 确定要处理的分类
    if args.all:
        categories = list(LAW_CATEGORIES.keys())
    elif args.categories:
        categories = args.categories
        # 验证分类
        for cat in categories:
            if cat not in LAW_CATEGORIES:
                print(f"错误: 不支持的分类 '{cat}'")
                print(f"支持的分类: {', '.join(LAW_CATEGORIES.keys())}")
                return 1
    else:
        print("错误: 请指定 --category 或 --all")
        print_usage()
        return 1

    # 处理 --fast 参数
    if args.fast:
        min_delay = 0
        max_delay = 0
    else:
        min_delay = args.min_delay
        max_delay = args.max_delay

    # 创建下载器
    downloader = FLKDownloader(output_dir=args.output, page_size=args.page_size,
                                min_delay=min_delay, max_delay=max_delay)

    # 处理分类
    if args.pages:
        # 测试模式：限制页数
        total_stats = {}
        for cat in categories:
            total_stats[cat] = downloader.process_category(
                cat,
                max_pages=args.pages,
                save_json_only=args.json_only
            )
    else:
        # 正常模式
        if args.json_only:
            # 仅保存JSON模式
            total_stats = {}
            for cat in categories:
                total_stats[cat] = downloader.process_category(
                    cat,
                    save_json_only=True
                )
        else:
            # 完整下载模式
            downloader.process_all(categories)

    return 0


if __name__ == "__main__":
    sys.exit(main())
