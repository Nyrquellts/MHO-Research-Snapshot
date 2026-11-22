"""Classify module names and paths for offline reports.

The application, engine, dependency, and tooling rules use the synthetic names in
the example traces. Reports keep the matched rule alongside each classification.
"""
from __future__ import annotations

import os
from enum import Enum


class Owner(str, Enum):
    APPLICATION = "APPLICATION"
    ENGINE = "ENGINE"
    DEPENDENCY = "DEPENDENCY"
    THIRD_PARTY = "THIRD_PARTY"
    WINDOWS = "WINDOWS"
    TOOLING = "TOOLING"
    UNKNOWN = "UNKNOWN"


_TOOLING_TOKENS = ("sampleapp_recording", "blackbox")
_DEPENDENCY_TOKENS = ("exampledependency",)
_THIRD_PARTY_EXACT = {"mss32.dll", "binkw32.dll", "bink2w32.dll"}
_THIRD_PARTY_PREFIX = ("bink", "gfx", "scaleform", "physx", "nvcuda", "nvapi", "fmod")
# Windows system modules: a set of exact basenames plus a few prefixes. Not
# exhaustive -- anything under the Windows directory is caught by path, below.
_WINDOWS_EXACT = {
    "ntdll.dll", "kernel32.dll", "kernelbase.dll", "user32.dll", "gdi32.dll",
    "gdi32full.dll", "gdiplus.dll", "advapi32.dll", "ws2_32.dll", "wsock32.dll",
    "mswsock.dll", "ole32.dll", "oleaut32.dll", "combase.dll", "rpcrt4.dll",
    "sechost.dll", "shell32.dll", "shlwapi.dll", "shcore.dll", "imm32.dll",
    "msctf.dll", "uxtheme.dll", "dwmapi.dll", "version.dll", "apphelp.dll",
    "setupapi.dll", "cfgmgr32.dll", "powrprof.dll", "winmm.dll", "dsound.dll",
    "dinput8.dll", "d3d9.dll", "d3d11.dll", "dxgi.dll", "ddraw.dll", "opengl32.dll",
    "glu32.dll", "secur32.dll", "crypt32.dll", "bcrypt.dll", "ncrypt.dll",
    "bcryptprimitives.dll", "cryptbase.dll", "wintrust.dll", "wininet.dll",
    "winhttp.dll", "urlmon.dll", "iphlpapi.dll", "dnsapi.dll", "dbghelp.dll",
    "psapi.dll", "msvcrt.dll", "ucrtbase.dll", "comctl32.dll", "comdlg32.dll",
    "propsys.dll", "windows.storage.dll", "kernel.appcore.dll", "profapi.dll",
    "clbcatq.dll", "wtsapi32.dll", "userenv.dll", "netapi32.dll", "nsi.dll",
    "cryptsp.dll", "rsaenh.dll", "sspicli.dll", "devobj.dll", "win32u.dll",
}
_WINDOWS_PREFIX = (
    "api-ms-win-", "ext-ms-", "d3dx9_", "d3dcompiler_", "xinput1_", "xinput9_",
    "msvcr", "msvcp", "vcruntime", "mfc", "atl", "d3dx11_",
)

_WINDOWS_DIRS = ("/windows/", "\\windows\\")


def _basename(name_or_path: str) -> str:
    s = (name_or_path or "").strip().replace("\\", "/")
    return os.path.basename(s).lower()


def explain(name_or_path: str) -> tuple[Owner, str]:
    """Classify a module and return ``(owner, why)`` so a report can cite the rule."""
    if not name_or_path:
        return Owner.UNKNOWN, "no module name"
    raw = name_or_path.strip().replace("\\", "/").lower()
    base = _basename(name_or_path)

    for tok in _TOOLING_TOKENS:
        if tok in base:
            return Owner.TOOLING, f"diagnostic tooling (matched {tok!r})"
    for tok in _DEPENDENCY_TOKENS:
        if tok in base:
            return Owner.DEPENDENCY, f"example dependency (matched {tok!r})"
    if base.startswith("sampleengine"):
        return Owner.ENGINE, "example engine module"
    if base == "sampleconnection.dll":
        return Owner.APPLICATION, "example application module"
    if base in _THIRD_PARTY_EXACT or base.startswith(_THIRD_PARTY_PREFIX):
        return Owner.THIRD_PARTY, "third-party middleware"
    if any(d in raw for d in _WINDOWS_DIRS):
        return Owner.WINDOWS, "module under the Windows directory"
    if base in _WINDOWS_EXACT or base.startswith(_WINDOWS_PREFIX):
        return Owner.WINDOWS, "Windows OS / runtime module"
    if base.startswith("sampleapp"):
        return Owner.APPLICATION, "example application module"
    return Owner.UNKNOWN, "unrecognised module"


def classify(name_or_path: str) -> Owner:
    """Return just the :class:`Owner` for a module name or path."""
    return explain(name_or_path)[0]
