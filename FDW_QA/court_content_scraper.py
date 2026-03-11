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
    """根据标题生成安全的文件名"""
    if not title:
        return "unknown"
    return ''.join(c if c.isalnum() else '_' for c in title).rstrip('_')


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


def main():
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
