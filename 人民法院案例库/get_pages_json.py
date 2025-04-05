import requests
import json
import time
import os
from datetime import datetime

# 创建存储数据的目录
output_dir = 'court_data'
os.makedirs(output_dir, exist_ok=True)

# 创建日志文件用于跟踪进度
log_file = f"{output_dir}/fetch_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"


def log_message(message):
    """将日志消息写入文件并打印到控制台"""
    print(message)
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")


# 从request.js文件中获取的请求头
headers = {
    'Accept-Encoding': 'gzip,compress,br,deflate',
    'content-type': 'application/json',
    'Connection': 'keep-alive',
    'Referer': 'https://servicewechat.com/wx9d3dc8d4b1e3924a/2/page-frame.html',
    'Host': 'rmfyalk.court.gov.cn',
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.56(0x18003835) NetType/4G Language/zh_CN',
    'faxin-cpws-al-token': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHAiOjE3NDM2OTg2MDQsInVzZXJuYW1lIjoiQTRCSnVVZ3NWb0dXa1FKd1BvRlpVaXVUNEZXd2ZVblhqZVZCMmlOQ0EwWUZmc3pBNEd6NjQ4eDhpeDRYTzBKdnRoNFNSbFZaR2JnPSJ9.W44zXAtNXTg6OWp7po8cd_cqdN0EpPk6FN35KBpGlnk' # 请替换为自己的token
}

# 步骤1：使用request.js中的初始请求获取总记录数


def get_total_count():
    url = "https://rmfyalk.court.gov.cn/cpws_al_api/api/cpwsAl/sortNextLeftCluster"

    payload = {
        "page": 1,
        "size": 10,
        "lib": "qb",
        "searchParams": {
            "userSearchType": 1,
            "isAdvSearch": "0",
            "selectValue": [],
            "lib": "cpwsAl_qb",
            "sort_field": "",
            "keyword_cpwsAl": "",
            "case_sort_id_cpwsAl": "02"
        },
        "pdh": 0,
        "mClient": "xcx"
    }

    try:
        # 发送POST请求获取初始数据
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()  # 如果请求失败则抛出异常
        data = response.json()

        # 保存初始响应数据以供参考
        with open(f"{output_dir}/initial_response.json", 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 检查是否返回未登录错误
        if data.get('code') == 401 and data.get('msg') == "未登录":
            log_message("错误: 用户未登录，请更新令牌！")
            log_message("请在微信小程序中登录并获取新的令牌，然后更新脚本中的 'faxin-cpws-al-token' 值")
            return None

        # 根据您提供的响应格式提取总记录数
        elif (data.get('code') == 0 and
              'data' in data and
              isinstance(data['data'], list) and
              len(data['data']) > 0 and
              'intCount' in data['data'][0]):

            # 使用intCount字段作为总记录数
            total_count = data['data'][0]['intCount']
            log_message(f"从响应中成功获取总记录数: {total_count}")
            return total_count

        else:
            log_message(
                f"在响应中未找到记录总数，错误代码: {data.get('code')}, 消息: {data.get('msg')}")
            log_message("请检查initial_response.json文件了解响应结构")
            return None

    except Exception as e:
        log_message(f"获取总记录数时出错: {str(e)}")
        return None

# 步骤2：根据总记录数获取所有分页数据


def fetch_all_pages(total_count):
    url = "https://rmfyalk.court.gov.cn/cpws_al_api/api/cpwsAl/search"

    # 使用get_json.py中的页面大小
    page_size = 300
    total_pages = (total_count + page_size - 1) // page_size

    log_message(f"总记录数: {total_count}")
    log_message(f"每页记录数: {page_size}")
    log_message(f"总页数: {total_pages}")

    # 创建存储分页数据的子目录
    pages_dir = f"{output_dir}/pages"
    os.makedirs(pages_dir, exist_ok=True)

    successful_pages = 0

    for page in range(1, total_pages + 1):
        try:
            log_message(f"正在获取第 {page}/{total_pages} 页...")

            # 构建请求负载，使用get_json.py中的参数
            payload = {
                "page": page,
                "size": page_size,
                "lib": "qb",
                "searchParams": {
                    "userSearchType": 1,
                    "isAdvSearch": "0",
                    "selectValue": "qw", 
                    "lib": "cpwsAl_qb",
                    "sort_field": "",
                    "sort_id_cpwsAl": "20000"  # 民事20000 执行40000 刑事10000 行政30000 国家赔偿50000
                }
            }

            # 发送请求获取当前页数据
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()

            data = response.json()

            # 检查是否返回未登录错误
            if data.get('code') == 401 and data.get('msg') == "未登录":
                log_message(f"获取第 {page} 页时出现未登录错误，请更新令牌")

                # 将错误响应保存到文件中
                error_file = f"{output_dir}/auth_error_page_{page}.json"
                with open(error_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                # 由于登录失效，终止后续请求
                log_message("因令牌失效中止操作。请更新令牌后重试。")
                break

            # 保存页面数据
            output_file = f"{pages_dir}/page_{page}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            successful_pages += 1
            log_message(f"成功保存第 {page} 页到 {output_file}")

            # 休眠一段时间，避免请求过于频繁
            time.sleep(1.5)  # 比get_json.py中的等待时间稍长，更安全

        except Exception as e:
            log_message(f"获取第 {page} 页时出错: {str(e)}")
            # 出错后等待更长时间再重试
            time.sleep(5)

            # 再尝试一次
            try:
                log_message(f"正在重试第 {page} 页...")
                response = requests.post(url, headers=headers, json=payload)
                response.raise_for_status()

                data = response.json()

                # 检查重试时是否返回未登录错误
                if data.get('code') == 401 and data.get('msg') == "未登录":
                    log_message(f"重试获取第 {page} 页时出现未登录错误，请更新令牌")
                    # 由于登录失效，终止后续请求
                    log_message("因令牌失效中止操作。请更新令牌后重试。")
                    break

                output_file = f"{pages_dir}/page_{page}.json"
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                successful_pages += 1
                log_message(f"重试后成功保存第 {page} 页")

            except Exception as retry_e:
                log_message(f"重试第 {page} 页失败: {str(retry_e)}")

    return successful_pages

# 主执行函数


def main():
    log_message("开始获取法院数据...")

    # 步骤1：获取总记录数
    total_count = get_total_count()

    if total_count is None:
        log_message("获取总记录数失败，程序退出。")
        return

    # 步骤2：获取所有页面数据
    successful_pages = fetch_all_pages(total_count)

    log_message(f"处理完成。成功获取 {successful_pages} 页数据。")
    log_message(f"数据保存在 {os.path.abspath(output_dir)} 目录中")

# 更新令牌的辅助函数


def update_token(new_token):
    """更新脚本中的令牌
    
    参数:
    new_token (str): 新的令牌值
    """
    # 读取当前脚本文件
    with open(__file__, 'r', encoding='utf-8') as f:
        script_content = f.read()

    # 查找并替换令牌值
    import re
    updated_content = re.sub(
        r"'faxin-cpws-al-token': '(.*?)'",
        f"'faxin-cpws-al-token': '{new_token}'",
        script_content
    )

    # 保存更新后的脚本
    with open(__file__, 'w', encoding='utf-8') as f:
        f.write(updated_content)

    log_message(f"令牌已更新。请重新运行脚本。")


if __name__ == "__main__":
    # 如果有命令行参数且第一个参数是update_token，则使用第二个参数更新令牌
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "update_token":
        update_token(sys.argv[2])
    else:
        main()
