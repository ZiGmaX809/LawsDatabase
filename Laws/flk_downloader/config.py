#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块
负责管理所有配置文件路径和首次运行设置
"""

import json
import shutil
from pathlib import Path
from typing import Dict, Optional


class Config:
    """
    配置管理类
    负责管理所有配置文件路径和首次运行设置
    """

    # 配置文件名
    CONFIG_FILE = "config.json"
    DOWNLOAD_STATE_FILE = "download_state.json"
    LAW_VERSIONS_FILE = "law_versions.json"

    def __init__(self, project_root: Path = None):
        """
        初始化配置管理器

        Args:
            project_root: 项目根目录，默认为脚本所在目录的父目录
        """
        if project_root is None:
            # 获取脚本所在目录
            script_dir = Path(__file__).parent.parent.absolute()
            self.project_root = script_dir
        else:
            self.project_root = Path(project_root)

        # configs 目录路径
        self.configs_dir = self.project_root / "configs"

        # 配置文件路径
        self.config_file = self.configs_dir / self.CONFIG_FILE
        self.download_state_file = self.configs_dir / self.DOWNLOAD_STATE_FILE
        self.law_versions_file = self.configs_dir / self.LAW_VERSIONS_FILE

        # 默认数据目录
        self.default_data_dir = self.project_root / "laws_data"

        # 确保configs目录存在
        self._ensure_configs_dir()

    def _ensure_configs_dir(self):
        """确保configs目录存在"""
        self.configs_dir.mkdir(parents=True, exist_ok=True)

    def is_first_run(self) -> bool:
        """
        检测是否为首次运行

        Returns:
            bool: 如果配置文件不存在则为首次运行
        """
        return not self.config_file.exists()

    def load_config(self) -> Dict:
        """
        加载配置文件

        Returns:
            配置字典
        """
        if not self.config_file.exists():
            return {}

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"警告: 加载配置文件失败: {e}")
            return {}

    def save_config(self, config: Dict) -> bool:
        """
        保存配置文件

        Args:
            config: 配置字典

        Returns:
            bool: 是否保存成功
        """
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"错误: 保存配置文件失败: {e}")
            return False

    def get_organized_dir(self) -> Optional[Path]:
        """
        获取整理目录路径

        Returns:
            整理目录的Path对象，如果未设置则返回None
        """
        config = self.load_config()
        organized_path = config.get('organized_dir')
        if organized_path:
            return Path(organized_path)
        return None

    def set_organized_dir(self, path: str) -> bool:
        """
        设置整理目录路径

        Args:
            path: 整理目录路径

        Returns:
            bool: 是否设置成功
        """
        config = self.load_config()
        config['organized_dir'] = str(path)
        return self.save_config(config)

    def migrate_existing_files(self, dry_run: bool = False) -> Dict:
        """
        迁移现有文件到configs目录

        Args:
            dry_run: 是否为预览模式

        Returns:
            迁移统计信息
        """
        stats = {
            'download_state': False,
            'law_versions': False,
            'errors': []
        }

        # 检查并迁移 download_state.json
        old_state_file = self.default_data_dir / "download_state.json"
        if old_state_file.exists():
            if not dry_run:
                try:
                    shutil.copy2(old_state_file, self.download_state_file)
                    stats['download_state'] = True
                    print(f"✓ 已迁移 download_state.json")
                except Exception as e:
                    stats['errors'].append(f"迁移 download_state.json 失败: {e}")
            else:
                stats['download_state'] = True
                print(f"[预览] 将迁移 download_state.json")

        # 检查并迁移 law_versions.json
        old_versions_file = self.default_data_dir / "law_versions.json"
        if old_versions_file.exists():
            if not dry_run:
                try:
                    shutil.copy2(old_versions_file, self.law_versions_file)
                    stats['law_versions'] = True
                    print(f"✓ 已迁移 law_versions.json")
                except Exception as e:
                    stats['errors'].append(f"迁移 law_versions.json 失败: {e}")
            else:
                stats['law_versions'] = True
                print(f"[预览] 将迁移 law_versions.json")

        return stats

    @staticmethod
    def prompt_for_organized_dir(interactive: bool = True) -> Optional[str]:
        """
        询问用户设置整理目录

        Args:
            interactive: 是否为交互式模式，非交互式时自动跳过

        Returns:
            用户输入的目录路径，如果用户跳过则返回None
        """
        # 非交互式模式直接返回 None
        if not interactive:
            return None

        print("\n" + "=" * 60)
        print("整理目录设置")
        print("=" * 60)
        print("\n您可以设置一个整理目录，用于存放整理后的 Markdown 文件。")
        print("markdown 文件夹中的所有内容将被复制到该目录。")
        print("\n格式示例:")
        print("  - 绝对路径: /Users/username/Documents/LawsMD")
        print("  - 相对路径: ../LawsMD")
        print("\n如果不设置，可以直接按 Enter 跳过。")

        while True:
            try:
                user_input = input("\n请输入整理目录路径: ").strip()

                if not user_input:
                    print("已跳过整理目录设置。")
                    return None

                # 验证路径
                from pathlib import Path
                organized_path = Path(user_input).expanduser().resolve()

                # 询问是否创建目录
                if not organized_path.exists():
                    create = input(f"目录 {organized_path} 不存在，是否创建? (y/n): ").strip().lower()
                    if create == 'y':
                        organized_path.mkdir(parents=True, exist_ok=True)
                        print(f"✓ 已创建目录: {organized_path}")
                    else:
                        print("请重新输入路径。")
                        continue

                print(f"✓ 整理目录设置为: {organized_path}")
                return str(organized_path)

            except (EOFError, KeyboardInterrupt):
                # 用户中断输入（非交互式环境或 Ctrl+C）
                print("\n已跳过整理目录设置。")
                return None
            except Exception as e:
                print(f"错误: 无效的路径 - {e}")
                print("请重新输入。")

    def organize_markdown_files(self, dry_run: bool = False) -> Dict:
        """
        整理 Markdown 文件到指定目录

        Args:
            dry_run: 是否为预览模式

        Returns:
            操作统计信息
        """
        organized_dir = self.get_organized_dir()
        if not organized_dir:
            return {'error': '未设置整理目录'}

        source_dir = self.default_data_dir / "markdown"
        if not source_dir.exists():
            return {'error': 'markdown 源目录不存在'}

        stats = {
            'dirs_created': 0,
            'files_copied': 0,
            'errors': []
        }

        print(f"\n{'=' * 60}")
        if dry_run:
            print(f"[预览模式] 整理 Markdown 文件")
        else:
            print(f"整理 Markdown 文件")
        print(f"{'=' * 60}")
        print(f"源目录: {source_dir}")
        print(f"目标目录: {organized_dir}")

        # 遍历源目录中的所有文件和子目录
        for item in source_dir.rglob('*'):
            if item.is_file():
                # 计算相对路径
                try:
                    rel_path = item.relative_to(source_dir)
                    dest_path = organized_dir / rel_path

                    # 创建目标目录
                    dest_path.parent.mkdir(parents=True, exist_ok=True)

                    if dry_run:
                        print(f"[预览] {rel_path}")
                        stats['files_copied'] += 1
                    else:
                        try:
                            shutil.copy2(item, dest_path)
                            stats['files_copied'] += 1
                            if stats['files_copied'] % 100 == 0:
                                print(f"已复制 {stats['files_copied']} 个文件...")
                        except Exception as e:
                            stats['errors'].append(f"{rel_path}: {e}")

                except ValueError:
                    stats['errors'].append(f"{item.name}: 无法计算相对路径")

        if not dry_run:
            print(f"\n✓ 整理完成: 共复制 {stats['files_copied']} 个文件")
            if stats['errors']:
                print(f"警告: {len(stats['errors'])} 个文件复制失败")

        return stats
