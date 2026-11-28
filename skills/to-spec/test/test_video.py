from array import array
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'scripts/animatic.mjs'
STORYBOARD = HERE / 'synthetic/storyboard.json'


def run(*args, cwd=None, env=None):
    return subprocess.run(['node', str(SCRIPT), *map(str, args)], capture_output=True, text=True, cwd=cwd, env=env)


def can_render():
    if not (shutil.which('ffmpeg') and shutil.which('ffprobe')):
        return False
    if not (os.environ.get('OPENWIZ_CHROMIUM') or shutil.which('chromium')):
        return False
    homes = [Path.cwd(), Path(os.environ.get('ANIMATIC_HOME', Path.home() / '.cache/animatic'))]
    return any((home / 'node_modules/playwright-core/package.json').is_file() for home in homes)


def other_filesystem(than):
    for root in ['/dev/shm', os.environ.get('XDG_RUNTIME_DIR')]:
        if root and os.path.isdir(root) and os.access(root, os.W_OK) and os.stat(root).st_dev != os.stat(than).st_dev:
            return Path(root)
    return None


VOICE = '''
import json, math, os, sys, wave
text = sys.stdin.read()
if len(sys.argv) > 2 and sys.argv[2] != text:
    sys.exit('narration argument differs from stdin')
mode = os.environ.get('VOICE_MODE', 'tone') if text == os.environ.get('VOICE_LINE') else 'tone'
if mode == 'nothing':
    sys.exit(0)
if mode == 'symlink':
    os.symlink(os.environ['VOICE_SOURCE'], sys.argv[1] + '.wav')
    sys.exit(0)
suffix = '.bin' if mode == 'wrong-extension' else '.wav'
w = wave.open(sys.argv[1] + suffix, 'wb')
w.setparams((1, 2, 16000, 0, 'NONE', ''))
amp = 0 if mode.startswith('silent') else int(os.environ.get('VOICE_AMP', '8000'))
tones = json.loads(os.environ.get('VOICE_TONES', '{}'))
hz, sample_count = tones.get(text, (320, 8000))
w.writeframes(b''.join(int(amp * math.sin(math.tau * hz * i / 16000)).to_bytes(2, 'little', signed=True)
                       for i in range(sample_count)))
w.close()
sys.exit(3 if mode.endswith('-exit-3') else 0)
'''


