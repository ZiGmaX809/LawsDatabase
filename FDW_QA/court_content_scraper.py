import requests
from bs4 import BeautifulSoup
import markdown
from urllib.parse import urljoin
import time
import random
import os
import json
from pathlib import Path


def fetch_page(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Connection': 'keep-alive'
    }
    try:
        # 添加随机延迟防止被封
        time.sleep(random.uniform(1, 3))
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        response.encoding = 'utf-8'
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None


def parse_links(html):
    if not html:
        return []

    soup = BeautifulSoup(html, 'html.parser')
    # 尝试多种可能的class名称
    search_list = soup.find('div', class_='search_list') or \
        soup.find('div', class_='search-list') or \
        soup.find('div', class_='searchList')

    if not search_list:
        print("Could not find search list div")
        return []

    links = []
    for li in search_list.find_all('li'):
        a_tag = li.find('a')
        if a_tag and a_tag.has_attr('href'):
            links.append(a_tag['href'])
    return links


def get_safe_filename(title):
    """
    根据标题生成安全的文件名

    转换规则（将原始标题转换为统一格式）：
    - 法答网精选答问（第三批）→ 法答网精选答问(第三批）
    - 法答网精选答问（第三十五批）——商事审判专题 → 法答网精选答问(第三十五批-商事审判专题）

    Args:
        title: 原始标题字符串

    Returns:
        str: 安全的文件名（不包含文件扩展名）
    """
    if not title:
        return "unknown"

    # 移除 Markdown 标题符号（如果存在）
    title = title.lstrip('#').strip()

    # 按照目标格式进行转换
    # 1. 将开头的 "法答网精选答问（" 替换为 "法答网精选答问("
    # 2. 将 "）——" 替换为 "-"
    # 3. 将其他非法字符（Windows/Linux文件系统不允许的字符）替换为下划线
    filename = title

    # 替换括号为统一格式：外层中文括号（），内层方括号【】
    if '——' in filename:
        # 处理有专题的格式：法答网精选答问（第三十五批）——商事审判专题
        # 或：法答网精选答问（第三十四批）——仲裁司法审查专题（第二批）
        # 先统计括号数量（在替换之前）
        left_count = filename.count('（')
        filename = filename.replace('）——', '-')
        # 去掉末尾的），后面会统一添加
        if filename.endswith('）'):
            filename = filename[:-1]
        # 如果有多个左括号，说明有内层括号需要转换
        if left_count >= 2:
            # 有内层括号，只保留第一个（为（，其余（和）转换为【】
            # 找到第一个（的位置（法答网精选答问后的）
            prefix_end = filename.find('（') + 1
            prefix = filename[:prefix_end]  # 法答网精选答问（
            rest = filename[prefix_end:]  # 第三十四批-仲裁司法审查专题（第二批
            # 将rest中的（和）替换为【和】
            rest = rest.replace('（', '【').replace('）', '】')
            # 如果rest中有【但没有】，补上】（因为末尾的）之前被去掉了）
            if '【' in rest and not rest.endswith('】'):
                rest += '】'
            filename = prefix + rest
        # 如果只有一个（，保持不变
    else:
        # 处理无专题的格式：法答网精选答问（第三批）
        # 去掉结尾的中文右括号，后面会统一添加
        if filename.endswith('）'):
            filename = filename[:-1]

    # 替换文件系统不允许的字符（Windows: \ / : * ? " < > |）
    forbidden_chars = r'\/:*?"<>|'
    for char in forbidden_chars:
        filename = filename.replace(char, '_')

    # 去除首尾空格和点
    filename = filename.strip(' .')

    # 统一加上结尾的中文右括号
    filename += '）'

    return filename


def fetch_content(base_url, link):
    full_url = urljoin(base_url, link)
    html = fetch_page(full_url)
    if not html:
        return None, None

    soup = BeautifulSoup(html, 'html.parser')
    title = soup.find('div', class_='title')
    txt_big = soup.find('div', class_='txt big')

    if not title or not txt_big:
        print(f"Could not find title or content for {full_url}")
        return None, None

    title_text = title.get_text().strip()
    txt_big_text = txt_big.get_text().strip()

    return title_text, txt_big_text


