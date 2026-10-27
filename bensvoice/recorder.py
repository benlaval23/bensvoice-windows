import threading

import sounddevice as sd

from .config import SAMPLE_RATE


class Recorder:
    """Captures the default mic as 16 kHz mono float32 PCM bytes. The stream only runs while recording.

    Raw bytes rather than numpy arrays, so the tray process never loads numpy.
    """

    def __init__(self):
        self._stream = None
        self._chunks = []
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            self._chunks = []
        self._stream = sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=self._callback)
        self._stream.start()

    def _callback(self, data, frames, time, status):
        with self._lock:
            self._chunks.append(bytes(data))

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            chunks, self._chunks = self._chunks, []
        return b"".join(chunks)
