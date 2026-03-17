# 国家法律法规数据库下载脚本

从 [国家法律法规数据库](https://flk.npc.gov.cn/) 下载法律文件并转换为Markdown格式。

## 功能特性

- 支持全部分类：宪法、法律、行政法规、监察法规、地方法规、司法解释
- 自动下载docx格式法律文件
- 自动转换为Markdown格式
- 支持 .doc 格式文件自动转换（macOS/Linux）
- 断点续传支持（可中断后继续）
- 自动保存法律元数据到JSON格式
- 分页自动处理
- 按分类和法律类型双层目录组织
- 快速下载模式支持

## 环境要求

- Python 3.7+
- 依赖库：`requests`, `python-docx`
- 可选：LibreOffice（Linux系统转换.doc文件需要）

## 安装

```bash
# 安装依赖
pip install requests python-docx

# Linux系统（可选，用于.doc文件转换）
sudo apt install libreoffice
```

## 使用方法

### 基本用法

```bash
# 下载所有分类
python3 flk_downloader.py --all

# 下载指定分类
python3 flk_downloader.py --category constitution
python3 flk_downloader.py --category law
python3 flk_downloader.py --category administrative_regulation
python3 flk_downloader.py --category supervision_regulation
python3 flk_downloader.py --category local_regulation
python3 flk_downloader.py --category judicial_interpretation
```

### 高级选项

```bash
# 快速批量下载（无延迟，推荐）
python3 flk_downloader.py --all --fast

# 并发下载（提高下载速度）
python3 flk_downloader.py --all --concurrent 3

# 限制页数（用于测试）
python3 flk_downloader.py --category law --pages 2 --page-size 50

# 自定义延迟时间
python3 flk_downloader.py --all --min-delay 0.05 --max-delay 0.1

# 指定输出目录
python3 flk_downloader.py --all --output /path/to/output

# 仅保存JSON信息，不下载文件
python3 flk_downloader.py --all --json-only

# 转换已下载的docx文件为markdown
python3 flk_downloader.py --convert

# 转换单个文件（用于测试或调试）
python3 flk_downloader.py --convert --file "laws_data/docx/法律/法律/中华人民共和国民法典_20200528_ff80808172.docx"

# 转换时指定输入/输出目录
python3 flk_downloader.py --convert --docx-dir /path/to/docx --md-dir /path/to/markdown

# 初始化法律版本数据库（扫描已有JSON文件）
python3 flk_downloader.py --init-db

# 重命名重复法律的Markdown文件（添加年份后缀）
python3 flk_downloader.py --dedup

# 预览模式（显示将要执行的操作但不实际执行）
python3 flk_downloader.py --dedup --dry-run

# 强制重新处理所有文件
python3 flk_downloader.py --convert --force

# 查看帮助信息
python3 flk_downloader.py --help
```

### 命令参数说明

| 参数 | 说明 |
|------|------|
| `--all` | 下载所有分类 |
| `--category CODE` | 指定分类代码（constitution/law/administrative_regulation等）|
| `--pages N` | 限制下载页数 |
| `--page-size N` | 每页获取数量（默认100） |
| `--fast` | 快速模式：无延迟 |
| `--min-delay / --max-delay` | 自定义延迟时间范围 |
| `--concurrent N` | 并发下载数量（默认1） |
| `--output DIR` | 指定输出目录 |
| `--json-only` | 仅保存JSON信息，不下载文件 |
| `--convert` | 仅转换已下载的docx文件为markdown |
| `--file PATH` | 指定单个docx文件进行转换（需与--convert一起使用） |
| `--docx-dir PATH` | docx文件目录（用于--convert模式） |
| `--md-dir PATH` | markdown输出目录（用于--convert模式） |
| `--init-db` | 初始化 law_versions.json 数据库（扫描JSON文件） |
| `--dedup` | 重命名重复法律的Markdown文件（添加年份后缀） |
| `--dry-run` | 预览模式，显示操作但不实际执行 |
| `--force` | 强制重新处理所有文件，忽略已处理标记 |
| `--db-path PATH` | 数据库文件路径 |

## 法律分类说明

| 分类代码 | 分类名称 | flfgCodeId | 数量 |
|---------|---------|------------|------|
| constitution | 宪法 | [100] | 7 |
| law | 法律 | [101,102,110,120,130,140,150,160,170,180,190,195,200] | 307 |
| administrative_regulation | 行政法规 | [201,210,215] | 611 |
| supervision_regulation | 监察法规 | [220] | 2 |
| local_regulation | 地方法规 | [221,222,230,260,270,290,295,300,305,310] | 15612 |
| judicial_interpretation | 司法解释 | [311,320,330,340,350] | 554 |

## 输出目录结构

```
laws_data/
├── logs/                        # 运行日志文件夹
│   └── download_log_*.txt       # 运行日志
├── docx/                        # 原始docx文件
│   └── {分类名称}/              # 第一层：法律分类
│       └── {法律类型}/          # 第二层：法律类型
│           └── {标题}_{日期}_{bbbs}.docx
├── markdown/                    # 转换后的markdown文件
│   └── {分类名称}/
│       └── {法律类型}/
│           └── {标题}_{日期}_{bbbs}.md
├── json/
│   └── laws/                    # 单个法律的完整JSON信息
│       └── {分类名称}/
│           └── {法律类型}/
│               └── {标题}_{日期}_{bbbs}.json
└── download_state.json         # 下载状态（断点续传）
```

## 输出文件格式

### Markdown文件格式

每个Markdown文件包含：

```markdown
# 法律标题

## 元数据
- **公布日期**: YYYY-MM-DD
- **生效日期**: YYYY-MM-DD
- **制定机关**: XXX
- **法律类型**: XXX
- **时效性**: 有效/已修改/已废止/尚未生效
- **唯一标识**: bbbs

---

## 正文

法律正文内容...
```

### 标题层级规则

- 有"第x编"时：编为 h3，章为 h4，节为 h4
- 没有"编"时：章为 h3，节为 h4
- "第x条"作为普通正文，不作为标题
- 自动跳过目录部分

### 时效性说明

时效性字段映射：
- `有效`：当前有效的法律
- `已修改`：已被修改的法律
- `已废止`：已被废止的法律
- `尚未生效`：尚未生效的法律

### JSON文件格式

每个JSON文件包含完整的法律信息：

```json
{
  "bbbs": "唯一标识",
  "title": "标题",
  "gbrq": "公布日期",
  "sxrq": "生效日期",
  "sxx": 3,
  "zdjgName": "制定机关",
  "flxz": "法律类型",
  "detail": {
    "ossFile": {
      "ossWordPath": "docx文件路径",
      "ossPdfPath": "pdf文件路径"
    },
    "content": { ... }
  },
  "fetch_time": "获取时间"
}
```

## 文件格式支持

| 格式 | 支持情况 | 说明 |
|------|----------|------|
| .docx | ✅ 完全支持 | 使用 python-docx 库 |
| .doc | ⚠️ 部分支持 | macOS 使用 textutil，Linux 使用 Libreoffice |

## 断点续传

脚本会自动保存下载状态到 `download_state.json`，中断后重新运行会自动跳过已下载的文件。

## 注意事项

1. 下载过程中请保持网络连接稳定
2. 建议先使用 `--pages` 参数测试少量数据
3. 使用 `--fast` 模式可提高下载速度
4. 某些文件可能为 .doc 格式，需要系统工具支持
5. 转换失败的文件会自动删除，下次运行会重新下载

## 依赖说明

- **requests**: HTTP请求库，用于调用API
- **python-docx**: Word文档处理库，用于读取docx文件内容

## 数据来源

所有数据来自 [国家法律法规数据库](https://flk.npc.gov.cn/)，请遵守相关法律法规和网站服务条款。

## 许可证

本项目仅供学习研究使用，请勿用于商业用途。
