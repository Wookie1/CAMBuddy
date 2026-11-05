"""panel_files skips hidden files and dev.html (a stray .fuse_hidden* once
made STEVE refuse the whole panel)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import connector  # noqa: E402


def test_panel_files_skips_hidden_and_dev(tmp_path):
    for name in ("index.html", "dev.html", ".fuse_hidden0000007700000018",
                 ".DS_Store"):
        (tmp_path / name).write_text("x")
    (tmp_path / "img.bin").write_bytes(b"\xff\xfe")
    files = connector.panel_files(str(tmp_path))
    assert sorted(files) == ["img.bin", "index.html"]
    assert files["img.bin"].startswith("base64:")


def test_real_panel_dir_is_publishable():
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel")
    files = connector.panel_files(d)
    assert "index.html" in files
    assert not any(n.startswith(".") for n in files)
