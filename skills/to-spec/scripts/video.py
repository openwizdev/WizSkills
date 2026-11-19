"""Assemble a local narrated animatic or format its verified HTTPS link."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit


def issue_link(url):
    parts = urlsplit(url)
    if (parts.scheme != 'https' or not parts.hostname or parts.username is not None
            or parts.port == 0 or not re.fullmatch(r'https://[^\s\x00-\x1f\x7f<>()\\`]+', url)):
        raise ValueError('use a verified HTTPS playback URL without credentials')
    return f'[Watch the narrated spec]({url})'


def render(manifest, output):
    scenes = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(scenes, list) or not scenes or output.suffix.lower() != '.mp4':
        raise ValueError('provide a nonempty scene list and an MP4 output path')
    if output.exists():
        raise ValueError('output already exists')
    args = ['ffmpeg', '-nostdin', '-v', 'error', '-filter_complex_threads', '1']
    filters = []
    segments = []
    for index, scene in enumerate(scenes):
        if (not isinstance(scene, dict) or set(scene) != {'slide', 'narration'}
                or not all(isinstance(value, str) and value for value in scene.values())):
            raise ValueError('every scene needs a slide and a narration file')
        slide, audio = ((manifest.parent / scene[key]).resolve() for key in ('slide', 'narration'))
        if not slide.is_file() or not audio.is_file():
            raise ValueError('a scene input is missing')
        probe = subprocess.check_output([
            'ffprobe', '-v', 'error', '-protocol_whitelist', 'file', '-select_streams', 'a:0',
            '-show_entries', 'format=duration:stream=codec_type', '-of', 'json', str(audio),
        ], stderr=subprocess.DEVNULL)
        metadata = json.loads(probe)
        duration = float(metadata.get('format', {}).get('duration', 0))
        if not metadata.get('streams') or not math.isfinite(duration) or duration <= 0:
            raise ValueError('each narration needs a readable audio track of known duration')
        args.extend(['-protocol_whitelist', 'file', '-loop', '1', '-framerate', '24', '-i', str(slide),
                     '-protocol_whitelist', 'file', '-i', str(audio)])
        filters.extend([
            f'[{2 * index}:v]trim=duration={duration:f},'
            'scale=1280:720:force_original_aspect_ratio=decrease,'
            f'pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v{index}]',
            f'[{2 * index + 1}:a]aresample=48000,aformat=channel_layouts=stereo,'
            f'asetpts=PTS-STARTPTS,apad=whole_dur={duration:f},atrim=duration={duration:f}[a{index}]',
        ])
        segments.append(f'[v{index}][a{index}]')

    filters.append(f'{"".join(segments)}concat=n={len(scenes)}:v=1:a=1[video][audio]')
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        candidate = Path(directory) / 'spec.mp4'
        subprocess.run([*args, '-filter_complex', ';'.join(filters), '-map', '[video]', '-map', '[audio]',
                        '-c:v', 'libx264', '-preset', 'fast', '-threads', '2',
                        '-c:a', 'aac', '-movflags', '+faststart', str(candidate)],
                       check=True, stderr=subprocess.DEVNULL)
        os.link(candidate, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    assembly = commands.add_parser('render')
    assembly.add_argument('manifest', type=Path)
    assembly.add_argument('output', type=Path)
    link = commands.add_parser('link')
    link.add_argument('url')
    args = parser.parse_args()
    try:
        if args.command == 'link':
            print(issue_link(args.url))
        else:
            render(args.manifest, args.output)
            print('Narrated MP4 rendered.')
    except (ValueError, OSError, subprocess.SubprocessError):
        message = ('use a verified HTTPS playback URL without credentials' if args.command == 'link'
                   else 'render failed; check local slides, audio, ffmpeg and a fresh output path')
        print(f'video: {message}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
