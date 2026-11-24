import pytest

from scripts.synthetic_pdf import make_pdf


def pytest_addoption(parser):
    parser.addoption("--browser-channel", default=None, help="Run browser checks with chromium or msedge")
    parser.addoption("--ocr-integration", action="store_true", help="Run real Tesseract OCR integration checks")

@pytest.fixture
def source_pdf(tmp_path):
    return make_pdf(tmp_path / "example.pdf")
