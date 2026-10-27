"""The speech model lives in a child process that exits when idle, so its ~850 MB goes back to Windows.

The tray process never imports numpy or ONNX Runtime and stays small. Pressing a hotkey starts the worker,
so the model loads while you're still talking.
"""
import logging
import multiprocessing
import sys


def rss_mb():
    """This process's resident memory in MB."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + \
                       [(n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                                       "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                                       "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        c = Counters()
        c.cb = ctypes.sizeof(c)
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        ctypes.WinDLL("psapi").GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return c.WorkingSetSize / 1e6
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1e6 if sys.platform == "darwin" else 1e3)


def serve(conn, idle_seconds):
    """Child process: load the model, transcribe float32 PCM bytes until idle, then exit."""
    import numpy as np
    from .transcriber import Transcriber
    try:
        t = Transcriber()
        t.warm_up()
    except Exception as e:
        conn.send(("error", f"{type(e).__name__}: {e}"))
        return
    conn.send(("ready", rss_mb()))
    while conn.poll(idle_seconds):
        try:
            pcm = conn.recv()
        except EOFError:
            return
        try:
            conn.send(("ok", t.transcribe(np.frombuffer(pcm, np.float32)), rss_mb()))
        except Exception as e:
            conn.send(("error", f"{type(e).__name__}: {e}"))


class ModelHost:
    """Runs on a single worker thread in the tray process."""

    def __init__(self, idle_seconds):
        self.idle_seconds = idle_seconds
        self.process = None
        self.conn = None
        self.ready = False
        self.worker_mb = None

    def start(self):
        if self.process is not None and self.process.is_alive():
            return
        ctx = multiprocessing.get_context("spawn")
        self.conn, child = ctx.Pipe()
        self.process = ctx.Process(target=serve, args=(child, self.idle_seconds), daemon=True, name="bensvoice-model")
        self.process.start()
        child.close()
        self.ready = False
        logging.info("Model worker started (pid %s)", self.process.pid)

    def wait_ready(self):
        self.start()
        if not self.ready:
            reply = self.conn.recv()  # first launch includes the model download
            if reply[0] == "error":
                self.process.join(5)
                raise RuntimeError(reply[1])
            self.ready, self.worker_mb = True, reply[1]

    def transcribe(self, pcm):
        for attempt in (1, 2):
            try:
                self.wait_ready()
                self.conn.send(pcm)
                reply = self.conn.recv()
                break
            except (EOFError, BrokenPipeError, ConnectionError, OSError):
                # The worker hit its idle timeout just as we sent: start a fresh one and retry once.
                self.process = None
                if attempt == 2:
                    raise
        if reply[0] == "error":
            raise RuntimeError(reply[1])
        self.worker_mb = reply[2]
        return reply[1]

    def alive(self):
        return self.process is not None and self.process.is_alive()
