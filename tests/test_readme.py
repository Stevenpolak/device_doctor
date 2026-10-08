"""The README must also render inside HACS, not only on GitHub."""

from __future__ import annotations

from pathlib import Path
import re

README = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")


def test_images_use_absolute_urls() -> None:
    """HACS shows the README outside GitHub, so relative image paths break."""
    sources = re.findall(r'src="([^"]+)"', README) + re.findall(
        r"!\[[^\]]*\]\(([^)]+)\)", README
    )
    relative = [src for src in sources if not src.startswith("https://")]
    assert not relative, f"relative image paths: {relative}"


def test_no_picture_tags() -> None:
    """HACS shows <picture>/<source> as plain text; use a plain <img>."""
    assert "<picture" not in README
    assert "<source" not in README
