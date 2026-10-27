import logging
import os
import sys
import time
import traceback

from .config import APP_DIR


def main():
    # The packaged app has no console: give libraries that print (download progress bars) somewhere to write.
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    APP_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=APP_DIR / "bensvoice.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    args = sys.argv[1:]

    # CLI test mode: BensVoice.exe --transcribe file.wav [out.txt]
    # Runs through the same model process as the app, and reports memory and the idle unload.
    if len(args) >= 2 and args[0] == "--transcribe":
        return transcribe_file(args[1], args[2] if len(args) > 2 else None)

    # Used by CI: BensVoice.exe --selftest out.txt
    if args[:1] == ["--selftest"]:
        return selftest(args[1] if len(args) > 1 else None)

    from . import winapi
    if not winapi.single_instance():
        return 0
    from .app import App
    logging.info("Starting")
    App().run()
    return 0


def transcribe_file(wav, path):
    from .transcriber import read_wav
    from .worker import ModelHost, rss_mb
    idle = 3
    try:
        host = ModelHost(idle_seconds=idle)
        t0 = time.time()
        host.wait_ready()
        t1 = time.time()
        audio = read_wav(wav)
        text = host.transcribe(audio.tobytes())
        t2 = time.time()
        lines = [text, f"load {t1 - t0:.2f}s, transcribe {t2 - t1:.2f}s, audio {len(audio) / 16000:.1f}s",
                 f"app process {rss_mb():.0f} MB, model process {host.worker_mb:.0f} MB"]
        time.sleep(idle + 2)
        lines.append(f"model process after {idle}s idle: {'STILL RUNNING' if host.alive() else 'exited'}")
        t3 = time.time()
        again = host.transcribe(audio.tobytes())
        lines.append(f"reload + transcribe {time.time() - t3:.2f}s: {again}")
    except Exception:
        output(traceback.format_exc(), path)
        return 1
    output("\n".join(lines) + "\n", path)
    return 0 if "exited" in lines[3] and again == text else 1


def output(text, path):
    # The packaged app has no console, so tests write to a file instead.
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    elif sys.stdout:
        print(text, end="")


def selftest(path):
    from . import winapi
    from .app import icon_image
    from .composer import find_claude
    lines, ok = [], True
    try:
        winapi.set_clipboard_text("before", transient=False)
        saved = winapi.save_clipboard()
        winapi.set_clipboard_text("héllo 👋")
        assert winapi.get_clipboard_text() == "héllo 👋", "clipboard text roundtrip"
        winapi.restore_clipboard(saved)
        assert winapi.get_clipboard_text() == "before", "clipboard restore"
        lines.append("clipboard ok")
        for state in ("ready", "dictate", "compose", "busy"):
            icon_image(state)
        lines.append("icons ok")
        lines.append(f"foreground app: {winapi.foreground_app_name()}")
        lines.append(f"claude cli: {find_claude()}")
        import pystray, sounddevice  # noqa: F401
        from .worker import rss_mb
        lines.append(f"audio devices: {len(sounddevice.query_devices())}")
        assert "numpy" not in sys.modules, "the tray process shouldn't load numpy"
        assert "onnxruntime" not in sys.modules, "the tray process shouldn't load onnxruntime"
        lines.append(f"tray-side modules only: {rss_mb():.0f} MB")
        import onnx_asr  # noqa: F401  make sure the bundle has it
    except Exception as e:
        ok = False
        lines.append(f"FAILED: {type(e).__name__}: {e}\n{traceback.format_exc()}")
    output("\n".join(lines) + "\n", path)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
