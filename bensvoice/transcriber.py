"""Local speech to text with NVIDIA Parakeet TDT, run on the CPU through ONNX Runtime (via onnx-asr)."""
import wave

import numpy as np

from .config import SAMPLE_RATE, load_config

# onnx-asr handles the TDT decoding; we cut long recordings into windows ourselves to keep memory flat.
WINDOW = 20 * SAMPLE_RATE


class Transcriber:
    def __init__(self):
        import onnx_asr  # slow import, keep it off the startup path
        import onnxruntime as ort

        config = load_config()
        quantization = config.get("quantization", "int8") or None
        so = ort.SessionOptions()
        so.log_severity_level = 3
        # Measured on Parakeet int8: no prepacking saves ~200 MB for a few ms per run, and without spinning
        # the threads go idle as soon as a transcription ends instead of burning CPU.
        so.add_session_config_entry("session.disable_prepacking", "1")
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        so.add_session_config_entry("session.inter_op.allow_spinning", "0")
        so.enable_cpu_mem_arena = False
        self.model = onnx_asr.load_model(config.get("asrModel", "nemo-parakeet-tdt-0.6b-v2"), quantization=quantization,
                                         sess_options=so, providers=["CPUExecutionProvider"])

    def warm_up(self):
        self.transcribe(np.zeros(SAMPLE_RATE, np.float32))

    def transcribe(self, samples):
        if len(samples) < SAMPLE_RATE // 4:
            return ""
        parts = []
        start = 0
        while start < len(samples):
            end = _chunk_end(samples, start)
            parts.append(self.model.recognize(samples[start:end], sample_rate=SAMPLE_RATE).strip())
            start = end
        return " ".join(p for p in parts if p)


def _chunk_end(s, start):
    """Cut long audio at the quietest 100 ms in the last 3 s of each window."""
    hard_end = start + WINDOW
    if hard_end >= len(s):
        return len(s)
    step = SAMPLE_RATE // 10
    best, best_energy = hard_end, float("inf")
    for i in range(hard_end - 3 * SAMPLE_RATE, hard_end - step + 1, step):
        e = float(np.dot(s[i:i + step], s[i:i + step]))
        if e < best_energy:
            best, best_energy = i + step // 2, e
    return best


def read_wav(path):
    """16-bit PCM wav to 16 kHz mono float32 (used by --transcribe and --selftest)."""
    with wave.open(str(path)) as w:
        rate, channels = w.getframerate(), w.getnchannels()
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    a = a.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        n = int(len(a) * SAMPLE_RATE / rate)
        a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)
    return a