def load_downloaded_records(record_file):
    """
    加载已下载文件记录

    Returns:
        set: 已下载文件的安全标题集合
    """
    if os.path.exists(record_file):
        try:
            with open(record_file, 'r', encoding='utf-8') as f:
                return set(line.strip() for line in f if line.strip())
        except Exception as e:
            print(f"加载下载记录失败: {e}")
    return set()


def save_downloaded_record(record_file, safe_title):
    """
    保存已下载文件记录

    Args:
        record_file: 记录文件路径
        safe_title: 安全的文件标题
    """
    try:
        with open(record_file, 'a', encoding='utf-8') as f:
            f.write(f"{safe_title}\n")
    except Exception as e:
        print(f"保存下载记录失败: {e}")


def file_exists(output_dir, safe_title):
    """检查文件是否已存在（保留用于兼容性）"""
    file_path = os.path.join(output_dir, f"{safe_title}.md")
    return os.path.exists(file_path)


def save_to_markdown(base_url, links):
    output_dir = 'court_contents'
    os.makedirs(output_dir, exist_ok=True)

    # 下载记录文件路径
    record_file = os.path.join(output_dir, '.downloaded_records.txt')

    # 加载已下载文件记录（用于快速跳过，避免不必要的HTTP请求）
    downloaded_titles = load_downloaded_records(record_file)
    print(f"已加载 {len(downloaded_titles)} 条已下载记录")

    skipped = 0
    saved = 0
    failed = 0

    for i, link in enumerate(links):
        # 首先获取标题
        full_url = urljoin(base_url, link)
        html = fetch_page(full_url)
        if not html:
            print(f"Failed to fetch {full_url}")
            failed += 1
            continue

        soup = BeautifulSoup(html, 'html.parser')
        title_div = soup.find('div', class_='title')

        if not title_div:
            print(f"No title found for {full_url}")
            failed += 1
            continue

        title_text = title_div.get_text().strip()
        safe_title = get_safe_filename(title_text)

        # 优化：优先检查下载记录（内存操作，比检查文件系统更快）
        if safe_title in downloaded_titles:
            print(f"[{i+1}/{len(links)}] 跳过已下载: {safe_title}.md")
            skipped += 1
            continue

        # 双重检查：如果记录中没有但文件存在（处理记录文件丢失的情况）
        if file_exists(output_dir, safe_title):
            print(f"[{i+1}/{len(links)}] 文件已存在，补充记录: {safe_title}.md")
            save_downloaded_record(record_file, safe_title)
            downloaded_titles.add(safe_title)
            skipped += 1
            continue

        # 获取内容并保存
        txt_big = soup.find('div', class_='txt big')
        if not txt_big:
            print(f"No content found for {full_url}")
            failed += 1
            continue

        txt_big_text = txt_big.get_text().strip()
        file_path = os.path.join(output_dir, f"{safe_title}.md")

        with open(file_path, 'w', encoding='utf-8') as f:
            # 将"问题1："等转换为二级标题
            lines = txt_big_text.split('\n')
            formatted_lines = []
            for line in lines:
                # 去除行首缩进
                line = line.lstrip()
                if line.startswith('问题') and '：' in line:
                    formatted_lines.append(f"## {line}")
                else:
                    formatted_lines.append(line)

            # 合并为纯文本内容
            formatted_content = '\n'.join(formatted_lines)
            md_content = f"# {title_text}\n\n{formatted_content}\n"
            f.write(md_content)

        # 保存下载记录
        save_downloaded_record(record_file, safe_title)
        downloaded_titles.add(safe_title)

        print(f"[{i+1}/{len(links)}] 已保存: {file_path}")
        saved += 1

    print(f"\n总结: 共处理 {len(links)} 个链接, 新下载 {saved} 个, 跳过 {skipped} 个, 失败 {failed} 个")


