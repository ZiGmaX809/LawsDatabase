#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法律数据库综合工具 - 统一入口
==============================

运行 ``python main.py`` 进入交互式总菜单，选择数据源后进入各自的二级流程：

- **法答网精选答问（FDW）** —— court.gov.cn
- **国家法律法规数据库（FLK）** —— flk.npc.gov.cn
- **人民法院案例库（PCC）** —— rmfyalk.court.gov.cn

各源也支持独立命令行高级模式：

    python -m laws_database.sources.fdw_qa --download
    python -m laws_database.sources.flk_laws --all --fast
    python -m laws_database.sources.court_cases --count

本文件为薄壳，仅加载配置 → 调用 :func:`laws_database.menu.main_loop`。
"""

import sys

from laws_database.menu import main_loop


def main():
    """程序入口。"""
    main_loop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已退出")
        sys.exit(0)
