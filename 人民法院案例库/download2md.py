import requests
import json
import os
import time
import random
from bs4 import BeautifulSoup

# 配置
page_data_dir = "court_data/pages"
output_dir = "downloaded_markdown"
os.makedirs(output_dir, exist_ok=True)
token = "12345677890000000000000000000000"  # 请替换为自己的token

# 随机User-Agent列表
user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
]

# 记录文件路径
record_file = "downloaded_records.txt"

# 读取已下载记录
downloaded_files = set()
if os.path.exists(record_file):
    with open(record_file, 'r', encoding='utf-8') as f:
        downloaded_files = set(line.strip() for line in f)

def remove_html_tags(text):
    # 去除 <p> 和 </p> 标签
    content = text.replace("<p>", "").replace("</p>", "")

    # 将 <br> 或 </br> 替换为换行符
    content = content.replace("<br/>", "\n")

    content = content.replace("　　　　", "　　")

    content = content.replace("######", "#### 原审法院\n")
    return content

def safe_filename(title):
    """生成安全的文件名"""
    return "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()

def make_request(item_id):
    """发送请求获取案件内容"""
    url = "https://rmfyalk.court.gov.cn/cpws_al_api/api/cpwsAl/content"
    headers = {
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
        'Origin': 'https://rmfyalk.court.gov.cn',
        'Referer': 'https://rmfyalk.court.gov.cn/view/content.html?id=W7TchTFrsdSkSM2wbeAJzGeSw4cZlstHOEO1xpJKOgQ%253D&lib=ck',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
        'sec-ch-ua': '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'faxin-cpws-al-token': token,
        'Content-Type': 'application/json;charset=UTF-8'
    }
    payload = f'{{"gid":"{item_id}"}}'
    response = requests.request("POST", url, headers=headers, data=payload)
    return response.json()

def save_as_markdown(content_data, output_dir):
    """将案件内容保存为markdown文件"""
    title = content_data.get('data', {}).get('data', {}).get('cpws_al_title', 'Untitled')
    subtitle = content_data.get('data', {}).get('data', {}).get('cpws_al_sub_title', '')
    keywords = ' '.join(content_data.get('data', {}).get('data', {}).get('cpws_al_keyword', []))
    basic_case = remove_html_tags(content_data.get('data', {}).get('data', {}).get('cpws_al_jbaq', ''))
    judgment_reason = remove_html_tags(content_data.get('data', {}).get('data', {}).get('cpws_al_cply', ''))
    judgment_summary = remove_html_tags(content_data.get('data', {}).get('data', {}).get('cpws_al_cpyz', ''))
    related_index = remove_html_tags(content_data.get('data', {}).get('data', {}).get('cpws_al_glsy', ''))
    case_info = content_data.get('data', {}).get('data', {}).get('cpws_al_infos', '')

    output_file = os.path.join(output_dir, f"{safe_filename(title)}.md")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"# {title}\n")
        f.write(f"## {subtitle}\n")
        f.write(f"### 关键字\n{keywords}\n")
        f.write(f"### 基本案情\n{basic_case}\n")
        f.write(f"### 裁判理由\n{judgment_reason}\n")
        f.write(f"### 裁判要旨\n{judgment_summary}\n")
        f.write(f"### 关联索引\n{related_index}\n")
        f.write(f"#### 案件信息\n{case_info}\n")
    return output_file

# 获取所有JSON文件
json_files = [f for f in os.listdir(page_data_dir) if f.endswith('.json')]
print(f"共发现 {len(json_files)} 个JSON文件")

# 按文件名倒序处理每个JSON文件
for json_file in sorted(json_files, reverse=True):
    file_path = os.path.join(page_data_dir, json_file)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)

                if 'data' in data and 'datas' in data['data']:
                    for item in data['data']['datas']:
                        if 'id' in item:
                            # 构建请求URL
                            try:
                                # 检查是否已下载
                                if item['id'][:10] in {x[:10] for x in downloaded_files}:
                                    print(f'{item["id"]} 已下载，跳过')
                                    continue
                                
                                try:
                                    # 使用新函数发送请求
                                        content_data = make_request(item['id'])
                                        
                                        # 检查title是否为空
                                        title = content_data.get('data', {}).get('data', {}).get('cpws_al_title', 'Untitled')
                                        if not title or title == 'Untitled':
                                            print("检测到空title，已达当天api上限，退出")
                                            exit(0)
                                            
                                        # 使用新函数保存markdown
                                        output_file = save_as_markdown(content_data, output_dir)
                                        print(f"成功保存 {os.path.basename(output_file)}")

                                        # 记录已下载文件
                                        with open(record_file, 'a', encoding='utf-8') as f:
                                            f.write(f'{item["id"][:10]}\n')

                                except Exception as e:
                                    print(f"处理 {item['id']} 时出错: {e}")
                                        
                                # 间隔3-5秒
                                time.sleep(random.uniform(3, 5))
                            except Exception as e:
                                print(f"处理 {item['id']} 时出错: {e}")

            except json.JSONDecodeError as e:
                print(f"文件 {json_file} JSON格式错误: {e}")
            except Exception as e:
                print(f"处理文件 {json_file} 时出错: {e}")

    except Exception as e:
        print(f"读取文件 {json_file} 时出错: {e}")

print("所有文件处理完成")
