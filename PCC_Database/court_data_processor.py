import os
import json
import time
import random
import requests
import shutil
import re
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

class CourtDataProcessor:
    """法院案例数据处理主程序"""
    
    def __init__(self):
        # 基础配置
        self.base_dir = Path(__file__).parent
        self.config = self.load_config()
        
        # 初始化目录
        self.init_dirs()
        
        # 日志文件
        self.log_file = self.base_dir / "court_data" / f"processor_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
    def load_config(self):
        """加载配置文件"""
        config_path = self.base_dir / "court_config.json"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        # 默认配置
        return {
            "token": "your_token_here",
            "page_size": 300,
            "case_sort_id": "20000",  # 民事20000 执行40000 刑事10000 行政30000 国家赔偿50000
            "json_dir": "court_data/pages",
            "markdown_dir": "downloaded_markdown",
            "target_dir": "/Users/zigma/Documents/律师材料/知识库/人民法院案例库/民事",
            "user_agents": [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15"
            ],
            "request_interval": [3, 5]  # 请求间隔秒数范围
        }
    
    def init_dirs(self):
        """初始化所需目录"""
        dirs = [
            self.base_dir / self.config["json_dir"],
            self.base_dir / self.config["markdown_dir"],
            Path(self.config["target_dir"])
        ]
        
        for dir_path in dirs:
            os.makedirs(dir_path, exist_ok=True)
    
    def log(self, message):
        """记录日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} - {message}"
        
        print(log_entry)
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry + "\n")
    
    def sanitize_filename(self, name):
        """清理文件名"""
        sanitized = re.sub(r'[\\/:*?"<>|]', '_', name)
        sanitized = sanitized.strip()
        return sanitized or "未命名"
    
    def get_headers(self):
        """获取请求头"""
        return {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'User-Agent': random.choice(self.config["user_agents"]),
            'faxin-cpws-al-token': self.config["token"],
            'Content-Type': 'application/json;charset=UTF-8'
        }
    
    def fetch_case_list(self):
        """获取案例列表"""
        self.log("开始获取案例列表...")
        
        url = "https://rmfyalk.court.gov.cn/cpws_al_api/api/cpwsAl/search"
        payload = {
            "page": 1,
            "size": self.config["page_size"],
            "lib": "qb",
            "searchParams": {
                "userSearchType": 1,
                "isAdvSearch": "0",
                "selectValue": "qw",
                "lib": "cpwsAl_qb",
                "sort_field": "",
                "sort_id_cpwsAl": self.config["case_sort_id"]
            }
        }
        
        try:
            response = requests.post(url, headers=self.get_headers(), json=payload)
            response.raise_for_status()
            data = response.json()
            
            if data.get('code') != 0:
                self.log(f"获取案例列表失败: {data.get('msg')}")
                return None
                
            # 保存JSON数据
            output_file = self.base_dir / self.config["json_dir"] / "initial_response.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
            self.log(f"成功获取案例列表，保存到 {output_file}")
            return data
            
        except Exception as e:
            self.log(f"获取案例列表时出错: {str(e)}")
            return None
    
    def download_case_details(self):
        """下载案例详情并转为Markdown"""
        self.log("开始下载案例详情...")
        
        json_dir = self.base_dir / self.config["json_dir"]
        markdown_dir = self.base_dir / self.config["markdown_dir"]
        
        # 记录已下载的文件
        record_file = self.base_dir / "downloaded_records.txt"
        downloaded_files = set()
        
        if record_file.exists():
            with open(record_file, 'r', encoding='utf-8') as f:
                downloaded_files = set(line.strip() for line in f)
        
        # 处理所有JSON文件
        json_files = [f for f in json_dir.glob('*.json')]
        if not json_files:
            self.log("没有找到JSON文件")
            return False
            
        success_count = 0
        
        for json_file in sorted(json_files, reverse=True):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    if 'data' not in data or 'datas' not in data['data']:
                        continue
                        
                    for item in data['data']['datas']:
                        if 'id' not in item:
                            continue
                            
                        # 检查是否已下载
                        if item['id'][:10] in {x[:10] for x in downloaded_files}:
                            continue
                            
                        # 下载案例详情
                        case_data = self.fetch_case_content(item['id'])
                        if not case_data:
                            continue
                            
                        # 保存为Markdown
                        if self.save_as_markdown(case_data, markdown_dir):
                            success_count += 1
                            with open(record_file, 'a', encoding='utf-8') as f:
                                f.write(f"{item['id'][:10]}\n")
                                
                        # 随机间隔
                        time.sleep(random.uniform(*self.config["request_interval"]))
                        
            except Exception as e:
                self.log(f"处理文件 {json_file.name} 时出错: {str(e)}")
                
        self.log(f"下载完成，共处理 {success_count} 个案例")
        return success_count > 0
    
    def fetch_case_content(self, case_id):
        """获取案例内容"""
        url = "https://rmfyalk.court.gov.cn/cpws_al_api/api/cpwsAl/content"
        payload = {"gid": case_id}
        
        try:
            response = requests.post(url, headers=self.get_headers(), json=payload)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.log(f"获取案例 {case_id} 内容时出错: {str(e)}")
            return None
    
    def save_as_markdown(self, content_data, output_dir):
        """将案例内容保存为Markdown"""
        try:
            data = content_data.get('data', {}).get('data', {})
            title = data.get('cpws_al_title', 'Untitled')
            
            if not title or title == 'Untitled':
                return False
                
            # 清理HTML标签
            def clean_html(text):
                text = text.replace("<p>", "").replace("</p>", "")
                text = text.replace("<br/>", "\n")
                text = text.replace("　　　　", "　　")
                return text
                
            # 构建Markdown内容
            md_content = f"# {title}\n"
            md_content += f"## {data.get('cpws_al_sub_title', '')}\n"
            md_content += f"### 关键字\n{' '.join(data.get('cpws_al_keyword', []))}\n"
            md_content += f"### 基本案情\n{clean_html(data.get('cpws_al_jbaq', ''))}\n"
            md_content += f"### 裁判理由\n{clean_html(data.get('cpws_al_cply', ''))}\n"
            md_content += f"### 裁判要旨\n{clean_html(data.get('cpws_al_cpyz', ''))}\n"
            md_content += f"### 关联索引\n{clean_html(data.get('cpws_al_glsy', ''))}\n"
            md_content += f"#### 案件信息\n{data.get('cpws_al_infos', '')}\n"
            
            # 保存文件
            safe_title = self.sanitize_filename(title)
            output_file = output_dir / f"{safe_title}.md"
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(md_content)
                
            self.log(f"成功保存案例: {output_file.name}")
            return True
            
        except Exception as e:
            self.log(f"保存Markdown文件时出错: {str(e)}")
            return False
    
    def organize_case_files(self):
        """整理案例文件到分类目录"""
        self.log("开始整理案例文件...")
        
        json_dir = self.base_dir / self.config["json_dir"]
        markdown_dir = self.base_dir / self.config["markdown_dir"]
        target_dir = Path(self.config["target_dir"])
        
        # 检查目录是否存在
        if not json_dir.exists():
            self.log(f"JSON目录 {json_dir} 不存在")
            return False
            
        if not markdown_dir.exists():
            self.log(f"Markdown目录 {markdown_dir} 不存在")
            return False
            
        # 创建目标目录
        os.makedirs(target_dir, exist_ok=True)
        
        # 从JSON文件中提取标题到分类的映射
        title_to_sort = {}
        
        for json_file in json_dir.glob('*.json'):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    if 'data' in data and 'datas' in data['data']:
                        for item in data['data']['datas']:
                            if 'cpws_al_title' in item and 'cpws_al_sort_name' in item:
                                title_to_sort[item['cpws_al_title']] = item['cpws_al_sort_name']
            except Exception as e:
                self.log(f"处理JSON文件 {json_file.name} 时出错: {str(e)}")
                
        if not title_to_sort:
            self.log("没有找到有效的标题到分类的映射")
            return False
            
        # 整理文件
        processed_files = set()
        sort_dirs = {}
        success_count = 0
        
        for title, sort_name in title_to_sort.items():
            safe_sort = self.sanitize_filename(sort_name)
            
            # 创建分类目录
            if safe_sort not in sort_dirs:
                dest_dir = target_dir / safe_sort
                os.makedirs(dest_dir, exist_ok=True)
                sort_dirs[safe_sort] = dest_dir
            else:
                dest_dir = sort_dirs[safe_sort]
                
            # 查找匹配的Markdown文件
            source_file = None
            possible_names = [
                f"{title}.md",
                f"{title}案.md",
                f"指导性案例{title.split('指导性案例')[-1]}.md" if "指导性案例" in title else ""
            ]
            
            for name in possible_names:
                if not name:
                    continue
                    
                test_file = markdown_dir / name
                if test_file.exists():
                    source_file = test_file
                    break
                    
            if source_file:
                # 复制文件到目标目录
                dest_file = dest_dir / source_file.name
                
                try:
                    shutil.copy2(source_file, dest_file)
                    if str(source_file) not in processed_files:
                        success_count += 1
                        processed_files.add(str(source_file))
                    self.log(f"已整理: {source_file.name} -> {safe_sort}/")
                except Exception as e:
                    self.log(f"整理文件 {source_file.name} 时出错: {str(e)}")
                    
        self.log(f"整理完成，共处理 {success_count} 个文件")
        return success_count > 0
    
    def run(self):
        """运行主流程"""
        self.log("法院案例数据处理程序启动")
        
        # 1. 获取案例列表
        if not self.fetch_case_list():
            return False
            
        # 2. 下载案例详情
        if not self.download_case_details():
            return False
            
        # 3. 整理案例文件
        if not self.organize_case_files():
            return False
            
        self.log("所有处理流程完成")
        return True

if __name__ == "__main__":
    processor = CourtDataProcessor()
    processor.run()