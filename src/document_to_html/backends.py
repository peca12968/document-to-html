"""Word adapters. All intermediate documents live in a temporary directory."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
from typing import Protocol

from .errors import BackendUnavailable, ConversionError


def _run_office(command: list[str], timeout: int) -> subprocess.CompletedProcess:
    """On timeout/cancellation, terminate only this invocation's process tree."""
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {"start_new_session": True}
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **flags) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            if sys.platform == "win32":
                if process.poll() is None:
                    taskkill = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/taskkill.exe"
                    try:
                        subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                                       capture_output=True, timeout=10, check=False,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
                    except (OSError, subprocess.TimeoutExpired):
                        process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


class WordBackend(Protocol):
    name: str

    def export_pdf(self, source: Path, directory: Path, timeout: int) -> Path: ...


class MicrosoftWordBackend:
    name = "Microsoft Word"

    def export_pdf(self, source: Path, directory: Path, timeout: int) -> Path:
        if sys.platform != "win32":
            raise BackendUnavailable("Microsoft Word 引擎僅適用於 Windows。")
        destination = directory / "word.pdf"
        status = directory / "word-status.json"
        try:
            process = _run_office(
                [sys.executable, "-m", "document_to_html.word_worker",
                 str(source), str(destination), str(status)],
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise ConversionError("Word 轉檔逾時；請檢查文件能否正常開啟。") from error
        result = json.loads(status.read_text(encoding="utf-8")) if status.exists() else {}
        if result.get("unavailable"):
            raise BackendUnavailable("未找到可使用的 Microsoft Word / pywin32。")
        if process.returncode or not destination.is_file():
            raise ConversionError("Microsoft Word 無法轉換文件；請檢查檔案是否損毀、加密或受保護。")
        return destination


class LibreOfficeBackend:
    name = "LibreOffice"

    def __init__(self, executable: str | None = None):
        self.executable = executable

    def _find_executable(self) -> str:
        explicit = self.executable or os.environ.get("LIBREOFFICE_PATH")
        if explicit:
            resolved = shutil.which(explicit)
            if resolved:
                return resolved
            raise BackendUnavailable("LIBREOFFICE_PATH 或 --libreoffice 指定的程式不存在。")
        candidates = [shutil.which("soffice"), shutil.which("libreoffice")]
        if sys.platform == "win32":
            for variable in ("ProgramFiles", "ProgramFiles(x86)"):
                root = os.environ.get(variable)
                if root:
                    candidates.append(str(Path(root) / "LibreOffice/program/soffice.com"))
                    candidates.append(str(Path(root) / "LibreOffice/program/soffice.exe"))
        elif sys.platform == "darwin":
            candidates.append("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return candidate
        raise BackendUnavailable("請安裝 LibreOffice，或指定 LIBREOFFICE_PATH。")

    def export_pdf(self, source: Path, directory: Path, timeout: int) -> Path:
        executable = self._find_executable()
        profile = directory / "libreoffice-profile"
        profile_user = profile / "user"
        profile_user.mkdir(parents=True)
        # Isolated profile: never reuse or change the user's Office preferences.
        (profile_user / "registrymodifications.xcu").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            '</item><item oor:path="/org.openoffice.Office.Writer/Content/Update">'
            '<prop oor:name="Link" oor:op="fuse"><value>2</value></prop>'
            '</item><item oor:path="/org.openoffice.Office.Update/Update">'
            '<prop oor:name="Enabled" oor:op="fuse"><value>false</value></prop>'
            '</item><item oor:path="/org.openoffice.Office.Jobs/Jobs/UpdateCheck/Arguments">'
            '<prop oor:name="AutoCheckEnabled" oor:op="fuse"><value>false</value></prop>'
            '<prop oor:name="AutoDownloadEnabled" oor:op="fuse"><value>false</value></prop>'
            '</item></oor:items>', encoding="utf-8",
        )
        destination_directory = directory / "libreoffice-pdf"
        destination_directory.mkdir()
        try:
            result = _run_office(
                [executable, f"-env:UserInstallation={profile.as_uri()}",
                 "--headless", "--nologo", "--nodefault", "--norestore",
                 "--convert-to", "pdf:writer_pdf_Export",
                 "--outdir", str(destination_directory), str(source)],
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise ConversionError("LibreOffice 轉檔逾時；請檢查文件是否需要密碼或互動操作。") from error
        destination = destination_directory / f"{source.stem}.pdf"
        if result.returncode or not destination.is_file():
            raise ConversionError("LibreOffice 無法轉換文件；請確認檔案可開啟且未加密。")
        return destination


def export_word(
    source: Path, directory: Path, backend: str, timeout: int,
    libreoffice: str | None = None,
) -> tuple[Path, str]:
    if backend == "word":
        engines: list[WordBackend] = [MicrosoftWordBackend()]
    elif backend == "libreoffice":
        engines = [LibreOfficeBackend(libreoffice)]
    else:
        engines = [MicrosoftWordBackend(), LibreOfficeBackend(libreoffice)]
    for index, engine in enumerate(engines):
        try:
            return engine.export_pdf(source, directory, timeout), engine.name
        except BackendUnavailable:
            if index == len(engines) - 1:
                raise
    raise AssertionError("No backend selected")
