"""Separate Word COM process, with a kill-on-close job for its owned Word instance."""

from __future__ import annotations

import json
from pathlib import Path
import sys


def main() -> int:
    source, destination, status = map(Path, sys.argv[1:])
    try:
        import pythoncom
        import win32api
        import win32com.client
        import win32con
        import win32job
        import win32process
    except ImportError:
        status.write_text(json.dumps({"unavailable": True}), encoding="utf-8")
        return 2

    application = document = job = process_handle = None
    owns_application = False
    stage = "startup"
    pythoncom.CoInitialize()
    try:
        existing_processes = set(win32process.EnumProcesses())
        try:
            application = win32com.client.DispatchEx("Word.Application")
        except pythoncom.com_error:
            status.write_text(json.dumps({"unavailable": True}), encoding="utf-8")
            return 2
        stage = "isolate"
        # Word exposes Hwnd on Window, not Application (unlike Excel).
        document = application.Documents.Add(Visible=False)
        _, word_pid = win32process.GetWindowThreadProcessId(document.Windows(1).Hwnd)
        if word_pid in existing_processes:
            # Never quit or attach a job to an existing user-owned Office process.
            document.Close(SaveChanges=0)
            document = application = None
            raise RuntimeError("Word did not create an isolated process")
        owns_application = True
        job = win32job.CreateJobObject(None, "")
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        process_handle = win32api.OpenProcess(
            win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, word_pid,
        )
        win32job.AssignProcessToJobObject(job, process_handle)
        document.Close(SaveChanges=0)
        document = None
        stage = "configure"
        application.Visible = False
        application.DisplayAlerts = 0
        application.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
        application.Options.UpdateLinksAtOpen = False
        stage = "open"
        document = application.Documents.Open(
            FileName=str(source), ConfirmConversions=False, ReadOnly=True,
            AddToRecentFiles=False, Visible=False, NoEncodingDialog=True,
            PasswordDocument="", WritePasswordDocument="",
        )
        stage = "export"
        document.ExportAsFixedFormat(
            OutputFileName=str(destination), ExportFormat=17,
            OpenAfterExport=False, OptimizeFor=0, CreateBookmarks=0,
            DocStructureTags=True, BitmapMissingFonts=True,
        )
        status.write_text(json.dumps({"ok": True}), encoding="utf-8")
        return 0
    except Exception as error:
        status.write_text(json.dumps({"ok": False, "stage": stage,
                                     "error_type": type(error).__name__,
                                     "hresult": getattr(error, "hresult", None)}), encoding="utf-8")
        return 1
    finally:
        try:
            if document is not None:
                document.Close(SaveChanges=0)
        finally:
            try:
                if application is not None and owns_application:
                    application.Quit(SaveChanges=0)
            finally:
                if process_handle is not None:
                    process_handle.Close()
                if job is not None:
                    job.Close()
                pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())
