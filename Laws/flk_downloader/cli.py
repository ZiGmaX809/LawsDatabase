#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
命令行接口模块
处理命令行参数和用户交互
"""

import argparse
import sys
from pathlib import Path

# 导入本包中的模块
from .config import Config
from .downloader import FLKDownloader
from . import LAW_CATEGORIES


def print_usage():
    """打印使用说明"""
    print("""
国家法律法规数据库下载脚本
========================

用法:
    python -m flk_downloader.cli [选项]

选项:
    --category CAT     指定分类 (constitution, law, administrative_regulation,
                       supervision_regulation, local_regulation, judicial_interpretation)
    --all              下载所有分类（排除地方法规）
    --pages N          限制下载页数（用于测试）
    --page-size N      每页获取的数量（默认: 100）
    --fast             快速模式（无延迟，适合批量下载）
    --min-delay SEC    最小延迟时间（秒），默认0
    --max-delay SEC    最大延迟时间（秒），默认0.5，设为0则无延迟
    --concurrent N     并发下载数量（默认: 1）
    --output DIR       指定输出目录（默认: ./laws_data）
    --json-only        仅保存JSON信息，不下载文件（用于获取法律元数据）
    --convert          仅转换已下载的docx文件为markdown
    --file PATH        指定单个docx文件进行转换（需与--convert一起使用）
    --docx-dir PATH    docx文件目录（用于--convert模式）
    --md-dir PATH      markdown输出目录（用于--convert模式）
    --init-db          初始化 law_versions.json 数据库（扫描 JSON 文件）
    --dedup            重命名重复法律的 Markdown 文件（添加年份后缀）
    --dry-run          预览模式，显示将要执行的操作但不实际执行
    --force            强制重新处理所有文件，忽略已处理标记
    --organize         整理 Markdown 文件到配置的目录
    --set-organized-dir PATH  设置整理目录路径
    --db-path PATH     数据库文件路径（默认: configs/law_versions.json）
    --help, -h         显示此帮助信息

分类说明:
    constitution            宪法
    law                    法律
    administrative_regulation  行政法规
    supervision_regulation     监察法规
    local_regulation          地方法规
    judicial_interpretation   司法解释

示例:
    # 只下载宪法
    python -m flk_downloader.cli --category constitution

    # 下载所有分类（排除地方法规）
    python -m flk_downloader.cli --all --fast

    # 设置整理目录
    python -m flk_downloader.cli --set-organized-dir /path/to/organized

    # 整理 Markdown 文件
    python -m flk_downloader.cli --organize

依赖安装:
    pip install requests python-docx