class SpecVideo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.moments = json.loads(STORYBOARD.read_text())

    def write(self, moments):
        path = self.tmp / 'storyboard.json'
        path.write_text(json.dumps(moments))
        return path

    def voice_command(self, *, argument=False):
        helper = self.tmp / 'voice.py'
        helper.write_text(VOICE)
        return f'python3 -I "{helper}" {{out}}' + (' {text}' if argument else '')

    def test_link_is_ready_to_insert_in_spec(self):
        result = run('link', 'https://example.com/videos/synthetic.mp4?lang=en')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout,
                         '[Watch the narrated spec](https://example.com/videos/synthetic.mp4?lang=en)\n')

    def test_a_nonlocal_voice_needs_authorization_and_public_safe_input(self):
        video = (HERE.parent / 'video.md').read_text()
        lower = video.lower()
        self.assertIn('default', lower)
        self.assertIn('--tts-command', video)
        self.assertIn('authorized provider', lower)
        self.assertIn('public-safe', lower)
        self.assertIn('nonlocal', lower.replace('non-local', 'nonlocal'))

    def test_link_refuses_unsafe_or_ambiguous_destinations(self):
        for url in ['file:///tmp/video.mp4', 'https://user:secret@example.com/video.mp4',
                    'https://example.com/clip)\n[extra](https://example.org',
                    'https://example.com:bad/video.mp4', 'https://example.com:0/video.mp4',
                    'https://example.com:000/video.mp4', 'https:///video.mp4']:
            with self.subTest(url=url):
                result = run('link', url)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr,
                                 'animatic: use a verified HTTPS playback URL without credentials\n')

    def test_the_synthetic_grill_storyboard_passes_in_build_order(self):
        result = run('check', STORYBOARD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0],
                         'storyboard ok: 5 moments; steps 1-3; user 2, codebase 2')

    def test_a_graph_a_bench_or_build_order_broken_is_refused_before_rendering(self):
        def change(fn):
            moments = copy.deepcopy(self.moments)
            fn(moments)
            return moments

        cases = {
            'a graph frame': lambda m: m[1]['frame'].update(type='diagram'),
            'an own image': lambda m: m[2].update(image='graph.png'),
            'an own page': lambda m: m[2].update(html='graph.html'),
            'graph in a line': lambda m: m[3].update(say='Here is the ticket graph.'),
            'bench in a point': lambda m: m[2]['frame']['points'].append('Benchmarks go up'),
            'out of build order': lambda m: m[4]['frame'].update(step=1),
            'not starting at step 1': lambda m: [x['frame'].update(step=x['frame']['step'] + 1) for x in m[1:]],
            'a skipped step': lambda m: m[4]['frame'].update(step=4),
            'no codebase change': lambda m: [x['frame'].update(type='user', points=['A change'])
                                             for x in m if x['frame']['type'] == 'codebase'],
            'no user change': lambda m: [x['frame'].update(type='codebase', paths=['a/b.py'])
                                         for x in m if x['frame']['type'] == 'user'],
            'title not first': lambda m: m.insert(2, m.pop(0)),
            'an extra key': lambda m: m[1]['frame'].update(ticket='#9101'),
            'no line': lambda m: m[1].pop('say'),
            'over the target': lambda m: m[1].update(say=' '.join(['word'] * 400)),
        }
        for name, fn in cases.items():
            with self.subTest(name):
                path = self.write(change(fn))
                result = run('check', path)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertTrue(result.stderr.startswith('animatic: '), result.stderr)
                built = run('build', path, '-o', self.tmp / 'spec.mp4')
                self.assertEqual(built.returncode, 1)
                self.assertFalse((self.tmp / 'build').exists(), 'build rendered a refused storyboard')
                self.assertFalse((self.tmp / 'spec.mp4').exists())

    def test_malformed_frames_are_refused_with_a_moment_number(self):
        for fields, reason in [
            ({'type': 'constructor'}, 'a frame is title, user or codebase'),
            ({'type': ['codebase']}, 'a frame is title, user or codebase'),
            ({'paths': 123}, 'paths is a list of 1 to 4 lines'),
            ({'points': {}}, 'points is a list of 1 to 4 lines'),
        ]:
            with self.subTest(fields=fields):
                moments = copy.deepcopy(self.moments)
                moments[3]['frame'].update(fields)
                result = run('check', self.write(moments))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr, f'animatic: moment 4: {reason}\n')

    def test_benches_are_refused_in_narration_and_frame_text(self):
        for where in ['narration', 'frame']:
            with self.subTest(where=where):
                moments = copy.deepcopy(self.moments)
                if where == 'narration':
                    moments[2]['say'] = 'Look at the benches.'
                else:
                    moments[2]['frame']['points'] = ['Look at the benches.']
                result = run('check', self.write(moments))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr,
                                 'animatic: moment 3: no bench and no graph in the video; the graph stays on the spec\n')

    @unittest.skipUnless(can_render(), 'rendering needs ffmpeg, ffprobe, Chromium and playwright-core')
    def test_build_renders_each_frame_with_its_voice_in_order(self):
        signatures = [(440, 9600), (550, 11200), (660, 12800), (770, 14400), (880, 16000)]
        for i, moment in enumerate(self.moments):
            moment['frame']['headline'] = '\u2003' * (2 * i) + '██'
        tones = {m['say']: signature for m, signature in zip(self.moments, signatures)}
        env = dict(os.environ, VOICE_TONES=json.dumps(tones))
        out = self.tmp / 'spec.mp4'
        result = run('build', self.write(self.moments), '-o', out, '--tts-command', self.voice_command(),
                     cwd=Path.cwd(), env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('no warnings', result.stdout)
        lengths = [1.0, 1.1, 1.2, 1.3, 1.4]
        meta = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,codec_name,r_frame_rate',
            '-of', 'json', str(out)]))
        self.assertEqual(sorted(s['codec_type'] for s in meta['streams']), ['audio', 'video'])
        self.assertAlmostEqual(float(meta['format']['duration']), sum(lengths), delta=0.25)
        frames = sorted((self.tmp / 'build').glob('frame-*.png'))
        self.assertEqual(len(frames), len(self.moments))
        self.assertTrue((self.tmp / 'build/sheet.png').is_file())

        def tiny(args):
            return subprocess.check_output(['ffmpeg', '-v', 'error', *args, '-frames:v', '1',
                                            '-vf', 'scale=80:45', '-pix_fmt', 'gray', '-f', 'rawvideo', '-'])

        pictures = [tiny(['-i', str(f)]) for f in frames]
        start = 0.0
        for i, ((hz, _), length) in enumerate(zip(signatures, lengths)):
            shot = tiny(['-ss', f'{start + length / 2:.2f}', '-i', str(out)])
            marker_slots = [
                sum(shot[y * 80 + x] > 230 for y in range(45) for x in range(6 + 8 * slot, 12 + 8 * slot))
                for slot in range(len(signatures))
            ]
            self.assertEqual(marker_slots.index(max(marker_slots)), i,
                             f'moment {i + 1} shows the wrong storyboard marker: {marker_slots}')
            nearest = min(range(len(pictures)),
                          key=lambda k: sum(abs(a - b) for a, b in zip(shot, pictures[k])))
            self.assertEqual(nearest, i, f'moment {i + 1} shows frame {nearest + 1}')
            pcm = subprocess.check_output([
                'ffmpeg', '-v', 'error', '-ss', f'{start + 0.1:.2f}', '-i', str(out),
                '-t', '0.25', '-map', '0:a:0', '-ac', '1', '-ar', '16000', '-f', 's16le', '-'])
            samples = array('h', pcm)
            if sys.byteorder != 'little':
                samples.byteswap()
            self.assertEqual(len(samples), 4000)
            rising_edges = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
            self.assertAlmostEqual(rising_edges * 4, hz, delta=8, msg=f'moment {i + 1} has the wrong voice')
            start += length

    @unittest.skipUnless(can_render(), 'rendering needs ffmpeg, ffprobe, Chromium and playwright-core')
    def test_narration_is_normalized_to_minus_16_lufs_however_loud_the_voice(self):
        for name, amp in (('quiet', 250), ('loud', 30000)):
            with self.subTest(voice=name):
                out = self.tmp / f'{name}.mp4'
                env = dict(os.environ, VOICE_AMP=str(amp))
                result = run('build', self.write(self.moments), '-o', out, '--tts-command', self.voice_command(),
                             cwd=Path.cwd(), env=env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                measured = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(out), '-af',
                                           'loudnorm=I=-16:TP=-1.5:print_format=json', '-vn', '-f', 'null', '-'],
                                          capture_output=True, text=True).stderr
                loud = json.loads(measured[measured.rindex('{'):measured.rindex('}') + 1])
                self.assertGreaterEqual(float(loud['input_i']), -17.5, f'the {name} voice stays quiet: {loud["input_i"]} LUFS')
                self.assertLessEqual(float(loud['input_i']), -14.5, f'the {name} voice is too loud: {loud["input_i"]} LUFS')
                self.assertLessEqual(float(loud['input_tp']), -1.0, f'the {name} voice clips: {loud["input_tp"]} dBTP')
                self.assertIn('LUFS', result.stdout)

    @unittest.skipUnless(can_render(), 'rendering needs ffmpeg, ffprobe, Chromium and playwright-core')
    def test_rebuilding_a_shorter_storyboard_uses_only_its_own_frames_in_the_sheet(self):
        extra = copy.deepcopy(self.moments[-1])
        extra['frame']['headline'] = 'A frame from the longer storyboard'
        tone = self.voice_command()
        for count, moments in [(6, [*self.moments, extra]), (5, self.moments)]:
            result = run('build', self.write(moments), '-o', self.tmp / f'spec-{count}.mp4',
                         '--tts-command', tone, cwd=Path.cwd())
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        last_tile = subprocess.check_output([
            'ffmpeg', '-v', 'error', '-i', str(self.tmp / 'build/sheet.png'),
            '-vf', 'crop=iw/3:ih/2:iw*2/3:ih/2,scale=1:1:flags=bilinear', '-pix_fmt', 'rgb24',
            '-frames:v', '1', '-f', 'rawvideo', '-'])
        self.assertEqual(last_tile, bytes(3), 'the sixth tile still shows an earlier frame')

    @unittest.skipUnless(can_render(), 'rendering needs ffmpeg, ffprobe, Chromium and playwright-core')
    def test_custom_voice_receives_literal_narration_as_an_argument_and_stdin(self):
        self.moments[2]['say'] = "Costs $& in 'fees' and prints {out} and {text}."
        result = run('build', self.write(self.moments[:3]), '-o', self.tmp / 'spec.mp4',
                     '--tts-command', self.voice_command(argument=True), cwd=Path.cwd())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(can_render(), 'rendering needs ffmpeg, ffprobe, Chromium and playwright-core')
    def test_custom_voice_output_must_be_a_supported_regular_file(self):
        tone = self.voice_command()
        source = self.tmp / 'source.wav'
        subprocess.run(['python3', '-I', str(self.tmp / 'voice.py'), str(source.with_suffix(''))],
                       input='A local tone.', text=True, check=True)
        out = self.tmp / 'spec.mp4'
        for mode in ['wrong-extension', 'symlink']:
            with self.subTest(mode=mode):
                env = dict(os.environ, VOICE_MODE=mode, VOICE_LINE=self.moments[2]['say'], VOICE_SOURCE=str(source))
                result = run('build', self.write(self.moments[:3]), '-o', out.with_stem(mode),
                             '--tts-command', tone, cwd=Path.cwd(), env=env)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('animatic: moment 3: the voice wrote no supported regular audio file', result.stderr)
                self.assertFalse(out.with_stem(mode).exists())
                self.assertTrue(source.is_file())
                self.assertEqual(list((self.tmp / 'build').glob('line-03.src.*')), [])

    @unittest.skipUnless(can_render(), 'rendering needs ffmpeg, ffprobe, Chromium and playwright-core')
    def test_media_decoders_receive_a_file_only_protocol_allowlist(self):
        install = self.tmp / 'bin'
        install.mkdir()
        decoder = '''#!/usr/bin/env python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ['DECODER_CALLS'], 'a') as log:
    print(json.dumps([name, *sys.argv[1:]]), file=log)
os.execv(os.environ[f'REAL_{name.upper()}'], sys.argv)
'''
        calls = self.tmp / 'calls.jsonl'
        env = dict(os.environ, PATH=f'{install}{os.pathsep}{os.environ["PATH"]}', DECODER_CALLS=str(calls))
        for name in ['ffmpeg', 'ffprobe']:
            env[f'REAL_{name.upper()}'] = shutil.which(name)
            wrapper = install / name
            wrapper.write_text(decoder)
            wrapper.chmod(0o755)
        result = run('build', self.write(self.moments[:3]), '-o', self.tmp / 'spec.mp4',
                     '--tts-command', self.voice_command(), cwd=Path.cwd(), env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        counts = {'ffmpeg': 0, 'ffprobe': 0}
        for line in calls.read_text().splitlines():
            name, *args = json.loads(line)
            inputs = [len(args) - 1] if name == 'ffprobe' else [i + 1 for i, arg in enumerate(args) if arg == '-i']
            for i in inputs:
                if args[i].endswith('.wav'):
                    counts[name] += 1
                    with self.subTest(decoder=name, source=Path(args[i]).name):
                        boundary = i if name == 'ffprobe' else i - 1
                        self.assertEqual(args[boundary - 2:boundary], ['-protocol_whitelist', 'file'])
        self.assertEqual(counts, {'ffmpeg': 9, 'ffprobe': 3})

    @unittest.skipUnless(can_render(), 'rendering needs ffmpeg, ffprobe, Chromium and playwright-core')
    def test_a_failed_or_silent_voice_for_one_moment_fails_the_build_and_names_it(self):
        helper = self.tmp / 'voice.py'
        helper.write_text(VOICE)
        cases = {
            'fails, leaving a silent take': ('silent-exit-3', False),
            'fails, leaving an audible take': ('tone-exit-3', False),
            'exits 0 with a silent take': ('silent', False),
            'writes nothing beside a stale take': ('nothing', True),
        }
        for name, (mode, stale) in cases.items():
            with self.subTest(name):
                work = Path(tempfile.mkdtemp(dir=self.tmp))
                shutil.copy(STORYBOARD, work / 'storyboard.json')
                if stale:
                    (work / 'build').mkdir()
                    env = dict(os.environ, VOICE_MODE='tone', VOICE_LINE='')
                    subprocess.run(['python3', '-I', str(helper), str(work / 'build/line-03.src')],
                                   input='stale', text=True, env=env, check=True)
                out_dir = work / 'deliverable'
                out_dir.mkdir()
                env = dict(os.environ, VOICE_MODE=mode, VOICE_LINE=self.moments[2]['say'])
                result = subprocess.run(
                    ['node', str(SCRIPT), 'build', str(work / 'storyboard.json'), '-o', str(out_dir / 'spec.mp4'),
                     '--tts-command', f'python3 -I {helper} {{out}}'],
                    capture_output=True, text=True, env=env, cwd=Path.cwd())
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(result.stdout, '')
                lines = result.stderr.splitlines()
                self.assertEqual(len(lines), 1, result.stderr)
                self.assertTrue(lines[0].startswith('animatic: moment 3: '), result.stderr)
                if mode.endswith('-exit-3'):
                    self.assertIn('(exit 3)', lines[0])
                self.assertEqual(list(out_dir.iterdir()), [], 'a refused build left a file at the output')

    @unittest.skipUnless(can_render(), 'rendering needs ffmpeg, ffprobe, Chromium and playwright-core')
    def test_build_exports_to_an_output_on_another_filesystem(self):
        far = other_filesystem(self.tmp)
        if far is None:
            self.skipTest('no second writable filesystem (such as /dev/shm) here')
        out_dir = Path(tempfile.mkdtemp(dir=far))
        self.addCleanup(shutil.rmtree, out_dir)
        shutil.copy(STORYBOARD, self.tmp / 'storyboard.json')
        helper = self.tmp / 'voice.py'
        helper.write_text(VOICE)
        env = dict(os.environ, VOICE_MODE='tone', VOICE_LINE='')
        result = subprocess.run(
            ['node', str(SCRIPT), 'build', str(self.tmp / 'storyboard.json'), '-o', str(out_dir / 'spec.mp4'),
             '--tts-command', f'python3 -I {helper} {{out}}'],
            capture_output=True, text=True, env=env, cwd=Path.cwd())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([p.name for p in out_dir.iterdir()], ['spec.mp4'])
        self.assertEqual([p.name for p in (self.tmp / 'build').iterdir() if 'partial' in p.name], [])
        meta = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'json', str(out_dir / 'spec.mp4')]))
        self.assertEqual(sorted(s['codec_type'] for s in meta['streams']), ['audio', 'video'])

    @unittest.skipUnless(can_render(), 'rendering needs ffmpeg, ffprobe, Chromium and playwright-core')
    def test_build_never_touches_an_existing_file_beside_the_output(self):
        shutil.copy(STORYBOARD, self.tmp / 'storyboard.json')
        helper = self.tmp / 'voice.py'
        helper.write_text(VOICE)
        out_dir = self.tmp / 'deliverable'
        out_dir.mkdir()
        env = dict(os.environ, VOICE_MODE='tone', VOICE_LINE='')
        launch = ('printf "keep me" > "$1/.spec.$$.partial.mp4"; '
                  'exec node "$2" build "$3" -o "$1/spec.mp4" --tts-command "python3 -I $4 {out}"')
        result = subprocess.run(['sh', '-c', launch, 'sh', str(out_dir), str(SCRIPT),
                                 str(self.tmp / 'storyboard.json'), str(helper)],
                                capture_output=True, text=True, env=env, cwd=Path.cwd())
        planted = [p for p in out_dir.iterdir() if p.name.endswith('.partial.mp4')]
        self.assertEqual(len(planted), 1, f'the existing file is gone: {result.stderr}')
        self.assertEqual(planted[0].read_bytes(), b'keep me')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sorted(p.name for p in out_dir.iterdir()), sorted([planted[0].name, 'spec.mp4']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
