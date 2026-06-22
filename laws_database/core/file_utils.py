# -*- coding: utf-8 -*-
"""
文件名清理工具
==============

提供跨平台安全的文件名清理函数，统一三个数据源原本各自的实现。

设计边界：本模块只处理"文件系统非法字符"这类通用规则；
各源特有的业务命名规则（如法答网的中文括号转换、法律法规的版本年份后缀）
保留在各 source 模块中，不在此统一，避免把领域知识塞进通用工具。
"""

import re
from typing import Optional

# Windows / Linux 文件系统均不允许出现的字符
# 参考：https://learn.microsoft.com/windows/win32/fileio/naming-a-file
_FORBIDDEN_CHARS_PATTERN = re.compile(r'[\\/:*?"<>|]')

# 文件名单段最大长度（预留扩展名空间，避免触碰部分文件系统 255 字节上限）
_MAX_FILENAME_LENGTH = 200


def sanitize_filename(name: Optional[str], replacement: str = "_") -> str:
    """
    清理文件名中的非法字符，返回跨平台安全的字符串。

    处理规则：
    1. ``None`` 或纯空白返回占位名 "未命名"；
    2. 将 ``\\ / : * ? " < > |`` 替换为 ``replacement``（默认下划线）；
    3. 去除首尾空白；
    4. 超过 :data:`_MAX_FILENAME_LENGTH` 字符则截断；
    5. 清理后若为空（如原名全是非法字符），返回占位名 "未命名"。

    本函数为纯函数：不修改入参，始终返回新字符串。

    Args:
        name: 原始文件名（可能含非法字符）。
        replacement: 用于替换非法字符的字符串，默认 ``"_"``。

    Returns:
        清理后的安全文件名（不含扩展名）。
    """
    if not name or not name.strip():
        return "未命名"

    # 替换文件系统非法字符
    sanitized = _FORBIDDEN_CHARS_PATTERN.sub(replacement, name)
    # 去除首尾空白
    sanitized = sanitized.strip()
    # 长度限制，防止触碰文件系统路径上限
    if len(sanitized) > _MAX_FILENAME_LENGTH:
        sanitized = sanitized[:_MAX_FILENAME_LENGTH]
    # 极端情况：原名全是非法字符且 replacement 经 strip 后为空
    return sanitized if sanitized else "未命名"
