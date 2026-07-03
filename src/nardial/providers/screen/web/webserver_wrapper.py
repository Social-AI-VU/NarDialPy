from pathlib import Path

from sic_framework.services.webserver import Webserver, WebserverConf

from nardial.providers.screen.web.assets_extension import AssetsExtension


class WebServerWrapper:
    def __init__(self, web_dir, assets_root, port, allowed_origin):
        AssetsExtension.ASSETS_ROOT = assets_root

        self.webserver = Webserver(
            conf=WebserverConf(
                templates_dir=str(Path(web_dir) / "templates"),
                static_dir=str(Path(web_dir) / "static"),
                port=port,
                cors_allowed_origins=[allowed_origin],
                extensions=["nardial.providers.screen.web.assets_extension:AssetsExtension"]
            )
        )
