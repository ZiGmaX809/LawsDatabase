# -*- coding: utf-8 -*-
"""
pytest 共享配置
===============

将项目根目录加入 ``sys.path``，使测试无论以 ``pytest tests/`` 还是
``python -m pytest tests/`` 方式运行，都能正确导入 :mod:`laws_database` 包。
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
