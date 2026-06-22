# -*- coding: utf-8 -*-
"""
docx → Markdown 转换器（国家法律法规数据库专用）
================================================

从原 ``flk_downloader.downloader`` 提取的文档转换逻辑，独立为函数模块。
将下载的 docx（或旧版 doc）法律文件转换为结构化 Markdown，
识别目录区并跳过，将"编/章/节"转为对应层级标题，"第x条"作为普通正文。

转换失败时回退到系统工具：macOS 用 ``textutil``，Linux 用 ``libreoffice``。

从原类方法重构为模块级函数，日志通过 :class:`~laws_database.core.logger.Logger`
参数注入，转换逻辑本身保持与原实现一致（功能等价）。
"""

import platform
import re
import subprocess
import zipfile
from pathlib import Path
from typing import Dict

from laws_database.core.logger import Logger

# 中文数字正则片段（编/章/节/条共用），匹配"第x编/章/节/条"
_CN_NUM = r'[一二三四五六七八九十百零千]+'


def convert_docx_to_markdown(
    docx_path: Path, md_path: Path, law_info: Dict, logger: Logger
) -> bool:
    """
    将 docx/doc 文件转换为 Markdown。

    自动识别有效 docx（zip 结构含 ``[Content_Types].xml``）；无效则按旧版 doc
    处理，回退到系统工具（textutil / libreoffice）。

    Args:
        docx_path: docx/doc 文件路径。
        md_path: 输出 Markdown 文件路径。
        law_info: 法律元数据字典（title/gbrq/sxrq/zdjgName/flxz/sxx/bbbs）。
        logger: 日志器。

    Returns:
        是否转换成功。
    """
    try:
        # docx 实际上是 zip 文件，通过该特征判断有效性
        is_docx = False
        try:
            with zipfile.ZipFile(docx_path, "r") as zip_ref:
                if any("[Content_Types].xml" in f for f in zip_ref.namelist()):
                    is_docx = True
        except (zipfile.BadZipFile, Exception):
            is_docx = False

        if is_docx:
            result = _convert_docx_file(docx_path, md_path, law_info, logger)
            if result:
                return True
            # docx 转换失败，可能是伪装的 doc 格式，尝试 fallback
            logger.log(f"docx转换失败，尝试作为.doc文件处理: {docx_path.name}")
            return convert_doc_to_markdown_fallback(docx_path, md_path, law_info, logger)
        else:
            logger.log(f"检测到非标准docx格式，尝试作为.doc文件处理: {docx_path.name}")
            return convert_doc_to_markdown_fallback(docx_path, md_path, law_info, logger)
    except Exception as e:
        logger.log(f"文件转换失败: {e} ({docx_path.name})")
        logger.log(f"最后尝试使用系统工具转换: {docx_path.name}")
        try:
            return convert_doc_to_markdown_fallback(docx_path, md_path, law_info, logger)
        except Exception:
            return False


