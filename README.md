# LawsDatabase

—— 旨在强化 AI 知识库，弱化 AI 幻觉

法律数据库综合抓取工具，整合三个法律数据源，统一通过交互式菜单运行。

## 安装

```shell
pip install -r requirements.txt
```

依赖：`requests`、`beautifulsoup4`、`python-docx`（docx 转换在 macOS 用 `textutil`、Linux 用 `libreoffice`）。

## 快速开始

```shell
python main.py
```

进入交互式总菜单，选择数据源：

1. **法答网精选答问（FDW）** —— 抓取"法答网精选答问"
2. **国家法律法规数据库（FLK）** —— 下载法律条文（docx → Markdown）
3. **人民法院案例库（PCC）** —— 抓取案例（需 token）

各源也支持独立命令行高级模式（见下）。

## 数据源

### 1. 法答网精选答问（FDW）

来源：court.gov.cn。抓取"法答网精选答问"各批次，转 Markdown，基于下载记录增量去重。

```shell
python -m laws_database.sources.fdw_qa --download   # 下载新内容（默认）
python -m laws_database.sources.fdw_qa --rename     # 重命名旧格式文件
```

### 2. 国家法律法规数据库（FLK）

来源：flk.npc.gov.cn。按分类下载法律 docx 并转 Markdown，支持断点续传、多版本同名法律管理（年份后缀）、整理到知识库目录。

| 分类代码 | 分类名称 |
|---------|---------|
| constitution | 宪法 |
| law | 法律 |
| administrative_regulation | 行政法规 |
| supervision_regulation | 监察法规 |
| judicial_interpretation | 司法解释 |
| local_regulation | 地方法规 |

```shell
python -m laws_database.sources.flk_laws --all --fast      # 下载全部分类（快速，排除地方法规）
python -m laws_database.sources.flk_laws --category law    # 下载指定分类
python -m laws_database.sources.flk_laws --convert         # 转换已下载 docx
python -m laws_database.sources.flk_laws --organize        # 整理到知识库目录
python -m laws_database.sources.flk_laws --dedup           # 去重重命名
python -m laws_database.sources.flk_laws --init-db         # 初始化版本数据库
```

### 3. 人民法院案例库（PCC）

来源：rmfyalk.court.gov.cn。按案件类型抓取案例（需 token），增量更新、整理分类。

| 类型 | 代码 | sort_id |
|------|------|---------|
| 刑事 | criminal | 10000 |
| 民事 | civil | 20000 |
| 行政 | administrative | 30000 |
| 执行 | execution | 40000 |
| 国家赔偿 | compensation | 50000 |

**Token 获取**（每个 token 每天约 100 次请求，**仅运行时输入、不持久化**）：

- 网页端：登录 [人民法院案例库](https://rmfyalk.court.gov.cn)，开发者工具执行：

  ```js
  document.cookie.split(';').map(c => c.trim().split('=')).find(pair => pair[0] === 'faxin-cpws-al-token')?.[1]
  ```

- 小程序端：微信小程序"人民法院案例库"登录后抓包。

```shell
python -m laws_database.sources.court_cases             # 下载（增量，交互输入 token）
python -m laws_database.sources.court_cases --full      # 全量模式
python -m laws_database.sources.court_cases --organize  # 仅整理已下载文件
python -m laws_database.sources.court_cases --count     # 统计目标目录文件数
```

## 配置

- `configs/config.json`：共享基础配置（数据目录、API 端点、分页参数），纳入版本控制。
- `configs/*.local.json`：各源用户特定配置（整理目录、目标目录），被 gitignore，不提交。
- token 绝不写入配置文件。

## 目录结构

```
LawsDatabase/
├── main.py                 # 统一入口
├── laws_database/          # 主包
│   ├── core/               # 公共模块（HTTP / 日志 / 文件名 / 下载记录）
│   ├── sources/            # 三个数据源（fdw_qa / flk_laws / court_cases）
│   ├── config.py           # 统一配置加载
│   └── menu.py             # 交互式菜单
├── configs/                # 配置文件
├── data/                   # 数据输出（fdw_qa / laws / court_cases）
└── tests/                  # 单元测试
```

## 测试

```shell
pytest tests/
```
