# LawsDatabase

—— 旨在强化AI知识库，弱化AI幻觉

## 📎 法答网精选问答

直接运行`court_content_scraper.py`脚本即可抓取

## 📎 人民法院案例库

运行`court_data_processor.py`脚本，通过交互式流程拉取全量案例库列表，并根据拉取内容进行整理及增量更新。

### 支持的案件类型

| 类型 | 代码 | sort_id |
|------|------|---------|
| 刑事 | criminal | 10000 |
| 民事 | civil | 20000 |
| 行政 | administrative | 30000 |
| 执行 | execution | 40000 |
| 国家赔偿 | compensation | 50000 |

### Token获取

每个token每天可请求约100次。有两种获取途径：

#### 1. 网页端

[人民法院案例库](https://rmfyalk.court.gov.cn)右上角登录后，在浏览器开发者工具中获取：

```js
document.cookie.split(';').map(c => c.trim().split('=')).find(pair => pair[0] === 'faxin-cpws-al-token')?.[1]
```

#### 2. 小程序端

微信小程序搜索`人民法院案例库`，登录后抓取请求链接获取。

### 使用方法

```shell
# 直接运行，进入交互式流程
python court_data_processor.py

# 统计目标文件夹中的文件数量
python court_data_processor.py --count

# 显示帮助信息
python court_data_processor.py --help
```

### 交互式流程

1. 输入token（首次运行或需更新时）
2. 选择案件类型
3. 自动执行以下步骤：
   - 获取案例列表（最多100页）
   - 下载案例详情并转为Markdown
   - 整理文件到分类目录

### 目录结构

```
PCC_Database/
├── downloaded_markdown/          # Markdown文件
│   ├── 刑事/
│   ├── 民事/
│   ├── 行政/
│   ├── 执行/
│   └── 国家赔偿/
├── court_data/pages/             # JSON数据
│   ├── 刑事/
│   ├── 民事/
│   ├── 行政/
│   ├── 执行/
│   └── 国家赔偿/
├── downloaded_records_*.txt      # 增量更新记录
└── court_config.json             # 配置文件
```

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

## 📎 国家法律法规数据库

从 [国家法律法规数据库](https://flk.npc.gov.cn/) 下载法律文件并转换为Markdown格式。

### 功能特性

- 支持全部分类：宪法、法律、行政法规、监察法规、地方法规、司法解释
- 自动下载docx格式法律文件
- 自动转换为Markdown格式
- 支持 .doc 格式文件自动转换（macOS/Linux）
- 断点续传支持（可中断后继续）
- 自动保存法律元数据到JSON格式
- 分页自动处理
- 按分类和法律类型双层目录组织
- 快速下载模式支持

### 环境要求

- Python 3.7+
- 依赖库：`requests`, `python-docx`
- 可选：LibreOffice（Linux系统转换.doc文件需要）

### 使用方法

```bash
# 进入Laws目录
cd Laws

# 安装依赖
pip install requests python-docx

# 下载所有分类
python3 flk_downloader.py --all

# 快速批量下载（推荐）
python3 flk_downloader.py --all --fast

# 下载指定分类
python3 flk_downloader.py --category law
python3 flk_downloader.py --category administrative_regulation
python3 flk_downloader.py --category judicial_interpretation

# 仅保存JSON信息，不下载文件
python3 flk_downloader.py --all --json-only
```

### 法律分类说明

| 分类代码 | 分类名称 | 数量 |
|---------|---------|------|
| constitution | 宪法 | 7 |
| law | 法律 | 307 |
| administrative_regulation | 行政法规 | 611 |
| supervision_regulation | 监察法规 | 2 |
| local_regulation | 地方法规 | 15612 |
| judicial_interpretation | 司法解释 | 554 |

### 输出目录结构

```
Laws/laws_data/
├── logs/                        # 运行日志
├── docx/                        # 原始docx文件
│   └── {分类名称}/{法律类型}/
├── markdown/                    # 转换后的markdown文件
│   └── {分类名称}/{法律类型}/
├── json/                        # 单个法律的完整JSON信息
│   └── laws/{分类名称}/{法律类型}/
└── download_state.json          # 下载状态（断点续传）
```