// 免费 Worker 中转：把 GitHub 的请求换成 Cloudflare 的 IP 去问 xcancel
// 部署后，用 https://你的worker.workers.dev/?url=https://xcancel.com/xxx/rss 即可
export default {
  async fetch(request) {
    const url = new URL(request.url);
    let target = url.searchParams.get('url');
    // 也支持路径直传：/VitalikButerin/rss
    if (!target && url.pathname !== '/' && url.pathname !== '/favicon.ico') {
      const handle = url.pathname.replace(/^\/+/, '');
      if (handle) target = `https://xcancel.com/${handle}`;
    }
    if (!target) {
      return new Response('Usage: ?url=https://xcancel.com/HANDLE/rss  or  /HANDLE/rss', { status: 400, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
    }
    let targetUrl;
    try { targetUrl = new URL(target); } catch { return new Response('bad url', { status: 400 }); }
    const allowed = ['xcancel.com', 'rss.xcancel.com', 'nitter.net', 'nitter.poast.org', 'nitter.privacydev.net'];
    if (!allowed.some(h => targetUrl.hostname === h || targetUrl.hostname.endsWith('.' + h))) {
      return new Response('host not allowed: ' + targetUrl.hostname, { status: 403 });
    }
    const upstream = await fetch(target, {
      headers: {
        'User-Agent': request.headers.get('User-Agent') || 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Accept': request.headers.get('Accept') || 'application/rss+xml,application/xml,*/*',
      },
      cf: { cacheTtl: 60, cacheEverything: false },
    });
    const body = await upstream.text();
    // 透传状态和内容类型，跨域放开方便调试
    return new Response(body, {
      status: upstream.status,
      headers: {
        'Content-Type': upstream.headers.get('Content-Type') || 'application/rss+xml; charset=utf-8',
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'public, max-age=60',
      },
    });
  },
};
