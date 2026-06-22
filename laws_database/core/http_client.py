# -*- coding: utf-8 -*-
"""
HTTP 客户端工厂
===============

三个数据源的 HTTP 请求各有差异（法答网 HTML GET、法律法规 POST JSON、
案例库带 token 头），但都复用了"requests.Session + User-Agent + 随机延迟"这套壳。
本模块仅提取这套公共壳，**不做**完整 client 封装——具体请求方法、token 注入、
请求体构造仍由各 source 自行处理。

遵循"优先熟开源方案、避免重复造轮子"：基于成熟的 :mod:`requests`，
不引入额外 HTTP 框架。
"""

import random
import time
from typing import List, Optional, Sequence, Tuple, Union

import requests

# 默认 User-Agent（贴近主流浏览器，降低被简单反爬拦截的概率）
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

# 延迟区间类型：(最小秒, 最大秒)，None 表示不延迟
DelayRange = Optional[Tuple[float, float]]


def make_session(
    user_agents: Optional[Sequence[str]] = None,
    extra_headers: Optional[dict] = None,
) -> requests.Session:
    """
    创建一个复用连接的 :class:`requests.Session`，并预置 User-Agent。

    Args:
        user_agents: 可选的 UA 池。调用方可从中随机选用以分散特征；
            为 ``None`` 时使用 :data:`DEFAULT_USER_AGENT`。
        extra_headers: 额外的默认请求头（如 ``Referer``、``Origin``）。

    Returns:
        配置好默认头的 :class:`requests.Session`。
    """
    session = requests.Session()
    headers = {"User-Agent": pick_user_agent(user_agents)}
    if extra_headers:
        headers.update(extra_headers)
    session.headers.update(headers)
    return session


def pick_user_agent(user_agents: Optional[Sequence[str]]) -> str:
    """
    从 UA 池中随机选一个；池为空则返回默认 UA。

    Args:
        user_agents: UA 池（可为 ``None`` 或空）。

    Returns:
        选中的 User-Agent 字符串。
    """
    if not user_agents:
        return DEFAULT_USER_AGENT
    return random.choice(list(user_agents))


def random_delay(delay_range: DelayRange) -> None:
    """
    在 ``[min, max]`` 秒区间内随机休眠，用于降低请求频率、规避封禁。

    Args:
        delay_range: ``(最小秒, 最大秒)``。``None`` 或 ``hi <= 0`` 时不休眠。
    """
    if not delay_range:
        return
    lo, hi = delay_range
    if hi <= 0:
        return
    time.sleep(random.uniform(max(0.0, lo), hi))