def rename_existing_files(output_dir='court_contents'):
    """
    批量重命名现有文件，将其从旧格式转换为新格式

    旧格式示例：
    - 法答网精选答问_第三批.md
    - 法答网精选答问_第三十五批___商事审判专题.md

    新格式示例：
    - 法答网精选答问(第三批).md
    - 法答网精选答问(第三十五批-商事审判专题).md

    同时更新下载记录文件
    """
    if not os.path.exists(output_dir):
        print(f"目录不存在: {output_dir}")
        return

    # 下载记录文件路径
    record_file = os.path.join(output_dir, '.downloaded_records.txt')

    # 加载现有下载记录
    old_records = load_downloaded_records(record_file)
    new_records = set()

    # 创建旧文件名到新文件名的映射（用于更新下载记录）
    filename_map = {}

    # 获取所有 .md 文件
    md_files = [f for f in os.listdir(output_dir) if f.endswith('.md') and not f.startswith('.')]

    renamed_count = 0
    skipped_count = 0
    error_count = 0

    for old_filename in md_files:
        old_path = os.path.join(output_dir, old_filename)

        # 读取文件内容获取标题
        try:
            with open(old_path, 'r', encoding='utf-8') as f:
                first_line = f.readline().strip()

            # 移除 Markdown 标题符号
            if first_line.startswith('#'):
                title = first_line.lstrip('#').strip()
            else:
                title = old_filename.replace('.md', '')

            # 使用新的命名规则生成新文件名
            new_filename = get_safe_filename(title) + '.md'
            new_path = os.path.join(output_dir, new_filename)

            # 如果新文件名与旧文件名相同，跳过
            if old_filename == new_filename:
                skipped_count += 1
                filename_map[old_filename.replace('.md', '')] = old_filename.replace('.md', '')
                continue

            # 如果目标文件已存在，添加序号避免覆盖
            if os.path.exists(new_path) and old_path != new_path:
                base, ext = os.path.splitext(new_filename)
                counter = 1
                while os.path.exists(os.path.join(output_dir, f"{base}_{counter}{ext}")):
                    counter += 1
                new_filename = f"{base}_{counter}{ext}"
                new_path = os.path.join(output_dir, new_filename)

            # 记录文件名映射（用于更新下载记录）
            old_safe_name = old_filename.replace('.md', '')
            new_safe_name = new_filename.replace('.md', '')
            filename_map[old_safe_name] = new_safe_name

            # 执行重命名
            os.rename(old_path, new_path)
            print(f"重命名: {old_filename} -> {new_filename}")
            renamed_count += 1

        except Exception as e:
            print(f"重命名失败 {old_filename}: {e}")
            error_count += 1

    # 更新下载记录文件
    if renamed_count > 0:
        print("\n正在更新下载记录...")
        try:
            # 重建记录文件
            updated_records = set()
            for old_record in old_records:
                # 如果有映射，使用新文件名；否则保持原样
                if old_record in filename_map:
                    updated_records.add(filename_map[old_record])
                else:
                    updated_records.add(old_record)

            # 添加新文件名的记录
            for new_record in filename_map.values():
                updated_records.add(new_record)

            # 写入更新后的记录
            with open(record_file, 'w', encoding='utf-8') as f:
                for record in sorted(updated_records):
                    f.write(f"{record}\n")

            print(f"下载记录已更新（共 {len(updated_records)} 条记录）")

        except Exception as e:
            print(f"更新下载记录失败: {e}")

    print(f"\n重命名完成: 成功 {renamed_count} 个, 跳过 {skipped_count} 个, 失败 {error_count} 个")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='法答网内容下载和重命名工具')
    parser.add_argument('--rename', action='store_true', help='仅重命名现有文件，不下载新内容')
    parser.add_argument('--download', action='store_true', help='下载新内容（默认操作）')
    args = parser.parse_args()

    # 如果指定了 --rename，只执行重命名操作
    if args.rename:
        print("开始重命名现有文件...")
        rename_existing_files()
        print("重命名完成!")
        return

    # 默认操作：下载新内容
    base_url = 'https://www.court.gov.cn'
    search_url = 'https://www.court.gov.cn/search.html?content=%E6%B3%95%E7%AD%94%E7%BD%91%E7%B2%BE%E9%80%89%E7%AD%94%E9%97%AE'

    print("开始爬取内容...")
    html = fetch_page(search_url)
    if not html:
        print("Failed to fetch initial page")
        return

    links = parse_links(html)
    if not links:
        print("No links found")
        return

    print(f"找到 {len(links)} 个链接, 开始下载内容...")
    save_to_markdown(base_url, links)
    print("下载完成!")


if __name__ == '__main__':
    main()
