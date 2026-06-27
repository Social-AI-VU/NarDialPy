import base64

from nardial.providers.screen.sic_adapter import SICScreenAdapter


class _DummyWebserver:
    def register_callback(self, _callback):
        return None


def test_resolve_media_src_keeps_remote_urls():
    adapter = SICScreenAdapter(webserver=_DummyWebserver())
    src = "https://example.com/image.png"
    assert adapter._resolve_media_src(src) == src


def test_resolve_media_src_inlines_assets_root_paths(tmp_path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir()
    image_path = assets_root / "example.png"
    image_path.write_bytes(b"abc")

    adapter = SICScreenAdapter(webserver=_DummyWebserver(), assets_root=assets_root)
    resolved = adapter._resolve_media_src("assets/example.png")

    assert resolved == f"data:image/png;base64,{base64.b64encode(b'abc').decode('ascii')}"


def test_resolve_media_src_rejects_assets_root_traversal(tmp_path):
    assets_root = tmp_path / "assets"
    assets_root.mkdir()
    outside_file = tmp_path / "outside.png"
    outside_file.write_bytes(b"abc")

    adapter = SICScreenAdapter(webserver=_DummyWebserver(), assets_root=assets_root)
    assert adapter._resolve_media_src("assets/../outside.png") == "assets/../outside.png"


def test_resolve_media_src_inlines_absolute_file_path(tmp_path):
    image_path = tmp_path / "example.jpg"
    image_path.write_bytes(b"jpg")
    adapter = SICScreenAdapter(webserver=_DummyWebserver())

    resolved = adapter._resolve_media_src(str(image_path))

    assert resolved == f"data:image/jpeg;base64,{base64.b64encode(b'jpg').decode('ascii')}"