""")


def is_interactive():
    """检测是否在交互式终端中运行"""
    return sys.stdin.isatty()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='国家法律法规数据库下载脚本',
        add_help=False
    )
    parser.add_argument('--category', action='append', dest='categories',
                       help='指定分类')
    parser.add_argument('--all', action='store_true',
                       help='下载所有分类（排除地方法规）')
    parser.add_argument('--pages', type=int, default=None,
                       help='限制下载页数')
    parser.add_argument('--page-size', type=int, default=100,
                       help='每页获取的数量（默认: 100）')
    parser.add_argument('--min-delay', type=float, default=0,
                       help='最小延迟时间（秒），默认0')
    parser.add_argument('--max-delay', type=float, default=0.5,
                       help='最大延迟时间（秒），默认0.5，设为0则无延迟')
    parser.add_argument('--concurrent', type=int, default=1,
                       help='并发下载数量（默认: 1）')
    parser.add_argument('--fast', action='store_true',
                       help='快速模式：无延迟，适合批量下载')
    parser.add_argument('--output', type=str, default='./laws_data',
                       help='输出目录')
    parser.add_argument('--json-only', action='store_true',
                       help='仅保存JSON信息，不下载文件（用于获取法律元数据）')
    parser.add_argument('--convert', action='store_true',
                       help='仅转换已下载的docx文件为markdown')
    parser.add_argument('--file', type=str,
                       help='指定单个docx文件进行转换（与--convert一起使用）')
    parser.add_argument('--docx-dir', type=str,
                       help='docx文件目录（用于--convert模式）')
    parser.add_argument('--md-dir', type=str,
                       help='markdown输出目录（用于--convert模式）')
    parser.add_argument('--init-db', action='store_true',
                       help='初始化 law_versions.json 数据库（扫描 JSON 文件）')
    parser.add_argument('--dedup', action='store_true',
                       help='重命名重复法律的 Markdown 文件')
    parser.add_argument('--dry-run', action='store_true',
                       help='预览模式，显示将要执行的操作但不实际执行')
    parser.add_argument('--force', action='store_true',
                       help='强制重新处理所有文件，忽略已处理标记')
    parser.add_argument('--organize', action='store_true',
                       help='整理 Markdown 文件到配置的目录')
    parser.add_argument('--set-organized-dir', type=str, metavar='PATH',
                       help='设置整理目录路径')
    parser.add_argument('--db-path', type=str,
                       help='数据库文件路径（默认: configs/law_versions.json）')
    parser.add_argument('--help', '-h', action='store_true',
                       help='显示帮助信息')

    args = parser.parse_args()

    # 显示帮助
    if args.help:
        print_usage()
        return 0

    # 初始化配置管理器
    config = Config(project_root=Path(args.output).parent)

    # 处理 --set-organized-dir 参数
    if args.set_organized_dir:
        organized_dir = Path(args.set_organized_dir).expanduser().resolve()
        
        # 创建目录（如果不存在）
        organized_dir.mkdir(parents=True, exist_ok=True)
        
        if config.set_organized_dir(str(organized_dir)):
            print(f"✓ 整理目录已设置为: {organized_dir}")
            
            # 询问是否立即整理
            markdown_dir = config.default_data_dir / "markdown"
            if markdown_dir.exists() and is_interactive():
                try:
                    organize_now = input("\n是否立即整理现有的 Markdown 文件? (y/n): ").strip().lower()
                    if organize_now == 'y':
                        config.organize_markdown_files(dry_run=False)
                except (EOFError, KeyboardInterrupt):
                    pass
            return 0
        else:
            print("错误: 设置整理目录失败")
            return 1

    # 创建下载器
    downloader = FLKDownloader(output_dir=args.output, page_size=args.page_size,
                               min_delay=args.min_delay, max_delay=args.max_delay)

    # 初始化数据库模式
    if args.init_db:
        db_path = args.db_path if args.db_path else None
        downloader.init_law_versions_db(db_path)
        return 0

    # 去重模式
    if args.dedup:
        db_path = args.db_path if args.db_path else None
        downloader.deduplicate_markdown_files(db_path, dry_run=args.dry_run, force=args.force)
        return 0

    # 整理模式
    if args.organize:
        organized_dir = config.get_organized_dir()
        if not organized_dir:
            # 未设置整理目录，提示用户输入
            print("\n" + "=" * 60)
            print("整理目录设置")
            print("=" * 60)
            print("\n请输入整理目录路径，用于存放整理后的 Markdown 文件。")
            print("markdown 文件夹中的所有内容将被复制到该目录。")
            print("\n格式示例:")
            print("  - 绝对路径: /Users/username/Documents/LawsMD")
            print("  - 相对路径: ../LawsMD")
            print("\n按 Enter 跳过，将不启用整理功能。")

            # 使用 Config 类的静态方法
            organized_path_str = Config.prompt_for_organized_dir(interactive=is_interactive())

            if organized_path_str is None:
                # 用户跳过了整理目录设置
                print("\n已跳过整理目录设置，整理功能未启用。")
                return 0

            # 设置整理目录
            if not config.set_organized_dir(organized_path_str):
                print("\n错误: 设置整理目录失败")
                return 1

            organized_dir = Path(organized_path_str)

        print(f"整理目录: {organized_dir}")
        config.organize_markdown_files(dry_run=args.dry_run)
        return 0

    # 转换模式
    if args.convert:
        downloader = FLKDownloader(output_dir=args.output, page_size=args.page_size,
                                    min_delay=args.min_delay, max_delay=args.max_delay)
        if args.file:
            file_path = Path(args.file)
            if not file_path.exists():
                print(f"错误: 文件不存在: {file_path}")
                return 1

            if args.md_dir:
                md_dir = Path(args.md_dir)
            else:
                md_dir = downloader.output_dir / "markdown"

            docx_dir = downloader.output_dir / "docx"
            try:
                rel_path = file_path.relative_to(docx_dir)
            except ValueError:
                rel_path = file_path.name

            if len(rel_path.parts) >= 3:
                category_folder = rel_path.parts[0]
                law_type_folder = rel_path.parts[1]
            elif len(rel_path.parts) == 2:
                category_folder = rel_path.parts[0]
                law_type_folder = ""
            else:
                category_folder = ""
                law_type_folder = ""

            stem = file_path.stem
            parts = stem.rsplit('_', 2)

            if len(parts) >= 2:
                title = parts[0]
                gbrq = parts[1]
                if len(gbrq) == 8:
                    formatted_date = f"{gbrq[:4]}-{gbrq[4:6]}-{gbrq[6:8]}"
                else:
                    formatted_date = gbrq
            else:
                title = stem
                formatted_date = ''

            db_path = downloader.config.law_versions_file
            db = None
            if db_path.exists():
                from .law_versions_db import LawVersionsDB
                db = LawVersionsDB(str(db_path), downloader.output_dir)

            bbbs = parts[2] if len(parts) >= 3 else ""
            md_filename, _ = downloader.ensure_unique_md_filename(
                title, formatted_date, bbbs, category_folder, law_type_folder, db
            )

            if law_type_folder:
                md_file = md_dir / category_folder / law_type_folder / f"{md_filename}.md"
            else:
                md_file = md_dir / category_folder / f"{md_filename}.md"

            os.makedirs(md_file.parent, exist_ok=True)

            json_dir = downloader.output_dir / "json" / "laws"
            json_file = None
            if len(rel_path.parts) >= 2:
                json_file = json_dir / rel_path.parent / f"{file_path.stem}.json"
            if not json_file or not json_file.exists():
                for jf in json_dir.rglob(f"{file_path.stem}.json"):
                    json_file = jf
                    break

            law_info = {}
            if json_file and json_file.exists():
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        law_info = json.load(f)
                except:
                    pass

            success = downloader.convert_docx_to_markdown(file_path, md_file, law_info)
            if success:
                print(f"✓ 转换成功: {md_file}")
                return 0
            else:
                print(f"✗ 转换失败: {file_path}")
                return 1
        else:
            docx_dir = Path(args.docx_dir) if args.docx_dir else None
            md_dir = Path(args.md_dir) if args.md_dir else None
            downloader.convert_existing_docx(docx_dir, md_dir)
        return 0

    # 确定要处理的分类
    if args.all:
        categories = [k for k in LAW_CATEGORIES.keys() if k != 'local_regulation']
    elif args.categories:
        categories = args.categories
        for cat in categories:
            if cat not in LAW_CATEGORIES:
                print(f"错误: 不支持的分类 '{cat}'")
                print(f"支持的分类: {', '.join(LAW_CATEGORIES.keys())}")
                return 1
    else:
        print("错误: 请指定 --category 或 --all")
        print_usage()
        return 1

    # 处理 --fast 参数
    if args.fast:
        min_delay = 0
        max_delay = 0
    else:
        min_delay = args.min_delay
        max_delay = args.max_delay

    # 创建下载器
    downloader = FLKDownloader(output_dir=args.output, page_size=args.page_size,
                                min_delay=min_delay, max_delay=max_delay)

    # 处理分类
    if args.pages:
        total_stats = {}
        for cat in categories:
            total_stats[cat] = downloader.process_category(
                cat,
                max_pages=args.pages,
                save_json_only=args.json_only
            )
    else:
        if args.json_only:
            total_stats = {}
            for cat in categories:
                total_stats[cat] = downloader.process_category(
                    cat,
                    save_json_only=True
                )
        else:
            downloader.process_all(categories)

    return 0


if __name__ == "__main__":
    sys.exit(main())
