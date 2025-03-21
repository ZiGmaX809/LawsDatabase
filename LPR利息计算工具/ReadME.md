## 一个LPR利息计算工具

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