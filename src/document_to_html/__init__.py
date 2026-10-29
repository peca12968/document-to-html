"""Offline conversion to self-contained HTML."""

from .converter import ConversionOptions, ConversionResult, convert
from .ocr import OcrOptions

__all__ = ["ConversionOptions", "ConversionResult", "OcrOptions", "convert"]
