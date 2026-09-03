// 免费 Worker 中转：把 GitHub 的请求换成 Cloudflare 的 IP 去问 xcancel/x.com
export default {
  async fetch(request) {
    const url = new URL(request.url);
    let target = url.searchParams.get('url');
    if (!target && url.pathname !== '/' && url.pathname !== '/favicon.ico') {
      const handle = url.pathname.replace(/^\/+/, '');
      if (handle) target = `https://xcancel.com/${handle}`;
    }
    if (!target) {
      return new Response('Usage: ?url=https://xcancel.com/HANDLE/rss  or  /HANDLE/rss  or  ?url=https://x.com/HANDLE', { status: 400, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
    }
    let targetUrl;
    try { targetUrl = new URL(target); } catch { return new Response('bad url', { status: 400 }); }
    // 临时放开所有 host 方便测试，稳定后可再加白名单
    const upstream = await fetch(target, {
      headers: {
        'User-Agent': request.headers.get('User-Agent') || 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': request.headers.get('Accept') || 'application/rss+xml,application/xml,text/html,*/*',
        'Accept-Language': 'en-US,en;q=0.9',
      },
      cf: { cacheTtl: 60, cacheEverything: false },
      redirect: 'follow',
    });
    const body = await upstream.text();
    return new Response(body, {
      status: upstream.status,
      headers: {
        'Content-Type': upstream.headers.get('Content-Type') || 'text/html; charset=utf-8',
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'public, max-age=60',
      },
    });
  },
};
