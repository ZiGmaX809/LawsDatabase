#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家法律法规数据库下载器包
"""

# 法律分类定义
# flfgCodeId 值来自 API，每个分类对应一个固定的 ID
LAW_CATEGORIES = {
    'constitution': {
        'name': '宪法',
        'flfgCodeId': 100,
    },
    'law': {
        'name': '法律',
        'flfgCodeId': 120,
    },
    'administrative_regulation': {
        'name': '行政法规',
        'flfgCodeId': 210,
    },
    'supervision_regulation': {
        'name': '监察法规',
        'flfgCodeId': 220,
    },
    'local_regulation': {
        'name': '地方法规',
        'flfgCodeId': 310,  # 根据规律推测，实际值可能需要验证
    },
    'judicial_interpretation': {
        'name': '司法解释',
        'flfgCodeId': 320,
    },
}
