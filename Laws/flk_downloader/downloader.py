#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载器核心模块
负责从国家法律法规数据库下载法律文件并转换为Markdown格式
"""

import os
import json
import time
import random
import requests
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    from docx import Document
except ImportError:
    Document = None

# 导入本包中的模块
from .config import Config
from .law_versions_db import LawVersionsDB, extract_base_name, extract_year


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

        # 初始化配置管理器
        self.config = Config(project_root=self.output_dir.parent)

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

        # 状态文件 - 使用配置管理器中的路径
        self.state_file = self.config.download_state_file

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

    def extract_gbrq_from_md(self, md_path: Path) -> Optional[str]:
        """
        从 Markdown 文件中提取公布日期

        Args:
            md_path: Markdown 文件路径

        Returns:
            公布日期字符串，格式如 "2021-04-29"，失败返回 None
        """
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 查找公布日期行
            # 格式: - **公布日期**: 2021-04-29
            for line in content.split('\n'):
                line = line.strip()
                if '公布日期' in line and '**' in line:
                    # 提取日期部分
                    match = re.search(r'\*\*公布日期\*\*\s*:\s*(\d{4}-\d{2}-\d{2})', line)
                    if match:
                        return match.group(1)
            return None
        except Exception as e:
            self.log(f"提取公布日期失败 {md_path.name}: {e}")
            return None

    def get_clean_md_filename(self, title: str, category_name: str, law_type_folder: str) -> str:
        """
        获取干净的 Markdown 文件名（去除日期和hash后缀）

        Args:
            title: 法律标题
            category_name: 分类名称
            law_type_folder: 法律类型文件夹

        Returns:
            文件名（不含扩展名）
        """
        safe_title = self.sanitize_filename(title)
        return safe_title

    def ensure_unique_md_filename(self, title: str, gbrq: str, bbbs: str,
                                  category_name: str, law_type_folder: str,
                                  db: LawVersionsDB = None) -> Tuple[str, bool]:
        """
        确保生成唯一的 Markdown 文件名

        逻辑：
        1. 首先尝试使用干净的文件名（无年份后缀）
        2. 如果文件已存在，检查数据库是否有多个版本
        3. 如果有多个版本，需要为所有版本添加年份后缀
        4. 返回最终的文件名和是否进行了重命名操作

        Args:
            title: 法律标题
            gbrq: 公布日期
            bbbs: 唯一标识
            category_name: 分类名称
            law_type_folder: 法律类型文件夹
            db: 法律版本数据库（可选）

        Returns:
            (文件名, 是否重命名了已有文件)
        """
        base_name = extract_base_name(title)
        year = extract_year(gbrq)

        # 构建目录路径
        md_dir = self.output_dir / "markdown" / category_name / law_type_folder

        # 尝试使用干净的文件名
        clean_name = self.sanitize_filename(base_name)
        clean_md_path = md_dir / f"{clean_name}.md"

        # 如果干净的文件名不存在，直接使用
        if not clean_md_path.exists():
            return clean_name, False

        # 文件已存在，需要判断是否有多个版本
        self.log(f"检测到重复文件: {clean_name}.md")

        # 尝试从数据库获取信息
        has_multiple = False
        if db:
            has_multiple = db.has_multiple_versions(base_name)
        else:
            # 没有数据库，检查是否已有带年份的版本
            for existing_file in md_dir.glob(f"{base_name}（*.md"):
                has_multiple = True
                break

        if not has_multiple:
            # 只有一个版本，直接覆盖（可能是更新）
            return clean_name, False

        # 有多个版本，需要处理年份后缀
        self.log(f"法律有多个版本，需要添加年份后缀: {base_name}")

        # 获取当前文件的公布日期
        existing_gbrq = self.extract_gbrq_from_md(clean_md_path)
        if existing_gbrq:
            existing_year = extract_year(existing_gbrq)
            old_name = f"{base_name}（{existing_year}）"
            old_md_path = md_dir / f"{old_name}.md"

            # 如果旧的重命名文件不存在，重命名当前文件
            if not old_md_path.exists():
                try:
                    clean_md_path.rename(old_md_path)
                    self.log(f"已重命名已有文件: {clean_name}.md -> {old_name}.md")

                    # 更新数据库中的路径
                    if db:
                        # 查找对应版本并更新路径
                        law_info = db.get_law_info(base_name)
                        if law_info:
                            for v in law_info.versions:
                                if v.md_path and v.md_path.endswith(f"{clean_name}.md"):
                                    try:
                                        new_rel_path = old_md_path.relative_to(self.output_dir)
                                        v.md_path = str(new_rel_path).replace('\\', '/')
                                    except ValueError:
                                        pass
                            db.save()
                except Exception as e:
                    self.log(f"重命名已有文件失败: {e}")

        # 返回带年份的新文件名
        new_name = f"{base_name}（{year}）"
        return new_name, True

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
            MAX_TOC_LINES = 500  # 增加最大目录行数（民法典目录很长）
            consecutive_article_count = 0  # 连续"第x条"计数
            MIN_CONSECUTIVE_ARTICLES = 3   # 最少连续几个"第x条"才确认正文开始
            toc_ended = False  # 目录是否已结束
            pending_articles = []  # 存储确认阶段的"第x条"

            # 遍历段落
            for para in doc.paragraphs:
                text = para.text.strip()
                if not text:
                    continue

                # 检查是否是目录
                if not toc_ended and (any(keyword in text for keyword in toc_keywords) or re.match(r'目\s*录', text)):
                    in_toc = True
                    toc_buffer = []
                    consecutive_article_count = 0
                    pending_articles = []
                    continue

                # 如果在目录中
                if in_toc:
                    # 检查是否是"第x条"（必须包含具体条文内容，不能只是"第一条"这样的标题）
                    is_article = ('条' in text and text.startswith('第') and
                                  re.match(r'第[一二三四五六七八九十百零千]+条', text) and
                                  len(text) > 20)  # 条文内容应该更长（包含实际法律条文）

                    if is_article:
                        consecutive_article_count += 1
                        pending_articles.append(text)
                        # 达到连续的"第x条"数量，确认正文开始
                        if consecutive_article_count >= MIN_CONSECUTIVE_ARTICLES:
                            # 输出缓存中最后的"编"和"章"（通常是正文真正的起始标题）
                            last_bian = None
                            last_zhang = None
                            for cached_text in reversed(toc_buffer):
                                if not last_bian and '编' in cached_text and cached_text.startswith('第'):
                                    if re.match(r'第[一二三四五六七八九十百零千]+编', cached_text):
                                        last_bian = cached_text
                                elif not last_zhang and '章' in cached_text and cached_text.startswith('第'):
                                    if not any(c in cached_text for c in ['编', '节', '条']):
                                        if re.match(r'第[一二三四五六七八九十百零千]+章', cached_text):
                                            last_zhang = cached_text
                                if last_bian and last_zhang:
                                    break
                            # 输出找到的标题
                            if last_bian:
                                md_content.append(f"### {last_bian}\n\n")
                            if last_zhang:
                                md_content.append(f"### {last_zhang}\n\n")
                            # 输出确认阶段的"第x条"
                            for article in pending_articles:
                                md_content.append(f"{article}\n\n")
                            # 清空缓存
                            toc_buffer = []
                            pending_articles = []
                            in_toc = False
                            toc_ended = True  # 标记目录已结束
                            # 当前这个"第x条"已经在上面的循环中处理了，跳过后续处理
                            continue
                    else:
                        # 不是"第x条"，重置计数
                        consecutive_article_count = 0
                        pending_articles = []
                        # 检查是否超过最大目录行数
                        if len(toc_buffer) >= MAX_TOC_LINES:
                            in_toc = False
                            toc_buffer = []
                        else:
                            toc_buffer.append(text)
                        continue
                    # 如果还在确认中（还没达到连续数量），继续处理下一个段落
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

        转换后的文件保持与docx相同的目录结构:
        markdown/分类名称/法律类型/文件名.md

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

            # 确定目录结构
            if len(rel_path.parts) >= 3:
                # 两层子目录: 分类名称/法律类型/ (新结构)
                # rel_path.parts = (分类名称, 法律类型, 文件名.docx)
                category_folder = rel_path.parts[0]  # 分类名称
                law_type_folder = rel_path.parts[1]  # 法律类型
            elif len(rel_path.parts) == 2:
                # 单层子目录: 法律类型/ 或 分类名称/ (旧结构或特殊情况)
                category_folder = rel_path.parts[0]
                law_type_folder = ""
            else:
                # 没有子目录
                category_folder = ""
                law_type_folder = ""

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

            # 加载法律版本数据库（用于智能命名）
            db_path = self.config.law_versions_file
            db = None
            if db_path.exists():
                db = LawVersionsDB(str(db_path), self.output_dir)

            # 提取 bbbs
            bbbs = parts[2] if len(parts) >= 3 else ""

            # 智能生成 Markdown 文件名
            md_filename, renamed_existing = self.ensure_unique_md_filename(
                title, formatted_date, bbbs, category_folder, law_type_folder, db
            )

            # 构建完整路径
            if law_type_folder:
                md_file = md_dir / category_folder / law_type_folder / f"{md_filename}.md"
            else:
                md_file = md_dir / category_folder / f"{md_filename}.md"

            # 确保父目录存在
            os.makedirs(md_file.parent, exist_ok=True)

            # 检查是否已存在
            if md_file.exists() and not renamed_existing:
                stats['skipped'] += 1
                continue

            # 尝试从JSON文件读取完整元数据（从子目录查找）
            # JSON目录结构与docx相同: json/laws/分类名称/法律类型/
            json_dir = self.output_dir / "json" / "laws"
            json_file = None

            # 先尝试从对应的子目录查找（匹配两层结构: 分类名称/法律类型/）
            if len(rel_path.parts) >= 3:
                # 两层目录: json/laws/分类名称/法律类型/文件名.json
                category_folder = rel_path.parts[0]  # 分类名称
                law_type_folder = rel_path.parts[1]  # 法律类型
                json_file = json_dir / category_folder / law_type_folder / f"{docx_file.stem}.json"
            elif len(rel_path.parts) == 2:
                # 单层子目录（旧结构兼容）
                subfolder = rel_path.parts[0]
                json_file = json_dir / subfolder / f"{docx_file.stem}.json"

            # 如果找不到，递归查找整个json目录
            if json_file is None or not json_file.exists():
                json_file = json_dir / f"{docx_file.stem}.json"
                if not json_file.exists():
                    for jf in json_dir.rglob(f"{docx_file.stem}.json"):
                        json_file = jf
                        break

            law_info = None
            display_title = title

            if json_file and json_file.exists():
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                        # 提取需要的元数据
                        json_title = json_data.get('title', title)
                        json_gbrq = json_data.get('gbrq', formatted_date)

                        # 判断是否需要添加年份后缀
                        base_name = extract_base_name(json_title)
                        if db and db.has_multiple_versions(base_name):
                            display_title = f"{base_name}（{extract_year(json_gbrq)}）"
                        else:
                            display_title = json_title

                        law_info = {
                            'title': display_title,
                            'gbrq': json_gbrq,
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
                # 判断是否需要添加年份后缀
                base_name = extract_base_name(title)
                if db and db.has_multiple_versions(base_name):
                    display_title = f"{base_name}（{extract_year(formatted_date)}）"
                else:
                    display_title = title

                law_info = {
                    'title': display_title,
                    'gbrq': formatted_date,
                    'sxrq': formatted_date,
                    'zdjgName': '',
                    'flxz': '',
                    'bbbs': bbbs,
                    'sxx': 0
                }

            # 转换文件
            if self.convert_docx_to_markdown(docx_file, md_file, law_info):
                stats['converted'] += 1

                # 更新数据库
                if db:
                    try:
                        md_rel_path = md_file.relative_to(self.output_dir)
                        base_name = extract_base_name(law_info.get('title', title))
                        db.register_law(
                            law_info.get('title', title),
                            law_info.get('gbrq', formatted_date),
                            law_info.get('bbbs', bbbs),
                            "",  # file_path 暂时为空
                            str(md_rel_path).replace('\\', '/')
                        )
                        db.save()
                    except (ValueError, Exception):
                        pass
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
                gbrq_formatted = law.get('gbrq', '')
                flxz = law.get('flxz', '未知类型')
                law_type_folder = self.get_law_type_folder(flxz)
                # 获取分类名称
                category_name = LAW_CATEGORIES[category_key]['name']

                # 加载法律版本数据库（用于智能命名）
                db_path = self.config.law_versions_file
                db = None
                if db_path.exists():
                    db = LawVersionsDB(str(db_path), self.output_dir)

                # 智能生成 Markdown 文件名（可能重命名已有文件）
                md_filename, renamed_existing = self.ensure_unique_md_filename(
                    title, gbrq_formatted, bbbs, category_name, law_type_folder, db
                )
                md_filename = f"{md_filename}.md"

                # docx 文件名保持原有格式（带日期和hash）
                docx_filename = f"{safe_title}_{gbrq}_{bbbs[:10]}.docx"

                # 使用两层目录结构: 分类名称/法律类型/
                docx_output = self.output_dir / "docx" / category_name / law_type_folder / docx_filename
                md_output = self.output_dir / "markdown" / category_name / law_type_folder / md_filename

                # 确保子目录存在
                os.makedirs(docx_output.parent, exist_ok=True)
                os.makedirs(md_output.parent, exist_ok=True)

                # 下载文件
                if self.download_docx(download_url, docx_output):
                    # 转换为markdown
                    # 如果文件被重命名过，需要使用新的标题
                    display_title = title
                    if renamed_existing or (db and db.has_multiple_versions(extract_base_name(title))):
                        display_title = f"{extract_base_name(title)}（{extract_year(gbrq_formatted)}）"

                    law_info = {
                        'title': display_title,
                        'bbbs': bbbs,
                        'gbrq': gbrq_formatted,
                        'sxrq': law.get('sxrq') or '',
                        'zdjgName': law.get('zdjgName') or '',
                        'flxz': law.get('flxz') or '未知类型',
                        'sxx': law.get('sxx', 0),
                    }

                    if self.convert_docx_to_markdown(docx_output, md_output, law_info):
                        stats['downloaded'] += 1
                        self.downloaded_files.add(bbbs)

                        # 更新数据库
                        if db:
                            try:
                                md_rel_path = md_output.relative_to(self.output_dir)
                                db.register_law(
                                    title, gbrq_formatted, bbbs,
                                    f"docx/{category_name}/{law_type_folder}/{docx_filename}",
                                    str(md_rel_path).replace('\\', '/')
                                )
                            except ValueError:
                                pass
                            db.save()

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

    def init_law_versions_db(self, db_path: str = None) -> Dict:
        """
        初始化法律版本数据库

        扫描所有 JSON 文件，建立法律版本数据库

        Args:
            db_path: 数据库文件路径，默认为 configs/law_versions.json

        Returns:
            处理统计信息
        """
        if db_path is None:
            db_path = self.config.law_versions_file

        self.log(f"开始初始化法律版本数据库: {db_path}")

        # 创建数据库实例
        db = LawVersionsDB(db_path, self.output_dir)

        # 扫描 JSON 文件目录
        json_dir = self.output_dir / "json" / "laws"
        if not json_dir.exists():
            self.log(f"JSON 目录不存在: {json_dir}")
            return {"error": "JSON 目录不存在"}

        stats = {
            "total_scanned": 0,
            "registered": 0,
            "skipped": 0,
            "errors": 0
        }

        # 递归查找所有 JSON 文件
        json_files = list(json_dir.rglob("*.json"))
        self.log(f"找到 {len(json_files)} 个 JSON 文件")

        for json_file in json_files:
            stats["total_scanned"] += 1

            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 提取必要信息
                title = data.get('title', '')
                gbrq = data.get('gbrq', '')
                bbbs = data.get('bbbs', '')

                if not title or not bbbs:
                    stats["skipped"] += 1
                    continue

                # 计算相对路径
                try:
                    rel_path = json_file.relative_to(self.output_dir)
                    file_path = str(rel_path).replace('\\', '/')
                except ValueError:
                    file_path = str(json_file)

                # 查找对应的 markdown 文件
                md_path = ""
                json_stem = json_file.stem
                md_dir = self.output_dir / "markdown"
                if md_dir.exists():
                    for md_file in md_dir.rglob(f"{json_stem}.md"):
                        try:
                            md_rel = md_file.relative_to(self.output_dir)
                            md_path = str(md_rel).replace('\\', '/')
                            break
                        except ValueError:
                            pass

                # 注册到数据库
                db.register_law(title, gbrq, bbbs, file_path, md_path)
                stats["registered"] += 1

            except Exception as e:
                self.log(f"处理 JSON 文件失败 {json_file.name}: {e}")
                stats["errors"] += 1

        # 保存数据库
        if db.save():
            self.log(f"数据库已保存: {db_path}")
            statistics = db.data.get("statistics", {})
            self.log(f"统计: 唯一法律 {statistics.get('total_unique_laws', 0)}, "
                    f"总版本数 {statistics.get('total_versions', 0)}, "
                    f"有重复 {statistics.get('with_duplicates', 0)}")
        else:
            self.log("保存数据库失败")
            stats["errors"] += 1

        self.log(f"初始化完成: 扫描 {stats['total_scanned']}, "
                f"注册 {stats['registered']}, "
                f"跳过 {stats['skipped']}, "
                f"错误 {stats['errors']}")

        return stats

    def deduplicate_markdown_files(self, db_path: str = None, dry_run: bool = False, force: bool = False) -> Dict:
        """
        重命名重复法律的 Markdown 文件

        对于有多个版本的法律，将文件名和标题添加年份后缀

        Args:
            db_path: 数据库文件路径，默认为 configs/law_versions.json
            dry_run: 预览模式，不实际执行
            force: 强制处理所有文件，包括已处理的

        Returns:
            处理统计信息
        """
        if db_path is None:
            db_path = self.config.law_versions_file

        self.log(f"开始{'预览' if dry_run else '处理'} Markdown 文件去重: {db_path}")

        # 加载数据库
        db = LawVersionsDB(db_path, self.output_dir)

        stats = {
            "total_laws": 0,
            "with_duplicates": 0,
            "files_to_rename": 0,
            "renamed": 0,
            "skipped": 0,
            "errors": 0
        }

        # 获取所有有重复的法律
        laws = db.data.get("laws", {})
        stats["total_laws"] = len(laws)

        for base_name, law_data in laws.items():
            if not law_data.get("has_multiple_versions", False):
                continue

            stats["with_duplicates"] += 1
            versions = law_data.get("versions", [])

            for version in versions:
                # 跳过已处理且非强制模式
                if version.get("processed", False) and not force:
                    stats["skipped"] += 1
                    continue

                md_path = version.get("md_path", "")
                if not md_path:
                    continue

                # 构建完整路径
                full_md_path = self.output_dir / md_path

                if not full_md_path.exists():
                    stats["skipped"] += 1
                    continue

                # 检查当前文件名是否已包含年份
                current_name = full_md_path.stem
                year = version.get("year", "")
                expected_name = f"{base_name}（{year}）"

                if current_name == expected_name:
                    # 已经是正确的名称，标记为已处理
                    if not force:
                        db.mark_processed(base_name, version.get("bbbs", ""))
                    stats["skipped"] += 1
                    continue

                # 需要重命名
                stats["files_to_rename"] += 1

                # 新文件路径
                new_md_name = f"{expected_name}.md"
                new_md_path = full_md_path.parent / new_md_name

                if dry_run:
                    # 预览模式，只输出信息
                    self.log(f"[预览] {md_path} -> {new_md_name}")
                    stats["renamed"] += 1
                else:
                    try:
                        # 重命名文件
                        full_md_path.rename(new_md_path)

                        # 更新 Markdown 文件的标题
                        self._update_markdown_title(new_md_path, expected_name)

                        # 更新数据库中的路径
                        try:
                            new_rel_path = new_md_path.relative_to(self.output_dir)
                            version["md_path"] = str(new_rel_path).replace('\\', '/')
                            version["display_name"] = expected_name
                        except ValueError:
                            pass

                        # 标记为已处理
                        version["processed"] = True

                        self.log(f"已重命名: {md_path} -> {new_md_name}")
                        stats["renamed"] += 1

                    except Exception as e:
                        self.log(f"重命名失败 {md_path}: {e}")
                        stats["errors"] += 1

        # 保存数据库更新
        if not dry_run and stats["renamed"] > 0:
            db.save()

        self.log(f"{'预览' if dry_run else '处理'}完成: "
                f"法律 {stats['total_laws']}, "
                f"有重复 {stats['with_duplicates']}, "
                f"需处理 {stats['files_to_rename']}, "
                f"{'预览' if dry_run else '已处理'} {stats['renamed']}, "
                f"跳过 {stats['skipped']}, "
                f"错误 {stats['errors']}")

        return stats

    def _update_markdown_title(self, md_path: Path, new_title: str):
        """
        更新 Markdown 文件的标题

        Args:
            md_path: Markdown 文件路径
            new_title: 新标题
        """
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 替换第一个 # 标题
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if line.strip().startswith('#'):
                    # 替换标题
                    lines[i] = f"# {new_title}"
                    break

            # 写回文件
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))

        except Exception as e:
            self.log(f"更新 Markdown 标题失败 {md_path.name}: {e}")


