## 一个LPR利息计算工具

### 使用说明

该脚本将会自动拉取中国银行公布的LPR各期利率并且进行分段计算利息并汇总

### 使用方法

安装依赖

```shell
pip install ds4 python-docx requests pandas
```

```python
python LPR_Calculator.py --amount 100000 --start 2023-01-01 --end 2023-12-31 --term one_year --day-count 365 --export "我的借款利息报告.docx"
```

### 参数解析

* --amount: 贷款金额（人民币）
* --start: 开始日期（YYYY-MM-DD）
* --end: 结束日期（YYYY-MM-DD）
* --term: LPR期限（`one_year` 或 `five_year`）
* --day-count: 计息天数惯例（`360` 或 `365`）
* --update: 可选标志，强制更新LPR数据
* --export: 导出docx文件路径
* --no-export: 跳过文件导出