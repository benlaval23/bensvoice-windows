# BensVoice for Windows

A tiny Windows tray app for talking to your computer, with two hotkeys:

- **Dictate**: speech to text in whatever field is focused, transcribed **locally** on your PC with NVIDIA's Parakeet model.
- **Compose**: say what you want written ("reply saying Thursday works but Friday's out"), and Claude Haiku writes it and pastes it in.

This is the Windows version of [BensVoice for Mac](https://github.com/benlaval23/bensvoice). It's a separate app that works the same way.

| Key | Action |
| --- | --- |
| Hold **Right Alt** | Dictate, release to paste |
| Hold **Right Ctrl** | Compose with Haiku, release to paste |
| Quick tap either key | Hands-free mode, tap again to finish |
| **Esc** | Cancel |

The tray icon shows the state: grey waveform (ready), red (dictating), purple sparkle (composing), spinner (transcribing / waiting on Haiku). Hover over it or click it to see the status line.

It's built to stay out of the way. The speech model (~850 MB in memory) runs in a helper process that **quits after 2 minutes idle**, so most of the time BensVoice is a single small process using almost no CPU. Holding a hotkey starts the model again in the background while you're still talking, so it's usually ready by the time you let go. The mic only runs while you hold a key.

In compose mode, Haiku also gets the name of the app you're in (casual tone for Slack or Teams, professional for Outlook, technical for Terminal or VS Code) and any text you have selected (e.g. the message you're replying to, or text to rewrite).

## Requirements

- **Windows 10 or 11** (64-bit)
- **A microphone**
- **About 1 GB free disk space** (the app plus the ~650 MB speech model, downloaded automatically on first launch)
- For compose mode, **one of**:
  - **[Claude Code](https://docs.claude.com/en/docs/claude-code) installed and logged in** with your Claude subscription (Pro or Max), **or**
  - an Anthropic API key

Dictation works without Claude. You only need Claude for compose mode.

## Install

### 1. Download the app

Go to [**Releases**](https://github.com/benlaval23/bensvoice-windows/releases/latest), download `BensVoice-Windows.zip`, and extract it somewhere permanent, such as `C:\Users\<you>\Apps\BensVoice`. Keep the whole folder together.

Double-click `BensVoice.exe`.

> **"Windows protected your PC"**: the app isn't code-signed (that costs money), so SmartScreen warns you the first time. Click **More info**, then **Run anyway**. If you'd rather not trust a downloaded exe, you can [run from source](#run-from-source) instead.

### 2. Wait for the first-run model download

On first launch the tray icon spins while it downloads the Parakeet speech model (~650 MB) from Hugging Face. This only happens once. After that it starts in a few seconds.

The tray icon may be hidden behind the **^** arrow in the taskbar. Drag it onto the taskbar to keep it visible.

### 3. Set up Claude (for compose mode)

**Option A: Claude Code subscription (default).** Install Claude Code by opening **PowerShell** and running:

```powershell
irm https://claude.ai/install.ps1 | iex
```

Then log in once:

```powershell
claude
# then type /login and follow the steps
```

Check that it works: `echo "say hi" | claude -p --model haiku`. BensVoice runs this CLI in the background, so nothing else is needed. Each compose takes about 2–3 s.

**Option B: API key (faster, ~1 s, billed per use).** Click the tray icon, choose **Open Settings Folder**, and put this in `config.json`:

```json
{ "anthropicApiKey": "sk-ant-...", "model": "claude-haiku-5-5" }
```

### 4. Start at login (optional)

Click the tray icon and turn on **Launch at Login**.

## Configuration

Optional `%APPDATA%\BensVoice\config.json` (tray menu › **Open Settings Folder**). Restart the app after changing it.

| Key | Default | Purpose |
| --- | --- | --- |
| `dictateKey` | `right alt` | Dictate hotkey |
| `composeKey` | `right ctrl` | Compose hotkey |
| `anthropicApiKey` | none | Use the API directly instead of the `claude` CLI |
| `model` | `claude-haiku-5-5` | Model when using an API key |
| `cliModel` | `haiku` | Model alias passed to `claude -p --model` |
| `keepModelLoadedMinutes` | `2` | How long the speech model stays in memory after you last used it. Higher means no reload wait. Lower means memory is freed sooner |
| `asrModel` | `nemo-parakeet-tdt-0.6b-v2` | Speech model. `nemo-parakeet-tdt-0.6b-v3` adds 24 more European languages |
| `quantization` | `int8` | Smaller, faster model. Set to `""` for full precision (bigger download, slightly more accurate) |

Hotkeys can be any of: `right alt`, `left alt`, `right ctrl`, `left ctrl`, `right shift`, `right win`, `caps lock`, `scroll lock`, `pause`, `insert`, `f1`–`f24`.

**AltGr keyboards** (French, German, Spanish and other layouts where Right Alt is AltGr): you need AltGr for characters like `@` and `€`, so move dictate to another key, e.g. `{ "dictateKey": "f8" }`.

## Troubleshooting

- **Nothing happens when I hold the key**: check the tray icon tooltip. If it says "Loading", the model is still downloading. Hotkeys also don't work while an app running as Administrator is focused (Windows blocks that). Running BensVoice as Administrator fixes it if you need it there.
- **Two apps react to the same key**: quit any other dictation app that uses the same hotkey, or change the BensVoice keys in the config.
- **Compose says it couldn't find `claude`**: BensVoice looks in `%USERPROFILE%\.local\bin`, your `PATH`, and `%APPDATA%\npm`. Make sure `claude` works in a new PowerShell window, then restart BensVoice.
- **Wrong microphone**: BensVoice uses the Windows default input device (Settings › System › Sound › Input).
- **The first word after a break takes a moment**: that's the model reloading after it was unloaded to save memory (about 1–3 s, mostly hidden while you talk). To keep it loaded longer, raise `keepModelLoadedMinutes`, e.g. `30`.
- **Something else**: the log is at `%APPDATA%\BensVoice\bensvoice.log`.
- **Test transcription without the GUI**: `BensVoice.exe --transcribe some.wav out.txt`

## Run from source

With Python 3.12:

```powershell
git clone https://github.com/benlaval23/bensvoice-windows.git
cd bensvoice-windows
pip install -r requirements.txt
pythonw -m bensvoice
```

To build the exe yourself: `pip install pyinstaller`, then run the same `pyinstaller` command as [the build workflow](.github/workflows/build.yml).

## How it works

- `winapi.py`: a low-level keyboard hook (watches keys, never blocks them), the clipboard swap used to paste (your clipboard is restored afterwards and the temporary text is kept out of Win+V history), and Ctrl+C to read the selection for compose.
- `transcriber.py`: Parakeet TDT via [onnx-asr](https://github.com/istupakov/onnx-asr) on the CPU. Recordings longer than 20 s are split at the quietest point near each boundary.
- `worker.py`: the model runs in a child process that exits when idle, so all of its memory goes back to Windows. The tray process never loads numpy or ONNX Runtime.
- `recorder.py`: 16 kHz mono capture. The mic only runs while you hold a key.
- `composer.py`: the Haiku prompt, through either the `claude` CLI or the Messages API.
- `app.py`: the tray icon and hotkey logic.

Every push is built and tested on Windows by GitHub Actions. Tagged versions are published to Releases.

## Credits

- [NVIDIA Parakeet TDT 0.6B v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) (CC-BY-4.0)
- ONNX conversion and runtime by [istupakov/onnx-asr](https://github.com/istupakov/onnx-asr)

## License

MIT
