import requests
from bs4 import BeautifulSoup

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
        else:
            print(f"请求失败，状态码: {response.status_code}，使用默认值3.45%")

    except Exception as e:
        print(f"发生错误: {e}，使用默认值3.45%")
        return 3.45  # 默认值

def main():
    # 获取一年期LPR利率
    fetch_loan_rates()

if __name__ == "__main__":
    main()
