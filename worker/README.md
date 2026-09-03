# Worker 中转 - 一键部署

## 1. 去 Cloudflare 创建 Worker（免费，不用绑卡）
1. 打开 https://dash.cloudflare.com -> 左侧 Workers & Pages -> Create -> Create Worker
2. 起名比如 `xkoc-xcancel-proxy` -> Deploy
3. 点 Edit code，把 `worker.js` 全部粘贴进去 -> Deploy

## 2. 拿到地址
地址形如 `https://xkoc-xcancel-proxy.你的账号.workers.dev`

测试：浏览器打开
`https://你的地址.workers.dev/?url=https://xcancel.com/VitalikButerin/rss`
应该能看到 XML，而不是 `whitelisted`。如果还是 whitelisted，说明 Worker 的 IP 也被 xcancel 拉黑（概率小），再告诉我。

## 3. 回到本仓库
把地址填到 GitHub Secrets 里：
`PROXY_BASE` = `https://你的地址.workers.dev`

之后 `run_brief.py` 会自动优先走这个中转，不用改别的地方。

本地测试：
`curl "https://你的地址.workers.dev/?url=https://xcancel.com/yujuhao/rss" | head`
