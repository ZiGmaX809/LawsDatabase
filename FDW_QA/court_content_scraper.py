import requests
from bs4 import BeautifulSoup
import markdown
from urllib.parse import urljoin
import time
import random
import os


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


def file_exists(output_dir, safe_title):
    """检查文件是否已存在"""
    file_path = os.path.join(output_dir, f"{safe_title}.md")
    return os.path.exists(file_path)


def save_to_markdown(base_url, links):
    output_dir = 'court_contents'
    os.makedirs(output_dir, exist_ok=True)

    skipped = 0
    saved = 0

    for i, link in enumerate(links):
        # 首先获取标题
        full_url = urljoin(base_url, link)
        html = fetch_page(full_url)
        if not html:
            print(f"Failed to fetch {full_url}")
            continue

        soup = BeautifulSoup(html, 'html.parser')
        title_div = soup.find('div', class_='title')

        if not title_div:
            print(f"No title found for {full_url}")
            continue

        title_text = title_div.get_text().strip()
        safe_title = get_safe_filename(title_text)

        # 检查文件是否已存在
        if file_exists(output_dir, safe_title):
            print(f"[{i+1}/{len(links)}] 跳过已存在的文件: {safe_title}.md")
            skipped += 1
            continue

        # 获取内容并保存
        txt_big = soup.find('div', class_='txt big')
        if not txt_big:
            print(f"No content found for {full_url}")
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

        print(f"[{i+1}/{len(links)}] 已保存: {file_path}")
        saved += 1

    print(f"\n总结: 共处理 {len(links)} 个链接, 跳过 {skipped} 个已存在文件, 新下载 {saved} 个文件")


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
