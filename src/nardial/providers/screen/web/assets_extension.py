from flask import send_from_directory
from pathlib import Path


class AssetsExtension:
    ASSETS_ROOT = None

    def __init__(self, component):
        print("ASSETS EXTENSION LOADED", self.ASSETS_ROOT)
        self.assets_dir = Path(self.ASSETS_ROOT).resolve()

    def register_routes(self, app):
        @app.route("/assets/<path:filename>")
        def serve_assets(filename):
            print("ASSET REQUEST:", filename)
            return send_from_directory(self.assets_dir, filename)
