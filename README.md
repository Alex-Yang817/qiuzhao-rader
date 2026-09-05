# 秋招雷达 · 自动更新版（GitHub Pages + Actions）

追踪国央企秋季校园招聘的实时动态：**每天自动抓取国务院国资委官网「央企招聘」栏目**，
把最新官方校招公告推送到页面；岗位卡支持专业匹配、多维筛选、收藏与截止倒计时。

---

## 目录结构

```
秋招雷达-auto/
├─ site/                     # 网站（发布到 GitHub Pages）
│  ├─ index.html             # 单页应用（数据从下方 JSON 读取）
│  └─ data/
│     ├─ jobs.json           # 岗位库：人工核实的结构化岗位（报名截止/专业/港澳适用性）
│     ├─ announcements.json  # 官方公告动态：Actions 每天自动生成（勿手改）
│     └─ last_run.json       # 上次自动采集时间与新增数（勿手改）
├─ scraper/main.py           # 自动采集器（仅 Python 标准库）
└─ .github/workflows/daily-update.yml  # 每天 06:20 UTC 自动运行
```

## 工作原理

```
GitHub Actions（每天 14:20 北京时间自动跑，也可手动触发）
   └─ python scraper/main.py
         └─ 抓取 国资委官网·央企招聘栏目  → 解析每条公告(标题/原文链接/发布日期)
               └─ 去重合并 → site/data/announcements.json
                     └─ 有变化则自动 commit + push
                           └─ GitHub Pages 自动重新发布 → 网站更新
```

- **自动层**：官方公告动态流（谁发布了 2027 届校招、原文链接、发布日期），全部来自国资委官网，权威可靠。
- **人工层**：岗位卡（报名截止、专业方向、是否接受港澳学历等）维护在 `jobs.json`，因企业官网普遍动态渲染或带反爬、程序无法稳定读懂，必须按官方公告人工核实——页面底部已如实说明，不做机器臆断。

## 启用步骤（共 4 步，约 5 分钟）

1. **建仓库并推送**：在 GitHub 新建一个仓库（公开/私有均可），把本目录全部内容推上去：
   ```bash
   git init
   git add .
   git commit -m "init qiuzhao radar auto"
   git remote add origin https://github.com/<你的用户名>/<仓库名>.git
   git push -u origin main
   ```

2. **开启 Pages**：仓库 → Settings → Pages → Source 选 **Deploy from a branch**，
   Branch 选 `main`、文件夹选 `/site` → Save。约 1 分钟后访问：
   `https://<你的用户名>.github.io/<仓库名>/`

3. **授予 Actions 写权限**（否则自动推送会失败）：
   仓库 → Settings → Actions → General → **Workflow permissions** →
   勾选 **Read and write permissions** → Save。

4. **手动触发一次验证**：仓库 → Actions → `daily-crawl-update` → **Run workflow**，
   等它跑完，打开 `site/data/last_run.json` 应显示本次运行时间与新增条数。

之后每天 14:20（北京时间）自动运行，公告动态区会自动出现当天新发布的央企校招公告。

## 本地预览（不部署时）

```bash
cd site
python3 -m http.server 8000      # 然后浏览器打开 http://localhost:8000
```
> 注意：必须通过 http 访问；直接用 `file://` 双击打开无法跨文件读取数据。

## 维护岗位库 jobs.json（可选，建议每周）

`jobs.json` 是岗位卡数据源，字段如下，可按模板增改条目：

| 字段 | 含义 |
|---|---|
| org / cat / ind | 企业 / 类型(央企·金融央企·上海国企) / 行业 |
| title / level / minLevel | 岗位 / 学历要求(展示) / 学历门槛(用于筛选与匹配) |
| tags | 专业方向标签（与你的专业档案做匹配） |
| cities / mainCity | 工作地点 / 主地点文案 |
| scope / hk | 招聘对象 / 港澳及境外学历适用性 |
| pub / ddl / ddlNote | 发布日期 / 报名截止(ISO) / 截止说明 |
| duty / req | 岗位职责 / 任职要求 |
| link / linkText / srcNote | 官方报名入口 / 来源核实说明 |
| status | `open` 报名中 / `soon` 预告 |

新增一家企业时，建议先按其官方公告核实上述字段再写入；无法核实的字段如实留空并注明，不要臆造。

## 想改采集频率？

编辑 `.github/workflows/daily-update.yml` 里的 cron（UTC 时间）：
每天一次保持 `cron: "20 6 * * *"`；想一天两次可改 `"20 6,18 * * *"`。

## 已知边界（如实说明）

- 数据源为国资委官网栏目（政府网站、可稳定服务端抓取）；各央企**自身**招聘官网多为动态页/带反爬（实测中国电信对程序返回 412、国家电网需安全验证、国聘为 JS 应用），不适合服务器端直抓，故不作采集源。
- 公告动态是"标题+原文链接"级信息；报名起止、专业、学历等结构化字段仍在 `jobs.json` 中人工核实维护。
- GitHub Actions 免费额度对个人仓库足够（每天一次远低于限额）；若抓取偶尔失败，脚本会保留上次数据并记录错误，不会中断或伪造。
