# LawsDatabase

—— 旨在强化AI知识库，弱化AI幻觉

## 📎 法答网精选问答

直接运行`court_content_scraper.py`脚本即可抓取

## 📎 人民法院案例库

### 需自行获取tokens
有两个途径可以获取tokens，每个token每天可以请求100次json。

#### 1.网页

[人民法院案例库](https://rmfyalk.court.gov.cn)右上角登录后使用如下代码获取

```js
document.cookie.split(';').map(c => c.trim().split('=')).find(pair => pair[0] === 'faxin-cpws-al-token')?.[1]
```

#### 2.小程序

微信小程序搜索`人民法院案例库`，登录后抓取请求链接获取

### 使用

1.获取tokens后自行填入`get_pages_json.py`脚本以获取分页json数据，默认抓取民事类案件，每页300项，会根据total自动分页全量抓取（该api请求次数似乎不影响总体请求次数，但也别请求太多）；

2.将tokens填入`doanload2md.py`后进行案例下载为MarkDown格式，每天每个token只能请求100次左右，下载前会匹配`download_records.txt`是否已经下载；

3.`organize_court_files.py`则是根据分页json数据中的案由信息按文件夹整理下载后的MarkDown文件；

## 📎 LPR利息计算工具

### 脚本功能

1. 根据中国银行公布的LPR各期利率进行分段计算
2. 判断本地LPR数据获取是否>30天并进行自动更新
3. 支持自定义自然年计数基准为360天或者365天
4. 支持自定义LPR倍数（1倍至法定最高4倍）
5. 支持自定义计息天数（算头不算尾或者两头都算）
6. 支持直接导出Word文档

### 使用方法

安装依赖

```shell
# 使用pip安装所有依赖
pip install -r requirements.txt
```

运行

```python
python LPR_Calculator.py --amount 100000 --start 2023-01-01 --end 2024-12-31 --term one_year --day-count 365 --mag 4 --gap both --export "我的借款利息报告.docx"
```

### 参数解析

* --amount: 贷款金额（人民币）
* --start: 开始日期（YYYY-MM-DD）
* --end: 结束日期（YYYY-MM-DD）
* --term: LPR期限（`one_year` 或 `five_year`），默认为1年息
* --day-count: 自然年计数基准（`360` 或 `365`），默认为365天
* --mag: LPR约定倍率，默认为1倍
* --gap: 计息天数（`no_tail` 或 `both`），默认为算头不算尾
* --update: 可选标志，强制更新LPR数据
* --export: 导出docx文件路径
* --no-export: 跳过文件导出