"""Local Chromium onboarding regression checks.
Run: python tests/onboarding.py [--screenshots /tmp/illusion-onboarding]
Requires Playwright for Python and Chromium (CHROMIUM_PATH overrides the executable).
"""
import argparse
import json
import os
from pathlib import Path
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--screenshots', type=Path)
args = parser.parse_args()
if args.screenshots:
    args.screenshots.mkdir(parents=True, exist_ok=True)

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
Thread(target=server.serve_forever, daemon=True).start()
url = f'http://127.0.0.1:{server.server_port}'
errors = []

def shot(page, name):
    if args.screenshots:
        page.screenshot(path=str(args.screenshots / (name + '.png')))

def reopen(page):
    page.locator('.menu summary').first.click()
    page.locator('#introOpen').click()
    expect(page.locator('#welcome')).to_be_visible()

def project(page):
    # Use the actual save path; also verifies that saving cannot make replay destructive.
    with page.expect_download() as info:
        page.locator('#saveProject').evaluate('(button) => button.click()')
    return json.loads(Path(info.value.path()).read_text())

def drag(page, start, end):
    box = page.locator('#art').bounding_box()
    page.mouse.move(box['x'] + box['width'] * start[0], box['y'] + box['height'] * start[1])
    page.mouse.down()
    page.mouse.move(box['x'] + box['width'] * end[0], box['y'] + box['height'] * end[1], steps=12)
    page.mouse.up()

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'), args=['--no-sandbox'])
        for width, height in [(1366, 768), (390, 844), (800, 600), (320, 568)]:
            context = browser.new_context(viewport={'width': width, 'height': height}, accept_downloads=True)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url)
            expect(page.locator('#welcome')).to_be_visible()
            shot(page, f'welcome-{width}')
            page.locator('#welcomeSample').click()
            expect(page.locator('#welcome')).to_be_hidden()
            expect(page.locator('#play')).to_have_text('一時停止')
            expect(page.locator('.layer-row')).to_have_count(2)
            expect(page.locator('#quickCompare')).to_be_focused()
            # Repeated synthetic clicks must not replace the sample or toggle playback.
            page.locator('#welcomeSample').evaluate('(b) => { b.click(); b.click(); }')
            expect(page.locator('#play')).to_have_text('一時停止')
            expect(page.locator('.layer-row')).to_have_count(2)
            for _ in range(2):
                page.locator('#quickCompare').click()
                expect(page.locator('#comparison')).to_have_value('still')
                expect(page.locator('#quickCompare')).to_have_attribute('aria-pressed', 'true')
                page.locator('#quickCompare').click()
                expect(page.locator('#comparison')).to_have_value('illusion')
            shot(page, f'sample-{width}')
            for selector in ['#quickCompare', '#quickClose', '#play', '#art', '#comparison', '#guides']:
                box = page.locator(selector).bounding_box()
                assert box and box['x'] >= 0 and box['x'] + box['width'] <= width + 1, (width, selector, box)
                assert box['y'] >= 0 and box['y'] + box['height'] <= height + 1, (height, selector, box)
            # Contextual guidance must not resize the fitted canvas in mid-gesture.
            box = page.locator('#art').bounding_box()
            page.mouse.move(box['x'] + 10, box['y'] + 10)
            page.mouse.down()
            page.wait_for_timeout(50)
            assert page.locator('#art').bounding_box() == box, 'Canvas moved during pointer gesture'
            page.mouse.up()
            expect(page.locator('#quickCompare')).to_be_hidden()
            before = project(page)
            reopen(page)
            expect(page.locator('#welcomeSample')).to_be_hidden()
            page.keyboard.press('Escape')
            expect(page.locator('#welcome')).to_be_hidden()
            assert project(page) == before, 'Reopening/closing intro changed artwork'
            page.locator('#quickClose').click()
            expect(page.locator('#quickGuide')).to_be_hidden()
            page.reload()
            expect(page.locator('#welcome')).to_be_hidden()
            expect(page.locator('#quickGuide')).to_be_hidden()
            expect(page.locator('.layer-row')).to_have_count(1)
            context.close()
            print(f'PASS sample / compare / repeat / replay / reload / layout: {width}x{height}')

        context = browser.new_context(viewport={'width':1366,'height':768}, accept_downloads=True)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url)
        page.locator('#welcomeDismiss').click()
        expect(page.locator('[data-tool=pen]')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('#quickGuide')).to_be_visible()
        drag(page, (.2, .3), (.5, .5))
        drawn = project(page)
        reopen(page)
        expect(page.locator('#welcomeSample')).to_be_hidden()
        page.locator('#welcomeSample').evaluate('(b) => b.click()')
        page.locator('#welcomeDismiss').click()
        assert project(page) == drawn, 'Intro replaced saved drawing'
        page.locator('[data-tool=select]').click()
        drag(page, (.15, .25), (.55, .55))
        page.locator('#play').click()
        expect(page.locator('#play')).to_have_text('一時停止')
        assert len(project(page)['regions']) == 1
        # Undo/redo and project import still work after guided drawing.
        page.locator('#undo').click()
        expect(page.locator('#regionCount')).to_have_text('0')
        page.locator('#redo').click()
        expect(page.locator('#regionCount')).to_have_text('1')
        page.locator('#projectFile').set_input_files({'name':'drawing.json','mimeType':'application/json','buffer':json.dumps(drawn).encode()})
        expect(page.locator('#regionCount')).to_have_text('0')
        assert project(page)['layers'] == drawn['layers']
        reopen(page)
        expect(page.locator('#welcomeSample')).to_be_hidden()
        page.locator('#welcomeClose').click()
        print('PASS drawing / selection / playback / saved-art preservation / undo / redo / import')
        context.close()

        for blocked in [False, True]:
            context = browser.new_context()
            if blocked:
                context.add_init_script("Storage.prototype.getItem = () => {throw new Error('blocked')}; Storage.prototype.setItem = () => {throw new Error('blocked')};")
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url)
            page.locator('#welcomeClose').click()
            expect(page.locator('#quickGuide')).to_be_hidden()
            page.reload()
            if blocked:
                expect(page.locator('#welcome')).to_be_visible()
            else:
                expect(page.locator('#welcome')).to_be_hidden()
            reopen(page)
            page.locator('#welcomeSample').focus()
            page.keyboard.press('Enter')
            expect(page.locator('#play')).to_have_text('一時停止')
            context.close()
        print('PASS skip / keyboard / storage unavailable')
        assert not errors, errors
        browser.close()
finally:
    server.shutdown()
