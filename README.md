# DAZA Brief — X/Twitter 每日情报简报

自动扫描你关注的 X/Twitter 博主，用 AI 分析帖子价值，生成一份可直接阅读的 HTML 日报。部署到 GitHub Pages 后，每天定时更新，打开专属网址即可阅读。

## 快速开始（GitHub Pages 部署）

### 1. Fork 本仓库

### 2. 设置 Secrets

在仓库 Settings → Secrets and variables → Actions → Secrets，添加：

| Secret | 说明 |
|--------|------|
| `AI_API_KEY` | LLM API 密钥（必填） |
| `AI_BASE_URL` | API 地址，如 `https://api.deepseek.com/v1` |
| `AI_MODEL` | 模型名，如 `deepseek-chat`（默认 `gpt-4o-mini`） |

### 3. 编辑博主列表

编辑仓库根目录的 `watchlist.txt`，一行一个用户名（`@` 前缀可有可无）：

```
VIP8888883
Ludamao_com
yujuhao
```

### 4. 调整更新频率（可选）

编辑 `config/schedule.json`：

```json
{
  "interval_minutes": 360,
  "window": "12h"
}
```

然后同步修改 `.github/workflows/brief.yml` 中的 cron 表达式（UTC 时间）。

### 5. 开启 GitHub Pages

Settings → Pages → Source: Deploy from a branch → 选择 `gh-pages` / `(root)` → Save。

### 6. 手动触发第一次运行

Actions → DAZA Brief → Run workflow → Run workflow。

完成后访问 `https://<你的用户名>.github.io/<仓库名>/` 即可看到最新简报。

## 本地运行

```bash
# 安装 Python 3.10+
# 无需安装任何第三方依赖

# 配置 API（二选一）
# 方式 A：创建 .env 文件
echo 'AI_API_KEY=sk-xxx' > .env
echo 'AI_BASE_URL=https://api.deepseek.com/v1' >> .env
echo 'AI_MODEL=deepseek-chat' >> .env

# 方式 B：设置环境变量
export AI_API_KEY=sk-xxx
export AI_BASE_URL=https://api.deepseek.com/v1
export AI_MODEL=deepseek-chat

# 编辑 watchlist.txt 添加博主
# 运行
python run_brief.py

# 或使用 CLI
python -m koc run-v2 --watchlist watchlist.txt --output output
```

## 命令参考

```bash
python -m koc run-v2          # 运行 V2 管道，生成日报
python -m koc run-v2 --watchlist my_list.txt --output my_output
python -m koc eval-v2         # 评估 AI 分类质量
```

## 站点结构

```
output/
  index.html              # 首页 = 最新完整报告
  .nojekyll
  archive/
    index.html            # 历史运行索引
    2026-06-12/
      run-1/              # 当天第 1 次更新
        report.html
        run.json
      run-2/              # 当天第 2 次更新（不会覆盖）
        report.html
        run.json
```

## 项目结构

```
koc/
  cli.py              # 命令行入口
  v2_pipeline.py      # V2 AI 管道（质量分类→日报→画像→深读）
  v2_report.py        # HTML 报告渲染
  v2_eval.py          # 评估工具
  robust_scanner.py   # RSS 扫描器（多实例容灾）
  reader.py           # 正文抓取
  llm.py              # LLM 客户端
  enrich.py           # 博主信息 + 互动数据
  watchlist.py        # 关注列表加载
  rss_utils.py        # RSS 解析工具
  models.py           # 数据模型
  config.py           # 配置加载
  output.py           # 进度输出
  url_normalizer.py   # URL 规范化
  content_cleaner.py  # 正文清洗
  http.py             # HTTP 工具
```

## FAQ

**Q: 为什么访问网址是 404？**
A: 确保 GitHub Pages 已开启，Source 选 `gh-pages` 分支。第一次部署后等待 1-2 分钟。

**Q: 如何更改更新频率？**
A: 编辑 `config/schedule.json` 的 `interval_minutes`，并同步修改 `.github/workflows/brief.yml` 中的 cron。

**Q: 需要费用吗？**
A: GitHub Actions 公开仓库免费。LLM API 根据用量收费，250 博主每天 4 次约 $1-3/月。
