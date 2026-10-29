from pathlib import Path
import subprocess

import pytest

from document_to_html import ConversionOptions, convert
from document_to_html import backends
from document_to_html.errors import BackendUnavailable, ConversionError
from conftest import make_pdf


def test_word_adapter_pipeline_uses_temporary_pdf_and_cleans_it(tmp_path, monkeypatch):
    source = tmp_path / "sample.doc"
    source.write_bytes(b"mock input")
    intermediate = []
    def export(self, source, directory, timeout):
        output = make_pdf(directory / "generated.pdf")
        intermediate.append(output)
        return output
    monkeypatch.setattr(backends.LibreOfficeBackend, "export_pdf", export)
    result = convert(source, options=ConversionOptions(backend="libreoffice"))
    assert result.pages == 2
    assert result.backend == "LibreOffice"
    assert not intermediate[0].exists()
    assert source.read_bytes() == b"mock input"


def test_auto_falls_back_only_for_unavailable_backend(tmp_path, monkeypatch):
    def unavailable(*args):
        raise BackendUnavailable("missing")
    monkeypatch.setattr(backends.MicrosoftWordBackend, "export_pdf", unavailable)
    monkeypatch.setattr(backends.LibreOfficeBackend, "export_pdf", lambda *args: tmp_path / "output.pdf")
    assert backends.export_word(tmp_path / "input.doc", tmp_path, "auto", 10)[1] == "LibreOffice"
    def failed(*args):
        raise ConversionError("conversion failed")
    monkeypatch.setattr(backends.MicrosoftWordBackend, "export_pdf", failed)
    with pytest.raises(ConversionError, match="conversion failed"):
        backends.export_word(tmp_path / "input.doc", tmp_path, "auto", 10)


def test_libreoffice_checks_output_and_uses_private_profile(tmp_path, monkeypatch):
    engine = backends.LibreOfficeBackend()
    monkeypatch.setattr(engine, "_find_executable", lambda: "soffice")
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(backends, "_run_office", run)
    with pytest.raises(ConversionError, match="無法轉換"):
        engine.export_pdf(tmp_path / "file.doc", tmp_path, 5)
    assert "--headless" in commands[0]
    assert any(argument.startswith("-env:UserInstallation=file:") for argument in commands[0])
    profile = (tmp_path / "libreoffice-profile/user/registrymodifications.xcu").read_text()
    assert 'MacroSecurityLevel' in profile and '<value>3</value>' in profile
    assert 'AutoCheckEnabled' in profile and '<value>false</value>' in profile


def test_office_process_timeout_is_bounded():
    import sys
    import time
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        backends._run_office([sys.executable, "-c", "import time; time.sleep(60)"], timeout=1)
    assert time.monotonic() - start < 15
