"""Browser smoke test. Starts a local service, inspects desktop/mobile and tears down."""
import os
import socket
import subprocess
import time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent.parent

def main():
    env=os.environ.copy();env['DATABASE_PATH']='/tmp/compass/ui-smoke.db'
    proc=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','uvicorn','compass.app:create_app','--factory','--host','127.0.0.1','--port','8765'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                if httpx.get('http://127.0.0.1:8765/api/health').status_code==200:break
            except httpx.TransportError:pass
            time.sleep(.2)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1100},device_scale_factor=1)
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:8765');page.wait_for_selector('#status:has-text("mode"), #status:has-text("online")')
            page.screenshot(path=str(ROOT/'docs/desktop.png'),full_page=True)
            page.locator('[data-prompt]').first.click();page.wait_for_selector('.agent-answer, .error',timeout=60000)
            assert page.locator('.agent-answer').count()==1,page.locator('.error').all_text_contents()
            assert page.locator('.job-card').count()>0
            page.locator('.trace summary').click()
            page.screenshot(path=str(ROOT/'docs/agent-result.png'),full_page=True)
            with page.expect_download() as download:page.locator('.export').click()
            assert download.value.suggested_filename=='compass-shortlist.json'
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(ROOT/'docs/mobile.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),'Mobile overflows horizontally'
            page.locator('#clear-memory').click();page.wait_for_selector('.agent-answer',state='detached')
            assert not errors,errors
            browser.close()
            print('PASS: desktop, real form submit, result cards, trace, JSON export, 390px mobile, reset; no browser exceptions.')
    finally:
        proc.terminate();proc.wait(timeout=10)

if __name__=='__main__':main()
