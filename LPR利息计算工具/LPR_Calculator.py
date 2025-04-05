import requests
from bs4 import BeautifulSoup
import datetime
import pandas as pd
import argparse
import os
import sys
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL


def fetch_loan_rates():
    """爬取中国银行贷款利率数据"""
    url = "https://www.bankofchina.com/fimarkets/lilv/fd32/201310/t20131031_2591219.html"

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        response.encoding = 'utf-8'  # 确保中文正确显示

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')

            # 首先查找页面中的所有表格
            tables = soup.find_all('table')

            # 查找包含"LPR"的表格
            lpr_table = None
            for table in tables:
                if 'LPR' in table.get_text():
                    lpr_table = table
                    break

            # 如果找到了表格，解析其中的数据
            if lpr_table:
                rows = lpr_table.find_all('tr')
                all_text = []
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if cells:
                        row_text = ' '.join(cell.get_text(strip=True)
                                            for cell in cells)
                        all_text.append(row_text)

                with open('LPR_Data.txt', 'w', encoding='utf-8') as f:
                    f.write('\n'.join(all_text))
                    f.close()

            return True
        else:
            print(f"请求失败，状态码: {response.status_code}")
            return False

    except Exception as e:
        print(f"发生错误: {e}")
        return False


def load_lpr_data(file_path='LPR_Data.txt', check_update=True):
    """从文件加载LPR数据，并转换为DataFrame，如果数据过旧则自动更新"""
    try:
        # 尝试加载现有数据
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 跳过标题行
        data = []
        for line in lines[1:]:  # 跳过第一行（标题行）
            parts = line.strip().split()
            if len(parts) >= 3:
                date = parts[0]
                one_year_rate = float(parts[1].replace('%', '')) / 100
                five_year_rate = float(parts[2].replace('%', '')) / 100
                data.append([date, one_year_rate, five_year_rate])

        # 创建DataFrame
        df = pd.DataFrame(
            data, columns=['date', 'one_year_rate', 'five_year_rate'])
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')  # 确保按日期排序

        # 只在第一次调用时检查更新，避免死循环
        if check_update and len(df) > 0:
            today = datetime.datetime.now()
            last_date = df['date'].iloc[-1]

            if today > last_date + datetime.timedelta(days=30):
                print("数据已超过30天，正在更新...")
                # 调用更新函数
                update_successful = fetch_loan_rates()

                # 只有在更新成功的情况下才重新加载
                if update_successful:
                    # 设置check_update为False，避免死循环
                    return load_lpr_data(file_path, check_update=False)
                else:
                    print("更新失败，使用当前数据")

        return df
    except Exception as e:
        print(f"加载LPR数据时发生错误: {e}")
        return None


def calculate_interest(amount, start_date, end_date, lpr_data, term='one_year', mag=1, gap="no_tail", day_count=365):
    """计算利息并返回结果"""
    rate_column = 'one_year_rate' if term == 'one_year' else 'five_year_rate'
    gap_days = 1 if gap == "both" else 0

    # 检查开始日期是否在LPR数据范围内
    if start_date < lpr_data['date'].min():
        return f"错误: 开始日期早于LPR数据范围（最早数据日期：{lpr_data['date'].min().strftime('%Y-%m-%d')}）"

    # 获取开始日期之前的最后一个LPR变更
    initial_rate_row = lpr_data[lpr_data['date'] <= start_date].iloc[-1]
    initial_rate = initial_rate_row[rate_column]

    # 获取计算期间内的所有LPR变更日期
    rate_changes = lpr_data[(lpr_data['date'] > start_date)
                            & (lpr_data['date'] <= end_date)]

    # 初始化利息总额
    total_interest = 0
    calculation_details = []

    # 处理第一个阶段
    current_date = start_date
    current_rate = initial_rate

    # 遍历所有LPR变更日期
    for _, row in rate_changes.iterrows():
        end_segment = row['date']
        days = (end_segment - current_date).days
        interest = amount * current_rate * mag * days / day_count
        total_interest += interest

        calculation_details.append({
            'start_date': current_date.strftime('%Y-%m-%d'),
            'end_date': (end_segment - datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
            'days': days,
            'rate': current_rate,
            'interest': interest
        })

        current_date = end_segment
        current_rate = row[rate_column]

    # 处理最后一个阶段
    days = (end_date - current_date).days + gap_days
    interest = amount * current_rate * mag * days / day_count
    total_interest += interest

    calculation_details.append({
        'start_date': current_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'days': days,
        'rate': current_rate,
        'interest': interest
    })

    return {
        'total_interest': total_interest,
        'calculation_details': calculation_details,
        'status': 'success'
    }


def main(args=None):
    """主函数，支持命令行参数和直接调用"""
    if args is None:
        args = sys.argv[1:]

    parser = argparse.ArgumentParser(description='根据LPR计算利息')
    parser.add_argument('--amount', type=float, required=True, help='贷款金额')
    parser.add_argument('--start', type=str, required=True,
                       help='开始日期（格式：YYYY-MM-DD）')
    parser.add_argument('--end', type=str, required=True,
                       help='结束日期（格式：YYYY-MM-DD）')
    parser.add_argument('--term', type=str, choices=['one_year', 'five_year'], default='one_year',
                       help='LPR期限（one_year: 一年期，five_year: 五年期以上）')
    parser.add_argument('--mag', type=int, default=1,
                       help='约定LPR倍数（默认：1倍）')
    parser.add_argument('--gap', type=str, choices=['no_tail', 'both'], default='no_tail',
                       help='天数算法：no_tail: 算头不算尾，both: 两头都算（默认：no_tail）')
    parser.add_argument('--day-count', type=int, choices=[360, 365], default=365,
                       help='计算年度天数：360或365（默认：365）')
    
    try:
        args = parser.parse_args(args)
    except:
        return {'status': 'error', 'message': '参数解析失败'}

    # 加载LPR数据
    lpr_data = load_lpr_data()
    if lpr_data is None:
        return {'status': 'error', 'message': '无法加载LPR数据'}

    try:
        start_date = datetime.datetime.strptime(args.start, '%Y-%m-%d')
        end_date = datetime.datetime.strptime(args.end, '%Y-%m-%d')
    except:
        return {'status': 'error', 'message': '日期格式错误，应为YYYY-MM-DD'}

    # 计算利息
    result = calculate_interest(
        args.amount,
        start_date,
        end_date,
        lpr_data,
        args.term,
        args.mag,
        args.gap,
        args.day_count
    )

    return result


if __name__ == "__main__":
    result = main()
    if isinstance(result, dict) and result.get('status') == 'error':
        print(result['message'])
        sys.exit(1)
    elif isinstance(result, dict):
        print(f"总利息: {result['total_interest']:.2f}元")
    else:
        print(result)
