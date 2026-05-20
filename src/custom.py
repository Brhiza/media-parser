"""自定义扩展：覆盖首页模板 + PWA 路由 + 媒体下载代理。

集中存放本仓库相对上游的所有 Flask 路由定制，便于跟随上游更新时降低冲突面。
app.py 中仅需在末尾追加一行 `from src.custom import register_custom; register_custom(app)`。
"""
import io
import re
import zipfile
from urllib.parse import urlparse, unquote

import requests
from flask import (
    render_template, send_from_directory, request, abort, Response, stream_with_context
)


# 仅允许代理这些根域的图片/视频，防止 SSRF
_ALLOWED_DOMAINS = (
    'douyin.com', 'iesdouyin.com', 'douyinpic.com', 'douyinvod.com',
    'xiaohongshu.com', 'xhscdn.com', 'xhslink.com',
    'kuaishou.com', 'kuaishouzt.com', 'kuaishoupro.com', 'yximgs.com',
    'bilibili.com', 'hdslb.com', 'biliimg.com', 'biliapi.net',
    'weibo.com', 'weibocdn.com', 'sinaimg.cn', 'weibo.cn',
    'zhihu.com', 'zhimg.com',
    'ixigua.com', 'byteimg.com', 'bytecdn.cn',
    'youtube.com', 'ytimg.com', 'googlevideo.com',
    'tiktok.com', 'tiktokcdn.com',
    'instagram.com', 'cdninstagram.com', 'fbcdn.net',
    'twitter.com', 'x.com', 'twimg.com',
    'acfun.cn', 'acfun.com', 'acimg.cn',
    'baidu.com', 'bdstatic.com', 'baidustatic.com',
    'qq.com', 'gtimg.cn', 'gtimg.com',
    'pearvideo.com', 'videopls.com',
    'pipigx.com', 'doupai.cc',
    'huya.com', 'huyaimg.com',
    'meipai.com', 'meitudata.com',
    'pipix.com',
    'kg.qq.com',
    '6.cn',
    'xinpianchang.com',
    'izuiyou.com', 'xiaochuankeji.cn',
)

_SAFE_NAME = re.compile(r'[^\w\-.]+', re.UNICODE)
_MAX_BYTES = 200 * 1024 * 1024  # 单文件 200MB 上限
_CHUNK = 64 * 1024


def _is_allowed(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ''
        host = host.lower()
        return any(host == d or host.endswith('.' + d) for d in _ALLOWED_DOMAINS)
    except Exception:
        return False


def _guess_filename(url: str, fallback: str = 'file') -> str:
    try:
        path = urlparse(url).path
        name = unquote(path.rsplit('/', 1)[-1]) or fallback
        name = _SAFE_NAME.sub('_', name).strip('._') or fallback
        if '.' not in name:
            name = name + '.bin'
        return name[:120]
    except Exception:
        return fallback


def _fetch(url: str, timeout: int = 30):
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'
        ),
        'Referer': f'{urlparse(url).scheme}://{urlparse(url).hostname}/',
    }
    return requests.get(url, headers=headers, stream=True, timeout=timeout)


def register_custom(app):
    # 用本地自定义模板覆盖上游 / 路由
    app.view_functions['index'] = lambda: render_template('index.html')

    @app.route('/sw.js')
    def service_worker():
        response = send_from_directory(app.static_folder, 'sw.js')
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['Service-Worker-Allowed'] = '/'
        return response

    @app.route('/manifest.webmanifest')
    def manifest():
        return send_from_directory(
            app.static_folder, 'manifest.webmanifest',
            mimetype='application/manifest+json'
        )

    @app.route('/api/download')
    def download_one():
        """单文件下载代理，强制以附件形式返回。"""
        url = request.args.get('url', '').strip()
        name_override = request.args.get('name', '').strip()
        if not url or not _is_allowed(url):
            abort(400, 'url 不在允许域名列表内')

        try:
            upstream = _fetch(url)
        except requests.RequestException:
            abort(502, '下载失败')

        if upstream.status_code != 200:
            upstream.close()
            abort(upstream.status_code, '远端返回非 200')

        filename = name_override or _guess_filename(url)
        content_type = upstream.headers.get('Content-Type', 'application/octet-stream')

        def gen():
            sent = 0
            try:
                for chunk in upstream.iter_content(_CHUNK):
                    if not chunk:
                        continue
                    sent += len(chunk)
                    if sent > _MAX_BYTES:
                        break
                    yield chunk
            finally:
                upstream.close()

        resp = Response(stream_with_context(gen()), mimetype=content_type)
        resp.headers['Content-Disposition'] = (
            f"attachment; filename*=UTF-8''{filename}"
        )
        return resp

    @app.route('/api/download_zip', methods=['POST'])
    def download_zip():
        """把多张图片打包为 zip 返回。"""
        data = request.get_json(silent=True) or {}
        urls = data.get('urls') or []
        zip_name = (data.get('name') or 'album').strip()
        zip_name = _SAFE_NAME.sub('_', zip_name).strip('._') or 'album'

        if not isinstance(urls, list) or not urls:
            abort(400, 'urls 不能为空')
        if len(urls) > 200:
            abort(400, '一次最多打包 200 张')

        urls = [u for u in urls if isinstance(u, str) and _is_allowed(u)]
        if not urls:
            abort(400, '没有合法的 url')

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            seen = {}
            for idx, url in enumerate(urls, start=1):
                try:
                    r = _fetch(url, timeout=20)
                    if r.status_code != 200:
                        r.close()
                        continue
                    base = _guess_filename(url, fallback=f'img_{idx}')
                    # 保证文件名前缀有序，且避免重名
                    stem, dot, ext = base.rpartition('.')
                    stem = stem or base
                    ext = ext if dot else ''
                    candidate = f'{idx:03d}_{stem}{("." + ext) if ext else ""}'
                    while candidate in seen:
                        candidate = f'{idx:03d}_{stem}_{seen[candidate]}{("." + ext) if ext else ""}'
                    seen[candidate] = seen.get(candidate, 0) + 1

                    total = 0
                    chunks = []
                    for chunk in r.iter_content(_CHUNK):
                        total += len(chunk)
                        if total > _MAX_BYTES:
                            break
                        chunks.append(chunk)
                    r.close()
                    zf.writestr(candidate, b''.join(chunks))
                except requests.RequestException:
                    continue

        buf.seek(0)
        resp = Response(buf.getvalue(), mimetype='application/zip')
        resp.headers['Content-Disposition'] = (
            f"attachment; filename*=UTF-8''{zip_name}.zip"
        )
        return resp
