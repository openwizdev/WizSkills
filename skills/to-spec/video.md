# Narrated spec video

Make an animatic from the spec, using a static slide with narration for each
beat. A few brief scenes should tell the story in order and leave the issue as
the detailed reference. Use a local approved recorder or text-to-speech tool
to make the audio files.

```json
[
  {"slide": "problem.png", "narration": "problem.wav"},
  {"slide": "experience.png", "narration": "experience.wav"},
  {"slide": "proof.png", "narration": "proof.wav"}
]
```

Paths are relative to this manifest. The local renderer uses FFmpeg and FFprobe
with H.264/AAC support. It keeps each slide up for its narration, in scene
order, and writes a playable MP4. The output path must be new. If the tools or
audio are unavailable, leave the preview incomplete. Check playback before
using the URL. Keep authorization tokens and private-media URLs out of a
public issue body.
