import pytest

from document_to_html import ConversionOptions, convert
from scripts.verify_html import verify
from conftest import make_pdf


@pytest.mark.parametrize("rotation", [0, 90])
def test_browser_search_render_print_and_mobile(tmp_path, request, rotation):
    channel = request.config.getoption("--browser-channel")
    if not channel:
        pytest.skip("Use --browser-channel chromium (or msedge) for browser integration checks")
    source = make_pdf(tmp_path / "browser.pdf", rotation=rotation)
    result = convert(source, options=ConversionOptions(dpi=96))
    report = verify(result.output, tmp_path / "browser-artifacts", channel)
    assert report["browser_find"]
    assert report["printed_pages"] == 2
