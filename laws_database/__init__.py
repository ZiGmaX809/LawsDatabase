# -*- coding: utf-8 -*-
"""
法律数据库综合工具包
====================

整合三个法律数据源的抓取与整理工具：
- 法答网精选答问（FDW）  —— court.gov.cn
- 国家法律法规数据库（FLK） —— flk.npc.gov.cn
- 人民法院案例库（PCC）  —— rmfyalk.court.gov.cn

公共逻辑（HTTP、日志、文件名清理、下载记录去重）抽取到 :mod:`laws_database.core`，
各数据源实现位于 :mod:`laws_database.sources`，统一入口见根目录 ``main.py``。
"""

__version__ = "2.0.0"
