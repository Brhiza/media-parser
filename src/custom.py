"""自定义扩展：覆盖首页模板 + 注册 PWA 路由。

集中存放本仓库相对上游的所有 Flask 路由定制，便于跟随上游更新时降低冲突面。
app.py 中仅需在末尾追加一行 `from src.custom import register_custom; register_custom(app)`。
"""
from flask import render_template, send_from_directory


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
