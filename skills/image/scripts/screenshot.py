#!/usr/bin/env python3
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit


def positive_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('timeout must be positive and finite')
    return number


DESCRIPTION = (
    "Capture phone + desktop evidence through Cloudroom's browser-harness.\n"
    '\n'
    "Only Python's standard library and the existing browser-harness CLI are needed.\n"
    'For each width it opens and activates a fresh tab, sets a 1x CSS pixel scale and\n'
    'reduced motion, and loads the URL at 390 x 844 and 1440 x 900 (viewport sizes,\n'
    'not phone emulation). It waits for load, a success HTTP status, the visible\n'
    'ready selector, fonts, image decoding (lazy images too; empty placeholders are\n'
    'skipped) and two animation frames, then saves full-page phone.png and\n'
    'desktop.png and closes its tab, on success or failure. --timeout is per step,\n'
    'not a sleep. Any failure exits nonzero; partial files are not a completed pair.\n'
    'The manifest is written last: its presence marks a completed pair, not approval.\n'
    'It prints the manifest path, then `overflow: none` or each capture, first\n'
    'screens included, whose content is wider than its viewport.\n'
    'Use --fixed-at-bottom for a tall viewport plus a separate first-screen PNG.\n'
    'The taller viewport changes vh units and other viewport-relative layouts;\n'
    'compare the first-screen image before judging the full-page layout.\n'
)


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('url', help='HTTP(S) page you are authorised to view')
    parser.add_argument('--out', type=Path, required=True, help='new evidence directory')
    parser.add_argument('--ready-selector', required=True,
                        help='visible CSS selector marking the intended settled state')
    parser.add_argument('--timeout', type=positive_seconds, default=30,
                        help='seconds per readiness step (default: 30)')
    parser.add_argument('--fixed-at-bottom', action='store_true',
                        help='capture with a page-height viewport and keep first-screen PNGs; '
                             'changes vh and other viewport-relative layouts')
    args = parser.parse_args()
    url = urlsplit(args.url)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
        parser.error('url must be HTTP(S) without embedded credentials')
    if not args.ready_selector.strip():
        parser.error('ready selector must not be empty')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    config = repr({'url': args.url, 'out': str(out), 'ready': args.ready_selector,
                   'timeout': args.timeout, 'fixed_at_bottom': args.fixed_at_bottom})
    program = 'config = ' + config + '\n' + r"""
import base64
import json
import math
from pathlib import Path
import struct
import zlib


def require_non_uniform_png(data, filename):
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise RuntimeError(f'{filename} is not a valid PNG')
    off, idat, width, height, channels, saw_iend = 8, [], 0, 0, 0, False
    while off + 8 <= len(data):
        length, kind = struct.unpack('>I4s', data[off:off + 8])
        end = off + 12 + length
        if end > len(data):
            raise RuntimeError(f'{filename} is a truncated PNG')
        chunk = data[off + 8:off + 8 + length]
        if kind == b'IHDR':
            if length != 13:
                raise RuntimeError(f'{filename} has an invalid PNG header')
            width, height, depth, colour, _, _, interlace = struct.unpack('>IIBBBBB', chunk)
            channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(colour, 0)
            if width <= 0 or height <= 0 or depth != 8 or interlace or not channels:
                raise RuntimeError(f'{filename} has an unsupported PNG format')
        elif kind == b'IDAT':
            idat.append(chunk)
        elif kind == b'IEND':
            saw_iend = True
            break
        off = end
    if not channels or not idat or not saw_iend:
        raise RuntimeError(f'{filename} is not a complete PNG')
    try:
        raw = zlib.decompress(b''.join(idat))
    except zlib.error as error:
        raise RuntimeError(f'{filename} has corrupt PNG data: {error}') from error
    stride = width * channels
    if len(raw) != height * (stride + 1):
        raise RuntimeError(f'{filename} has invalid PNG scanline data')
    first_pixel = raw[1:1 + channels]
    solid = first_pixel * width
    zeros_rest = b'\x00' * (stride - channels)
    zeros_full = b'\x00' * stride
    avg_half = bytes((b - (b >> 1)) & 0xff for b in first_pixel)
    expected_row0 = {
        0: solid,
        1: first_pixel + zeros_rest,
        2: solid,
        3: first_pixel + avg_half * (width - 1),
        4: first_pixel + zeros_rest,
    }
    expected_later = {
        0: solid,
        1: first_pixel + zeros_rest,
        2: zeros_full,
        3: avg_half + zeros_rest,
        4: zeros_full,
    }
    for y in range(height):
        base = y * (stride + 1)
        expected = (expected_row0 if y == 0 else expected_later).get(raw[base])
        if expected is None:
            raise RuntimeError(f'{filename} has an unsupported PNG filter')
        if raw[base + 1:base + 1 + stride] != expected:
            return
    raise RuntimeError(f'{filename} is a single-colour PNG (blank first-screen capture)')


def evaluate(expression):
    response = cdp('Runtime.evaluate', expression=expression, awaitPromise=True,
                   returnByValue=True, _response_timeout=config['timeout'] + 5)
    if 'exceptionDetails' in response:
        raise RuntimeError('Page readiness failed: ' + str(response['exceptionDetails']))
    return response['result'].get('value')


def page_size(width):
    metrics = cdp('Page.getLayoutMetrics')['cssContentSize']
    if evaluate('innerWidth') != width:
        raise RuntimeError('Viewport width was not applied')
    return {'width': width, 'height': metrics['height'], 'contentWidth': metrics['width']}


def save_png(filename, width, height, beyond, *, reject_single_colour=False):
    png = cdp('Page.captureScreenshot', format='png', captureBeyondViewport=beyond,
              clip={'x': 0, 'y': 0, 'width': width, 'height': height, 'scale': 1})
    raw_png = base64.b64decode(png['data'], validate=True)
    if reject_single_colour:
        require_non_uniform_png(raw_png, filename)
    Path(config['out'], filename).write_bytes(raw_png)


captures = []
for name, width, height in [('phone', 390, 844), ('desktop', 1440, 900)]:
    # Each viewport gets a new document, even for fragment-only navigation.
    # A blank new_tab always creates a target; never reuse a user's blank tab.
    tab = new_tab()
    try:
        # Background pages can pause requestAnimationFrame and never reach readiness.
        activate_tab(tab)
        cdp('Emulation.setEmulatedMedia', features=[{'name': 'prefers-reduced-motion', 'value': 'reduce'}])
        cdp('Emulation.setDeviceMetricsOverride', width=width, height=height,
            deviceScaleFactor=1, mobile=False)
        response = cdp('Page.navigate', url=config['url'])
        if response.get('errorText'):
            raise RuntimeError('Navigation failed: ' + response['errorText'])
        if not wait_for_load(timeout=config['timeout']):
            raise RuntimeError('Page load readiness timed out')
        status = evaluate('performance.getEntriesByType("navigation")[0]?.responseStatus')
        if not isinstance(status, (int, float)) or not 200 <= status < 400:
            raise RuntimeError('Navigation HTTP status: ' + str(status))
        if not wait_for_element(config['ready'], timeout=config['timeout'], visible=True):
            raise RuntimeError('Page ready selector was not visible: ' + config['ready'])
        evaluate('''(async () => {
            await Promise.race([
                (async () => {
                    await document.fonts.ready;
                    await Promise.all([...document.images].map(async image => {
                        if (!image.currentSrc && !image.getAttribute('src') && !image.getAttribute('srcset')
                            && !image.closest('picture')?.querySelector('source[srcset]')) return;
                        // Load lazy images below the fold for the full-page capture.
                        image.loading = 'eager';
                        await image.decode();
                    }));
                    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                })(),
                new Promise((_, reject) => setTimeout(() => reject(new Error('Font/image readiness timed out')), ''' + str(config['timeout'] * 1000) + '''))
            ]);
            return true;
        })()''')
        page = page_size(width)
        first_screen = None
        if config['fixed_at_bottom']:
            first_filename = name + '-first-screen.png'
            save_png(first_filename, width, height, True, reject_single_colour=True)
            first_screen = {'file': first_filename,
                            'viewport': {'width': width, 'height': height}, 'page': page}
            # Measure at the normal viewport, then resize once. Repeatedly
            # expanding vh-based pages could grow forever; this is a distinct
            # tall-viewport view, not a claim that such layouts stay unchanged.
            height = math.ceil(max(height, page['height']))
            cdp('Emulation.setDeviceMetricsOverride', width=width, height=height,
                deviceScaleFactor=1, mobile=False)
            evaluate('''new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))''')
            page = page_size(width)
        filename = name + '.png'
        save_png(filename, width, height if first_screen else max(height, page['height']),
                 not config['fixed_at_bottom'])
        capture = {'name': name, 'file': filename,
                   'viewport': {'width': width, 'height': height}, 'page': page}
        if first_screen:
            capture['firstScreen'] = first_screen
        captures.append(capture)
    finally:
        close_tab(tab)
manifest = {'url': config['url'], 'readySelector': config['ready'],
            'deviceScaleFactor': 1, 'reducedMotion': True, 'captures': captures}
Path(config['out'], 'capture.json').write_text(json.dumps(manifest, indent=2) + '\n')
"""
    subprocess.run(['browser-harness'], input=program, text=True, check=True)
    print(out / 'capture.json')
    wide = []
    for capture in json.loads((out / 'capture.json').read_text())['captures']:
        views = [(capture['name'], capture)]
        if 'firstScreen' in capture:
            views.append((capture['name'] + ' first screen', capture['firstScreen']))
        wide += [f"{label} {view['page']['contentWidth']:g} > {view['viewport']['width']}"
                 for label, view in views
                 if view['page']['contentWidth'] > view['viewport']['width']]
    print('overflow: ' + (', '.join(wide) or 'none'))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'screenshot: {error}', file=sys.stderr)
        sys.exit(1)
