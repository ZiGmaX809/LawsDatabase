import os
import json
import shutil
import re
from pathlib import Path
import sys


def sanitize_filename(name):
    """
    清理文件名，移除或替换不适合作为文件名的字符
    """
    # 移除 Windows 文件系统不允许的字符
    # 替换: \ / : * ? " < > |
    sanitized = re.sub(r'[\\/:*?"<>|]', '_', name)
    # 移除前后空格
    sanitized = sanitized.strip()
    # 确保文件名不为空
    if not sanitized:
        sanitized = "未命名"
    return sanitized


def organize_court_files(json_dir_path=None, markdown_dir_path=None, target_dir_path=None):
    # 如果未提供路径，使用默认路径
    if json_dir_path is None:
        json_dir_path = '人民法院案例库/court_data/pages'
    if markdown_dir_path is None:
        markdown_dir_path = '人民法院案例库/downloaded_markdown'
    if target_dir_path is None:
        target_dir_path = '/Users/zigma/Documents/律师材料/知识库/人民法院案例库/民事'

    # 转换为Path对象
    json_dir = Path(json_dir_path)
    markdown_dir = Path(markdown_dir_path)
    target_dir = Path(target_dir_path)

    # 检查路径是否存在
    if not json_dir.exists():
        print(f"错误: JSON目录 '{json_dir}' 不存在。请检查路径。")
        print(f"当前工作目录: {os.getcwd()}")
        return

    if not markdown_dir.exists():
        print(f"错误: Markdown目录 '{markdown_dir}' 不存在。请检查路径。")
        print(f"当前工作目录: {os.getcwd()}")
        return
        
    # 创建目标目录(如果不存在)
    os.makedirs(target_dir, exist_ok=True)

    # 创建一个字典用于映射标题到分类名称
    title_to_sort_name = {}

    # 检查JSON文件
    json_files = list(json_dir.glob('*.json'))
    if not json_files:
        print(f"警告: 在 '{json_dir}' 中没有找到JSON文件。")
        print(
            f"目录内容: {[f.name for f in json_dir.iterdir()] if any(json_dir.iterdir()) else '空目录'}")

        # 尝试使用其他可能的文件
        other_files = list(json_dir.iterdir())
        if other_files:
            print(f"尝试处理目录中的 {len(other_files)} 个文件...")
            json_files = other_files
    else:
        print(f"找到 {len(json_files)} 个JSON文件")

    # 处理所有JSON文件
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                try:
                    # 解析JSON数据
                    data = json.load(f)

                    # 适应提供的JSON结构
                    if 'data' in data and 'datas' in data['data']:
                        # 遍历datas数组中的每个项目
                        for item in data['data']['datas']:
                            if 'cpws_al_sort_name' in item and 'cpws_al_title' in item:
                                title_to_sort_name[item['cpws_al_title']
                                                   ] = item['cpws_al_sort_name']
                    else:
                        # 尝试其他可能的数据结构
                        if isinstance(data, list):
                            for item in data:
                                if 'cpws_al_sort_name' in item and 'cpws_al_title' in item:
                                    title_to_sort_name[item['cpws_al_title']
                                                       ] = item['cpws_al_sort_name']
                        elif 'cpws_al_sort_name' in data and 'cpws_al_title' in data:
                            title_to_sort_name[data['cpws_al_title']
                                               ] = data['cpws_al_sort_name']
                except json.JSONDecodeError:
                    print(f"错误: 文件 '{json_file}' 不是有效的JSON格式。")
        except Exception as e:
            print(f"处理 {json_file} 时出错: {e}")

    print(f"已提取 {len(title_to_sort_name)} 个标题到分类名称的映射")

    # 如果没有找到映射，退出
    if not title_to_sort_name:
        print("没有找到有效的映射，无法进行文件整理。")
        return

    # 查看markdown目录中的文件数量
    markdown_files = list(markdown_dir.iterdir())
    print(f"Markdown目录中有 {len(markdown_files)} 个文件")

    # 创建目标目录并移动/复制文件
    files_copied = 0
    processed_files = set()  # 跟踪已处理的文件，避免重复计数
    unmatched_files = []  # 存储未匹配的文件名
    sort_name_dirs = {}  # 缓存已创建的目录

    for title, sort_name in title_to_sort_name.items():
        # 清理分类名称，确保可以作为有效的目录名
        safe_sort_name = sanitize_filename(sort_name)

        # 如果目标子目录尚未创建，则创建它
        if safe_sort_name not in sort_name_dirs:
            dest_dir = target_dir / safe_sort_name
            os.makedirs(dest_dir, exist_ok=True)
            sort_name_dirs[safe_sort_name] = dest_dir
        else:
            dest_dir = sort_name_dirs[safe_sort_name]

        # 查找具有匹配标题的markdown文件
        # 尝试多种可能的文件名格式
        possible_filenames = [
            f"{title}.md",
            f"{title}案.md",
            f"指导性案例{title.split('指导性案例')[-1]}" if "指导性案例" in title else "",
            f"{title.split('诉')[-1].split('案')[0]}.md" if "诉" in title and "案" in title else ""
        ]
        
        source_file = None
        for filename in possible_filenames:
            if filename:  # 跳过空字符串
                test_file = markdown_dir / filename
                if test_file.exists():
                    source_file = test_file
                    break

        if source_file:
            # 增量移动文件到目标目录(如果文件不存在或已修改)
            dest_file = dest_dir / title
            need_copy = True
            if dest_file.exists():
                # 比较文件修改时间和大小
                src_stat = os.stat(source_file)
                dest_stat = os.stat(dest_file)
                if src_stat.st_mtime <= dest_stat.st_mtime and src_stat.st_size == dest_stat.st_size:
                    need_copy = False
                    
            if need_copy:
                try:
                    shutil.copy2(source_file, dest_file)
                    print(f"已复制: {title} -> {safe_sort_name}/{title}")
                    if str(source_file) not in processed_files:  # 确保文件只被计数一次
                        files_copied += 1
                        processed_files.add(str(source_file))
                except Exception as e:
                    print(f"复制 {title} 时出错: {e}")
        else:
            # 尝试不同的匹配策略
            found_match = False

            # 1. 查找包含标题的文件
            potential_matches = [f for f in markdown_files if title in f.name]

            # 2. 如果没有找到，尝试更宽松的匹配（移除特殊字符后比较）
            if not potential_matches:
                # 清理标题以进行匹配
                clean_title = re.sub(r'[^\w\s]', '', title).strip()
                if clean_title:  # 确保清理后的标题不为空
                    potential_matches = [
                        f for f in markdown_files
                        if clean_title in re.sub(r'[^\w\s]', '', f.name).strip()
                    ]

            # 3. 尝试标题的关键部分
            if not potential_matches and len(title) > 10:
                # 使用标题的一部分（前10个字符）进行匹配
                title_part = title[:10]
                potential_matches = [
                    f for f in markdown_files if title_part in f.name]

            if potential_matches:
                for match in potential_matches:
                    dest_file = dest_dir / match.name
                    try:
                        shutil.copy2(match, dest_file)
                        print(
                            f"已复制（匹配）: {match.name} -> {safe_sort_name}/{match.name}")
                        if str(match) not in processed_files:  # 确保文件只被计数一次
                            files_copied += 1
                            processed_files.add(str(match))
                        found_match = True
                    except Exception as e:
                        print(f"复制 {match.name} 时出错: {e}")

            if not found_match:
                print(f"未找到标题对应的文件: {title}")
                unmatched_files.append({
                    "标题": title,
                    "分类": sort_name
                })

    # 检查是否有任何文件未被处理
    unprocessed_files = [f for f in markdown_files if str(
        f) not in processed_files and f.is_file()]
    if unprocessed_files:
        print(f"\n有 {len(unprocessed_files)} 个文件未被处理:")
        for f in unprocessed_files[:10]:  # 只显示前10个，避免输出过多
            print(f"  - {f.name}")
        if len(unprocessed_files) > 10:
            print(f"  ... 以及 {len(unprocessed_files) - 10} 个更多文件")

    print(f"\n整理完成! 共复制了 {files_copied} 个文件，总共有 {len(markdown_files)} 个文件")

    # 输出未匹配的文件列表
    if unmatched_files:
        print(f"\n未找到匹配文件的条目 ({len(unmatched_files)}个):")
        for i, item in enumerate(unmatched_files, 1):
            print(f"{i}. 标题: {item['标题']}")
            print(f"   分类: {item['分类']}")

        # 将未匹配的文件列表保存到文件中
        try:
            output_file = Path(markdown_dir) / "未匹配文件列表.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"未找到匹配文件的条目 ({len(unmatched_files)}个):\n\n")
                for i, item in enumerate(unmatched_files, 1):
                    f.write(f"{i}. 标题: {item['标题']}\n")
                    f.write(f"   分类: {item['分类']}\n\n")
            print(f"\n未匹配文件列表已保存至: {output_file}")
        except Exception as e:
            print(f"保存未匹配文件列表时出错: {e}")


if __name__ == "__main__":
    # 允许通过命令行参数指定路径
    json_path = sys.argv[1] if len(sys.argv) > 1 else None
    md_path = sys.argv[2] if len(sys.argv) > 2 else None
    target_path = sys.argv[3] if len(sys.argv) > 3 else None

    print("开始整理法院文件...")
    organize_court_files(json_path, md_path, target_path)
