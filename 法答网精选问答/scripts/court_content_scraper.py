import requests
from bs4 import BeautifulSoup
import markdown
from urllib.parse import urljoin
import time
import random

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

def fetch_content(base_url, link):
    full_url = urljoin(base_url, link)
    html = fetch_page(full_url)
    if not html:
        return None, None
        
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.find('div', class_='title')
    txt_big = soup.find('div', class_='txt big')
    
    title_text = title.get_text().strip()
    txt_big_text = txt_big.get_text().strip()

    return title_text, txt_big_text

def save_to_markdown(base_url, links):
    import os
    output_dir = 'court_contents'
    os.makedirs(output_dir, exist_ok=True)
    
    for link in links:
        title, content = fetch_content(base_url, link)
        if title and content:
            # 使用title作为文件名，替换非法字符并去除最后的_
            safe_title = ''.join(c if c.isalnum() else '_' for c in title).rstrip('_')
            file_path = os.path.join(output_dir, f"{safe_title}.md")
            
            with open(file_path, 'w', encoding='utf-8') as f:
                # 将"问题1："等转换为二级标题
                lines = content.split('\n')
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
                md_content = f"# {title}\n\n{formatted_content}\n"
                f.write(md_content)
            print(f"Saved {file_path}")
        else:
            print(f"No valid content found for {link}")

def main():
    base_url = 'https://www.court.gov.cn'  # 更新base_url
    search_url = 'https://www.court.gov.cn/search.html?content=%E6%B3%95%E7%AD%94%E7%BD%91%E7%B2%BE%E9%80%89%E7%AD%94%E9%97%AE'
    html = fetch_page(search_url)
    if not html:
        print("Failed to fetch initial page")
        return
        
    links = parse_links(html)
    if not links:
        print("No links found")
        return
        
    print(f"Found {len(links)} links")
    save_to_markdown(base_url, links)

if __name__ == '__main__':
    main()