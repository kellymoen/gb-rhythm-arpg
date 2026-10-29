"""Own audio output for the lab: an SDL queue fed from `pb.sound.ndarray` and used as the frame clock.

PyBoy's built-in SDL playback paces itself at 60 fps while the Game Boy makes 59.7275 frames of audio
per second, so its queue slowly fills and is then flushed (audible glitch every ~13 s) and the audio
lags the picture by a wandering 50-120 ms (docs/lab-audio-spike.md). Here the audio device is the
clock instead: the lab runs the next frame only when fewer than `target` frames of audio are queued,
so latency is fixed at about `target` frames plus the device's own buffer, and nothing drifts.
"""

import time

import sdl2

GB_FPS = 4194304 / 70224  # 59.7275


class AudioOut:
    """Stereo S8 queue at PyBoy's sample rate. `ok` is False when no output device could be opened."""

    def __init__(self, sample_rate: int = 48000, target_frames: float = 1.5, device_samples: int = 256):
        self.rate = sample_rate
        self.target = target_frames
        self.ok = False
        self.dev = 0
        self.driver = ""
        if sdl2.SDL_InitSubSystem(sdl2.SDL_INIT_AUDIO) < 0:
            return
        self._want = sdl2.SDL_AudioSpec(sample_rate, sdl2.AUDIO_S8, 2, device_samples)
        self._have = sdl2.SDL_AudioSpec(0, 0, 0, 0)
        self.dev = sdl2.SDL_OpenAudioDevice(None, 0, self._want, self._have, 0)
        if self.dev == 0:
            return
        self.ok = True
        self.driver = (sdl2.SDL_GetCurrentAudioDriver() or b"").decode()
        self.device_ms = 1000 * self._have.samples / self._have.freq
        sdl2.SDL_PauseAudioDevice(self.dev, 0)
        self.underruns = 0
        self._primed = False

    def queued_frames(self) -> float:
        """Audio waiting to be played, in Game Boy frames."""
        return sdl2.SDL_GetQueuedAudioSize(self.dev) / 2 / (self.rate / GB_FPS)

    def wait_for_room(self) -> None:
        """Block until the queue has drained below the target (this is the lab's frame pacing)."""
        while self.queued_frames() > self.target:
            time.sleep(0.0005)

    def push(self, samples) -> None:
        """Queue one frame of PyBoy's int8 stereo samples; counts an underrun if the queue ran dry."""
        if self._primed and self.queued_frames() < 0.05:
            self.underruns += 1
        self._primed = True
        data = samples.tobytes()
        sdl2.SDL_QueueAudio(self.dev, data, len(data))

    def close(self) -> None:
        if self.ok:
            sdl2.SDL_CloseAudioDevice(self.dev)
            self.ok = False