def convert_doc_to_markdown_fallback(
    doc_path: Path, md_path: Path, law_info: Dict, logger: Logger
) -> bool:
    """
    使用系统工具转换旧版 ``.doc`` 文件为 Markdown。

    - macOS：``textutil -convert docx -stdout``
    - Linux：``libreoffice --headless --convert-to docx``

    Args:
        doc_path: doc 文件路径。
        md_path: 输出 Markdown 文件路径。
        law_info: 法律元数据字典。
        logger: 日志器。

    Returns:
        是否转换成功。
    """
    system = platform.system()
    temp_docx = doc_path.parent / f"{doc_path.stem}_temp.docx"

    try:
        if system == "Darwin":  # macOS
            result = subprocess.run(
                ["textutil", "-convert", "docx", "-stdout", str(doc_path)],
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0:
                with open(temp_docx, "wb") as f:
                    f.write(result.stdout)
                success = _convert_docx_file(temp_docx, md_path, law_info, logger)
                try:
                    temp_docx.unlink()
                except Exception:
                    pass
                return success
        elif system == "Linux":
            result = subprocess.run(
                [
                    "libreoffice", "--headless", "--convert-to", "docx",
                    "--outdir", str(doc_path.parent), str(doc_path),
                ],
                capture_output=True,
                timeout=30,
            )
            temp_docx_path = doc_path.parent / f"{doc_path.stem}.docx"
            if temp_docx_path.exists():
                success = _convert_docx_file(temp_docx_path, md_path, law_info, logger)
                try:
                    temp_docx_path.unlink()
                except Exception:
                    pass
                return success

        logger.log(f"无法转换.doc文件，系统: {system}，建议安装 LibreOffice 或使用 macOS")
        return False

    except FileNotFoundError:
        logger.log(f"转换工具未找到，无法转换.doc文件: {doc_path.name}")
        return False
    except Exception as e:
        logger.log(f".doc文件转换失败: {e}")
        return False


def _convert_docx_file(
    docx_path: Path, md_path: Path, law_info: Dict, logger: Logger
) -> bool:
    """
    内部方法：转换已确认是 docx 格式的文件。

    识别目录区并跳过（直到连续出现 3 个含内容的"第x条"才确认正文开始），
    将"编/章"转为三级标题、"节"转为四级标题，"第x条"作为普通正文。

    Args:
        docx_path: docx 文件路径。
        md_path: 输出 Markdown 文件路径。
        law_info: 法律元数据字典。
        logger: 日志器。

    Returns:
        是否转换成功。
    """
    try:
        from docx import Document

        doc = Document(docx_path)
        md_content = []

        # 标题与元数据
        title = law_info.get("title", "未知标题")
        md_content.append(f"# {title}\n")
        md_content.append("## 元数据\n")
        md_content.append(f"- **公布日期**: {law_info.get('gbrq', '未知')}\n")
        md_content.append(f"- **生效日期**: {law_info.get('sxrq', '未知')}\n")
        md_content.append(f"- **制定机关**: {law_info.get('zdjgName', '未知')}\n")
        md_content.append(f"- **法律类型**: {law_info.get('flxz', '未知')}\n")
        # 时效性映射: 1=已废止, 2=已修改, 3=有效, 4=尚未生效
        sxx = law_info.get("sxx", 0)
        sxx_map = {1: "已废止", 2: "已修改", 3: "有效", 4: "尚未生效"}
        md_content.append(f"- **时效性**: {sxx_map.get(sxx, '未知')}\n")
        md_content.append(f"- **唯一标识**: {law_info.get('bbbs', '')}\n")
        md_content.append("\n---\n")
        md_content.append("## 正文\n\n")

        # 目录识别状态机
        in_toc = False
        toc_buffer = []
        toc_keywords = ["目录", "contents", "索引"]
        max_toc_lines = 500  # 民法典目录很长，放宽上限
        consecutive_article_count = 0
        min_consecutive_articles = 3  # 连续 3 个"第x条"才确认正文开始
        toc_ended = False
        pending_articles = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            # 目录起始检测
            if not toc_ended and (
                any(kw in text for kw in toc_keywords) or re.match(r"目\s*录", text)
            ):
                in_toc = True
                toc_buffer = []
                consecutive_article_count = 0
                pending_articles = []
                continue

            if in_toc:
                # "第x条"需含具体条文内容（len>20）才视为正文起始
                is_article = (
                    "条" in text
                    and text.startswith("第")
                    and re.match(rf"第{_CN_NUM}条", text)
                    and len(text) > 20
                )

                if is_article:
                    consecutive_article_count += 1
                    pending_articles.append(text)
                    if consecutive_article_count >= min_consecutive_articles:
                        # 输出缓存最后的"编/章"作为正文真正起始标题
                        last_bian = None
                        last_zhang = None
                        for cached_text in reversed(toc_buffer):
                            if not last_bian and "编" in cached_text and cached_text.startswith("第"):
                                if re.match(rf"第{_CN_NUM}编", cached_text):
                                    last_bian = cached_text
                            elif not last_zhang and "章" in cached_text and cached_text.startswith("第"):
                                if not any(c in cached_text for c in ["编", "节", "条"]):
                                    if re.match(rf"第{_CN_NUM}章", cached_text):
                                        last_zhang = cached_text
                            if last_bian and last_zhang:
                                break
                        if last_bian:
                            md_content.append(f"### {last_bian}\n\n")
                        if last_zhang:
                            md_content.append(f"### {last_zhang}\n\n")
                        for article in pending_articles:
                            md_content.append(f"{article}\n\n")
                        toc_buffer = []
                        pending_articles = []
                        in_toc = False
                        toc_ended = True
                        continue
                else:
                    # 不是"第x条"，重置计数
                    consecutive_article_count = 0
                    pending_articles = []
                    if len(toc_buffer) >= max_toc_lines:
                        in_toc = False
                        toc_buffer = []
                    else:
                        toc_buffer.append(text)
                    continue
                continue

            # 正文标题层级识别
            heading_level = None
            if "编" in text and text.startswith("第"):
                if re.match(rf"第{_CN_NUM}编", text):
                    heading_level = 3
            elif "章" in text and text.startswith("第"):
                if not any(c in text for c in ["编", "节", "条"]) and re.match(rf"第{_CN_NUM}章", text):
                    heading_level = 3
                else:
                    heading_level = 4
            elif "节" in text and text.startswith("第"):
                heading_level = 4
            elif text in ["附则", "附录"]:
                heading_level = 3

            # 强制：所有"第x条"都作为普通正文，不作为标题
            if "条" in text and text.startswith("第") and re.match(rf"第{_CN_NUM}条", text):
                heading_level = None

            if heading_level:
                md_content.append(f"{'#' * heading_level} {text}\n\n")
            else:
                md_content.append(f"{text}\n\n")

        with open(md_path, "w", encoding="utf-8") as f:
            f.writelines(md_content)

        logger.log(f"转换成功: {md_path.name}")
        return True

    except Exception as e:
        error_msg = str(e)
        if "relationship" in error_msg.lower():
            logger.log(f"转换失败: 文件可能已损坏或格式异常 ({docx_path.name})")
        else:
            logger.log(f"转换失败: {e} ({docx_path.name})")
        return False
