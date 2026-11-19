import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/video.py'


def run(*args):
    return subprocess.run([sys.executable, '-I', SCRIPT, *map(str, args)],
                          capture_output=True, text=True)


class SpecVideo(unittest.TestCase):
    def test_link_is_ready_to_insert_in_spec(self):
        result = run('link', 'https://example.com/videos/synthetic.mp4?lang=en')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout,
                         '[Watch the narrated spec](https://example.com/videos/synthetic.mp4?lang=en)\n')

    def test_link_refuses_unsafe_or_ambiguous_destinations(self):
        for url in ['file:///tmp/video.mp4', 'https://user:secret@example.com/video.mp4',
                    'https://example.com/clip)\n[extra](https://example.org',
                    'https://example.com:bad/video.mp4', 'https:///video.mp4']:
            with self.subTest(url=url):
                result = run('link', url)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                         'local media integration requires ffmpeg and ffprobe')
    def test_render_keeps_both_narrated_scenes_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, rgb, sample in [('one', b'\xff\x00\x00', b'\x00\x12'),
                                      ('two', b'\x00\x00\xff', b'\x00\xe8')]:
                (root / f'{name}.ppm').write_bytes(b'P6\n16 16\n255\n' + rgb * 256)
                with wave.open(str(root / f'{name}.wav'), 'wb') as audio:
                    audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                    audio.writeframes(sample * 8000)
            manifest = root / 'scenes.json'
            manifest.write_text(json.dumps([
                {'slide': f'{name}.ppm', 'narration': f'{name}.wav'}
                for name in ('one', 'two')
            ]))
            video = root / 'spec.mp4'
            result = run('render', manifest, video)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(video.is_file(), 'render did not produce a narrated preview')
            metadata = json.loads(subprocess.check_output([
                'ffprobe', '-v', 'error', '-show_entries',
                'format=duration:stream=codec_type', '-of', 'json', video]))
            self.assertEqual({stream['codec_type'] for stream in metadata['streams']},
                             {'video', 'audio'})
            self.assertAlmostEqual(float(metadata['format']['duration']), 2, delta=0.12)
            for second, channel in [('0.5', 0), ('1.5', 2)]:
                pixel = subprocess.check_output([
                    'ffmpeg', '-v', 'error', '-ss', second, '-i', video, '-frames:v', '1',
                    '-vf', 'crop=2:2:640:360,scale=1:1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
                self.assertGreater(pixel[channel], 200)
                self.assertLess(pixel[2 - channel], 30)


if __name__ == '__main__':
    unittest.main()
