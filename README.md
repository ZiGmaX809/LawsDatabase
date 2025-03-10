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