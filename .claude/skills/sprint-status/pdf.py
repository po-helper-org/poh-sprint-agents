"""HTML → PDF печатью headless Chrome/Chromium: без Python-зависимостей, плагин ставится копированием.

Браузер ищется так: аргумент → SPRINT_STATUS_CHROME / CHROME_PATH → Chromium из
PLAYWRIGHT_BROWSERS_PATH → установленные Chrome / Chromium / Edge / Brave.
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MAC_APPS = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
]
WIN_APPS = [
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
]
ON_PATH = ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome',
           'microsoft-edge', 'msedge', 'brave-browser']
PLAYWRIGHT_GLOBS = ['chromium-*/chrome-linux/chrome',
                    'chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium',
                    'chromium-*/chrome-win/chrome.exe']


class PdfError(Exception):
    pass


def find_browser(explicit=None):
    for cand in (explicit, os.environ.get('SPRINT_STATUS_CHROME'), os.environ.get('CHROME_PATH')):
        if cand:
            if Path(cand).is_file():
                return cand
            raise PdfError(f'браузер не найден по пути {cand}')
    pw = os.environ.get('PLAYWRIGHT_BROWSERS_PATH')
    if pw:
        for pattern in PLAYWRIGHT_GLOBS:
            hits = sorted(glob.glob(os.path.join(pw, pattern)), reverse=True)
            if hits:
                return hits[0]
    for path in (MAC_APPS if sys.platform == 'darwin' else WIN_APPS if os.name == 'nt' else []):
        if Path(path).is_file():
            return path
    for name in ON_PATH:
        found = shutil.which(name)
        if found:
            return found
    return None


def print_pdf(html_path, pdf_path, browser, timeout=90):
    """Печатает страницу в PDF. Пишет атомарно: при сбое прошлый файл остаётся."""
    html_path, pdf_path = Path(html_path).resolve(), Path(pdf_path).resolve()
    tmp = pdf_path.with_suffix('.pdf.tmp')
    with tempfile.TemporaryDirectory(prefix='sprint-status-chrome-') as profile:
        cmd = [browser, '--headless=new', '--disable-gpu', '--no-first-run',
               '--no-default-browser-check', '--disable-extensions', '--hide-scrollbars',
               f'--user-data-dir={profile}', '--no-pdf-header-footer',
               '--run-all-compositor-stages-before-draw', '--virtual-time-budget=2000',
               f'--print-to-pdf={tmp}', html_path.as_uri()]
        # под root (контейнеры, CI) Chrome без этого флага не стартует
        if hasattr(os, 'geteuid') and os.geteuid() == 0:
            cmd.insert(1, '--no-sandbox')
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise PdfError(f'браузер не уложился в {timeout} с') from exc
    if not tmp.is_file() or tmp.read_bytes()[:5] != b'%PDF-':
        tmp.unlink(missing_ok=True)
        tail = (proc.stderr or '').strip().splitlines()[-1:] or [f'код {proc.returncode}']
        raise PdfError(f'браузер не напечатал PDF ({tail[0]})')
    os.replace(tmp, pdf_path)
    return pdf_path
