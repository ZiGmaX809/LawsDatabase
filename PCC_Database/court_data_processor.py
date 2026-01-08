import os
import json
import time
import random
import requests
import shutil
import re
import argparse
import hashlib
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

class CourtDataProcessor:
    """法院案例数据处理主程序"""

    # 案件类型配置：类型名称 -> (sort_id, 中文说明)
    CASE_TYPES = {
        "criminal": ("10000", "刑事"),
        "civil": ("20000", "民事"),
        "administrative": ("30000", "行政"),
        "execution": ("40000", "执行"),
        "compensation": ("50000", "国家赔偿")
    }

    def __init__(self, token=None, case_type=None):
        # 基础配置
        self.base_dir = Path(__file__).parent
        self.config = self.load_config()

        # 日志文件 - 需要在set_case_type之前初始化，因为set_case_type会调用log
        self.log_file = self.base_dir / "court_data" / f"processor_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        # 如果提供了命令行token，则覆盖配置文件中的token
        if token:
            self.config["token"] = token

        # 设置案件类型
        if case_type:
            self.set_case_type(case_type)

        # 初始化目录
        self.init_dirs()

    def set_case_type(self, case_type):
        """
        设置案件类型
        Args:
            case_type: 案件类型代码（criminal/civil/administrative/execution/compensation）
        """
        if case_type not in self.CASE_TYPES:
            raise ValueError(f"不支持的案件类型: {case_type}，支持的类型: {list(self.CASE_TYPES.keys())}")

        sort_id, type_name = self.CASE_TYPES[case_type]
        self.config["case_sort_id"] = sort_id
        self.config["case_type_code"] = case_type
        self.config["case_type_name"] = type_name

        # 更新配置中的目录路径，添加案件类型分类
        self.config["markdown_dir"] = f"downloaded_markdown/{type_name}"
        self.config["json_dir"] = f"court_data/pages/{type_name}"
        self.config["target_dir"] = f"/Users/zigma/Documents/律师材料/知识库/人民法院案例库/{type_name}"

        self.log(f"已设置案件类型: {type_name} ({case_type}), sort_id: {sort_id}")
        
    def load_config(self):
        """加载配置文件"""
        config_path = self.base_dir / "court_config.json"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        # 默认配置
        return {
            "token": "",  # 默认空token，需要从命令行获取
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

    def login(self, username, password):
        """
        使用账号密码登录获取token
        Args:
            username: 用户名/手机号
            password: 密码
        Returns:
            str: 获取的token，失败返回None
        """
        self.log("正在登录...")

        # 登录API URL
        login_url = "https://rmfyalk.court.gov.cn/cpws_al_api/api/user/login"

        # 构建登录payload
        payload = {
            "username": username,
            "password": self._md5_hash(password),  # 通常密码需要MD5加密
            "loginType": "1"  # 1表示账号密码登录
        }

        headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'User-Agent': random.choice(self.config["user_agents"]),
            'Content-Type': 'application/json;charset=UTF-8'
        }

        try:
            response = requests.post(login_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get('code') == 0 and 'data' in data:
                token = data['data'].get('token') or data['data'].get('faxin-cpws-al-token')
                if token:
                    self.log("登录成功，已获取token")
                    # 保存token到配置文件
                    self.config["token"] = token
                    self.save_config()
                    return token
                else:
                    self.log("登录失败: 响应中未找到token")
                    return None
            else:
                self.log(f"登录失败: {data.get('msg', '未知错误')}")
                return None

        except requests.exceptions.Timeout:
            self.log("登录失败: 请求超时")
            return None
        except requests.exceptions.RequestException as e:
            self.log(f"登录失败: 网络请求错误 - {str(e)}")
            return None
        except Exception as e:
            self.log(f"登录失败: {str(e)}")
            return None

    def _md5_hash(self, text):
        """
        计算MD5哈希值
        Args:
            text: 需要哈希的文本
        Returns:
            str: MD5哈希值（32位小写十六进制）
        """
        return hashlib.md5(text.encode('utf-8')).hexdigest()

    def save_config(self):
        """保存配置到文件"""
        config_path = self.base_dir / "court_config.json"
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            self.log("配置已保存")
        except Exception as e:
            self.log(f"保存配置失败: {str(e)}")

    def get_headers(self):
        """获取请求头"""
        if not self.config["token"]:
            raise ValueError("未提供token，请使用--token参数提供有效的token")
            
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

        # 记录已下载的文件 - 按案件类型分类
        case_type_code = self.config.get("case_type_code", "civil")
        record_file = self.base_dir / f"downloaded_records_{case_type_code}.txt"
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
    
    def count_target_files(self):
        """统计目标文件夹中的文件数量并保存结果"""
        target_dir = Path(self.config["target_dir"])

        if not target_dir.exists():
            self.log(f"目标目录不存在: {target_dir}")
            return None

        # 统计总文件数和各子目录文件数
        total_count = 0
        dir_stats = {}

        # 遍历目标目录及其所有子目录
        for root, dirs, files in os.walk(target_dir):
            file_count = len(files)
            # 计算相对路径作为目录名
            rel_path = os.path.relpath(root, target_dir)

            if file_count > 0:
                dir_stats[rel_path] = file_count
                total_count += file_count

        # 获取当前时间作为更新时间
        update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        update_date = datetime.now().strftime('%Y-%m-%d')

        # 构建Markdown内容
        md_content = f"# 人民法院案例库统计\n\n"
        md_content += f"## 统计信息\n\n"
        md_content += f"- **更新时间**: {update_time}\n"
        md_content += f"- **总文件数**: {total_count} 个\n"
        md_content += f"- **分类数量**: {len(dir_stats)} 个\n\n"
        md_content += f"## 分类统计\n\n"
        md_content += f"按文件数量降序排列：\n\n"

        # 按文件数量降序排列
        sorted_stats = sorted(dir_stats.items(), key=lambda x: x[1], reverse=True)
        for i, (dir_name, count) in enumerate(sorted_stats, 1):
            md_content += f"{i}. **{dir_name}**: {count} 个文件\n"

        # 保存统计结果到Markdown文件（按日期命名，覆盖旧的）
        stats_file = target_dir / f"统计信息_{update_date}.md"
        try:
            with open(stats_file, 'w', encoding='utf-8') as f:
                f.write(md_content)
            self.log(f"统计结果已保存到: {stats_file}")
        except Exception as e:
            self.log(f"保存统计结果时出错: {str(e)}")

        # 输出统计结果到控制台和日志
        self.log("=" * 60)
        self.log(f"目标目录统计: {target_dir}")
        self.log(f"更新时间: {update_time}")
        self.log("=" * 60)
        self.log(f"总文件数: {total_count}")
        self.log(f"分类数量: {len(dir_stats)}")
        self.log("-" * 60)

        # 按文件数量降序显示各子目录统计（显示前20个）
        for i, (dir_name, count) in enumerate(sorted_stats[:20], 1):
            self.log(f"{i:2d}. {dir_name}: {count} 个文件")

        if len(sorted_stats) > 20:
            self.log(f"... 还有 {len(sorted_stats) - 20} 个分类")

        self.log("=" * 60)
        return total_count

    def run(self):
        """运行主流程"""
        self.log("法院案例数据处理程序启动")

        # 检查是否有token
        if not self.config["token"]:
            self.log("错误: 未提供token，请使用--token参数提供有效的token")
            return False

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

def get_case_type_choice():
    """
    交互式选择案件类型
    Returns:
        str: 案件类型代码
    """
    print("\n请选择要下载的案件类型:")
    case_list = list(CourtDataProcessor.CASE_TYPES.items())
    for i, (code, (sort_id, name)) in enumerate(case_list, 1):
        print(f"  {i}. {name} ({code})")

    while True:
        try:
            choice = input(f"\n请输入选项 (1-{len(case_list)}) 或直接输入类型代码: ").strip()

            # 尝试直接输入类型代码
            if choice in CourtDataProcessor.CASE_TYPES:
                return choice

            # 尝试输入数字选项
            choice_num = int(choice)
            if 1 <= choice_num <= len(case_list):
                return case_list[choice_num - 1][0]

            print(f"无效输入，请输入 1-{len(case_list)} 之间的数字")
        except ValueError:
            print("无效输入，请输入数字")
        except KeyboardInterrupt:
            print("\n\n操作已取消")
            sys.exit(0)


def get_credentials_input():
    """
    交互式获取认证信息（token或账号密码）
    Returns:
        str: 获取的token
    """
    print("\n请选择认证方式:")
    print("  1. 使用已有token")
    print("  2. 账号密码登录")

    while True:
        try:
            choice = input("\n请选择 (1-2): ").strip()

            if choice == "1":
                return get_direct_token_input()
            elif choice == "2":
                return get_login_input()
            else:
                print("无效输入，请输入 1 或 2")
        except KeyboardInterrupt:
            print("\n\n操作已取消")
            sys.exit(0)


def get_direct_token_input():
    """
    直接输入token
    Returns:
        str: 用户输入的token
    """
    print("\n[直接输入token]")
    print("提示: token可从浏览器开发者工具中获取")

    while True:
        token = input("token: ").strip()
        if token:
            return token
        print("token不能为空，请重新输入")


def get_login_input():
    """
    账号密码登录
    Returns:
        str: 登录成功后获取的token
    """
    print("\n[账号密码登录]")
    print("提示: 请使用您在人民法院案例库注册的账号")

    while True:
        try:
            username = input("用户名/手机号: ").strip()
            if not username:
                print("用户名不能为空")
                continue

            password = input("密码: ").strip()
            if not password:
                print("密码不能为空")
                continue

            # 尝试登录
            print("\n正在登录，请稍候...")
            processor = CourtDataProcessor(token=None, case_type=None)
            token = processor.login(username, password)

            if token:
                print(f"\n登录成功！token已自动保存到配置文件")
                return token
            else:
                print("\n登录失败，请重试或选择使用token方式")
                retry = input("是否重试? (y/n): ").strip().lower()
                if retry != 'y':
                    # 返回到认证方式选择
                    return get_credentials_input()

        except KeyboardInterrupt:
            print("\n\n操作已取消")
            sys.exit(0)


def get_token_input():
    """
    交互式获取token（保留向后兼容）
    Returns:
        str: 用户输入的token
    """
    return get_credentials_input()


def main():
    """主函数 - 交互式流程"""
    print("=" * 60)
    print(" " * 15 + "人民法院案例库数据处理程序")
    print("=" * 60)

    # 仅保留--count和--config参数
    parser = argparse.ArgumentParser(
        description='人民法院案例库数据处理程序',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False  # 禁用默认帮助，自定义帮助信息
    )
    parser.add_argument('--config', type=str, help='可选的配置文件路径')
    parser.add_argument('--count', action='store_true', help='统计目标文件夹中的文件数量')
    parser.add_argument('--help', '-h', action='store_true', help='显示帮助信息')

    args = parser.parse_args()

    # 显示帮助信息
    if args.help:
        print("""
用法: python court_data_processor.py [选项]

选项:
  --config PATH    可选的配置文件路径
  --count          统计目标文件夹中的文件数量
  --help, -h       显示此帮助信息

交互式流程:
  1. 启动脚本后选择认证方式：
     - 使用已有token（从浏览器开发者工具获取）
     - 账号密码登录（自动获取并保存token）
  2. 选择要下载的案件类型
  3. 自动执行下载和整理流程

认证方式说明:
  - Token方式：适合已有token的用户，token会保存到配置文件
  - 账号密码：适合注册用户，登录成功后自动保存token
  - 配置文件：court_config.json，保存token后下次无需重新输入

案件类型说明:
  1. criminal     刑事案件 (sort_id: 10000)
  2. civil        民事案件 (sort_id: 20000)
  3. administrative  行政案件 (sort_id: 30000)
  4. execution    执行案件 (sort_id: 40000)
  5. compensation 国家赔偿案件 (sort_id: 50000)
        """)
        return

    # 如果是统计模式，需要先选择案件类型
    if args.count:
        print("\n[统计模式]")
        case_type = get_case_type_choice()
        processor = CourtDataProcessor(token=None, case_type=case_type)
        processor.count_target_files()
        return

    # 正常下载流程
    print("\n[下载模式]")

    # 检查配置文件中是否已有token
    temp_processor = CourtDataProcessor(token=None, case_type=None)
    existing_token = temp_processor.config.get("token", "").strip()

    if existing_token:
        print("\n检测到配置文件中已有保存的token")
        use_existing = input("是否使用已保存的token? (y/n，默认y): ").strip().lower()
        if use_existing in ['', 'y', 'yes']:
            token = existing_token
            print(f"已使用已保存的token: {token[:10]}...")
        else:
            # 获取新的token
            token = get_token_input()
    else:
        # 获取token
        token = get_token_input()

    # 选择案件类型
    case_type = get_case_type_choice()

    # 显示确认信息
    _, case_name = CourtDataProcessor.CASE_TYPES[case_type]
    print(f"\n已选择: {case_name}案件")
    print(f"token: {token[:10]}..." if len(token) > 10 else f"token: {token}")
    print("\n开始处理...")

    # 实例化处理器并运行
    processor = CourtDataProcessor(token=token, case_type=case_type)
    processor.run()

    print("\n" + "=" * 60)
    print("处理完成！")
    print("=" * 60)


if __name__ == "__main__":
    import sys
    main()