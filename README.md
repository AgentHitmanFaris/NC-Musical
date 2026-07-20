# NC-Musical: AI Music Transcription & Interactive Editor

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/AgentHitmanFaris/NC-Musical/blob/Stable/NC_Musical_Colab.ipynb)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)
![PyTorch CUDA](https://img.shields.io/badge/PyTorch-CUDA%20Accelerated-EE4C2C)
![FastAPI](https://img.shields.io/badge/FastAPI-Server-009688)
![SpessaSynth](https://img.shields.io/badge/SpessaSynth-v4.x%20SF3-purple)
![License](https://img.shields.io/badge/License-Proprietary-red)

NC-Musical is a production-grade, GPU-accelerated desktop and web application for Automatic Music Transcription (AMT) and interactive note editing. Built on top of the MuScriptor engine (MT3 architecture), it combines high-fidelity AI note extraction with an AnthemScore-style Piano Roll Editor and a real-time Web Audio SoundFont synthesis engine.

---

## Quick Start Guide

### 1. Cloud GPU Mode (Google Colab - Recommended)

Run NC-Musical with free NVIDIA GPU acceleration without installing local CUDA drivers or dependencies:

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/AgentHitmanFaris/NC-Musical/blob/Stable/NC_Musical_Colab.ipynb)

1. Open the [NC_Musical_Colab.ipynb](https://colab.research.google.com/github/AgentHitmanFaris/NC-Musical/blob/Stable/NC_Musical_Colab.ipynb) notebook in Google Colab.
2. Select **Runtime -> Change runtime type -> T4 GPU**.
3. Run Step 1 (Mount Google Drive) to enable persistent model caching. All model weights (~1.2GB) and SoundFonts will be stored in your Drive to make future startups instant.
4. Run Steps 2 to 4 to initialize dependencies and launch the backend.
5. Click the generated proxy URL (`https://...googleusercontent.com/.../index.html` or Cloudflare Tunnel link) to open the interactive Web GUI directly in your browser.

---

### 2. Local Desktop Application (Windows)

Launch NC-Musical as a native desktop application powered by WebView2:

1. Double-click the launcher script in the workspace root:
   ```cmd
   run_desktop.bat
   ```
2. Or execute via PowerShell/CMD:
   ```powershell
   .\venv\Scripts\python.exe app_desktop.py
   ```

---

### 3. Local Web Server Mode

Run the FastAPI backend server directly and access the Web GUI from any web browser:

```powershell
.\venv\Scripts\python.exe server_gui.py --port 8222 --model medium --device auto
```

Then open your browser and navigate to: `http://127.0.0.1:8222/index.html`

---

## Core Features

### AnthemScore-Style Piano Roll Editor
* **Select & Edit Mode (`1`):** Click and drag notes to adjust pitch and time. Drag note edges to alter duration. Select multiple notes using `Shift + Box Select` or keyboard arrow keys for micro-tuning.
* **Draw Mode (`2`):** Paint new notes on grid locations corresponding to the active target instrument.
* **Erase Mode (`3`):** Click notes to delete them instantly, or press `Delete` / `Backspace` on selected note clusters.
* **Undo/Redo Stack:** Full 50-step state history with `Ctrl + Z` and `Ctrl + Y` support.
* **Smart Auto-Follow:** Viewport smoothly pans during real-time playback or live AI transcription to keep the active playhead centered.

### Multi-Instrument SF3 SoundFont Synthesis
* **SpessaSynth SF3 Integration:** Integrated Web Audio API synthesizer utilizing `MS Basic.sf3` for multi-instrument sound reproduction (Piano, Nylon Guitar, Fingered Bass, Drums).
* **AudioWorklet Architecture:** Multi-threaded Web Audio processing prevents UI thread stuttering during note preview.
* **Solo & Mute Channels:** Granular per-track controls to solo or mute specific instruments during real-time MIDI playback.
* **Fallback Web Synth:** Synthetic oscillator fallback for quick preview if SoundFont loading is bypassed.

### Session & Project Management
* **Native OS File Save Dialogs:** Saves project JSON files and MIDI exports via a backend endpoint (`/save_file`), triggering native Windows File Save dialogs.
* **Save Project:** Package notes, track states, active instruments, and audio references into `.json` project files.
* **Load Project:** Restore previous editing sessions from `.json` files.
* **Download MIDI:** Export full transcription or edited piano roll notes as standard `.mid` files.
* **Auto-Save Protection:** Debounced LocalStorage auto-save with a session restore prompt on application launch.

### GPU Acceleration & Backend Audio Export
* **CUDA Hardware Detection:** Automatic detection and allocation of CUDA devices for MT3 model inference.
* **FluidSynth Backend Auralization:** Render transcribed MIDI back into high-fidelity WAV audio using local `MS Basic.sf3` SoundFonts and FluidSynth.

---

## Command Line Arguments (`server_gui.py`)

| Argument | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--host` | `str` | `127.0.0.1` | Bind IP address for the FastAPI server |
| `--port` | `int` | `8222` | Port number to listen on |
| `--model` | `str` | `large` | Model size: `small`, `medium`, or `large` |
| `--device` | `str` | `auto` | Execution device: `cuda`, `cpu`, or `auto` |

---

## Repository Structure

```
NC-Musical/
├── NC_Musical_Colab.ipynb   # Google Colab Notebook with GPU & Drive caching
├── index.html               # Main Web GUI (Piano Roll, SpessaSynth, Controls)
├── app_desktop.py           # Native pywebview Desktop Application Launcher
├── server_gui.py            # FastAPI Backend (Transcription, Save Dialogs, Auralize)
├── patch_muscriptor.py      # Dependency patching utility for muscriptor
├── run_desktop.bat          # One-click Windows desktop startup script
├── MS Basic.sf3             # High-quality General MIDI SoundFont
├── config.js                # Dynamic backend port configuration
└── README.md                # Project documentation
```

---

## License

This project is private and proprietary. All rights reserved.