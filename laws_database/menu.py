# -*- coding: utf-8 -*-
"""
交互式总菜单
============

第一层路由：选择数据源后，控制权交给各源的二级交互流程。
菜单本身不含任何业务逻辑，避免成为上帝模块（各源逻辑留在各自模块）。

每个数据源模块暴露 ``run(config)`` 入口，由 :func:`dispatch` 路由调用。
"""

import sys

from laws_database.sources import court_cases, fdw_qa, flk_laws

# 菜单项：(源 key, 显示标题, run 函数)
_MENU_ITEMS = [
    ("fdw", "法答网精选答问 (FDW)", fdw_qa.run),
    ("flk", "国家法律法规数据库 (FLK)", flk_laws.run),
    ("pcc", "人民法院案例库 (PCC)", court_cases.run),
]


def show_main_menu():
    """
    显示总菜单并返回用户选择的源 key。

    Returns:
        源 key 字符串（如 ``"fdw"``），或 ``None`` 表示退出。
    """
    print("\n" + "=" * 50)
    print("           法律数据库综合工具")
    print("=" * 50)
    for i, (_, title, _) in enumerate(_MENU_ITEMS, 1):
        print(f"  {i}. {title}")
    print("  0. 退出")
    print("=" * 50)

    while True:
        try:
            choice = input("请选择: ").strip()
            if choice == "0":
                return None
            # 支持数字选项
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(_MENU_ITEMS):
                    return _MENU_ITEMS[idx - 1][0]
            # 也支持直接输入源 key
            for key, _, _ in _MENU_ITEMS:
                if choice == key:
                    return key
            print("无效选择，请重新输入")
        except (EOFError, KeyboardInterrupt):
            return None


def dispatch(source_key: str, config: dict) -> bool:
    """
    根据源 key 路由到对应的 ``run(config)``。

    Args:
        source_key: 源 key（fdw / flk / pcc）。
        config: 统一配置字典。

    Returns:
        是否成功路由（未知 key 返回 False）。
    """
    for key, _, run_fn in _MENU_ITEMS:
        if key == source_key:
            try:
                run_fn(config)
            except KeyboardInterrupt:
                print("\n已中断")
            return True
    print(f"未知的数据源: {source_key}")
    return False


def main_loop():
    """主循环：反复显示菜单直到用户选择退出。"""
    from laws_database.config import load_config

    config = load_config()
    while True:
        source = show_main_menu()
        if source is None:
            print("\n再见！")
            break
        dispatch(source, config)


if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        print("\n已退出")
        sys.exit(0)
