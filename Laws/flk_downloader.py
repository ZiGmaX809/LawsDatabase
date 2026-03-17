#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家法律法规数据库下载脚本 - 主入口
从 https://flk.npc.gov.cn 下载法律文件并转换为Markdown格式

这是脚本的主入口点，实际功能已拆分到 flk_downloader 包中。
使用方式：
    python flk_downloader.py --help
    python flk_downloader.py --all --fast
"""

import sys

# 导入包中的 CLI 模块
from flk_downloader.cli import main

if __name__ == "__main__":
    sys.exit(main())
