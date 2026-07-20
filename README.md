# NC-Musical (MuScriptor AMT Desktop Editor)

NC-Musical is a high-performance, GPU-accelerated desktop application for Automatic Music Transcription (AMT) and interactive note editing. Built on top of the MuScriptor engine, it features an interactive AnthemScore-style Piano Roll Editor and a real-time synchronized playback engine.

---

## Key Features

### 1. Interactive AnthemScore-Style Piano Roll Editor
* **Select Mode (`1`):** Select notes, shift pitch/time via mouse dragging or arrow keys, resize boundaries by dragging note edges, and box-select multiple notes (`Shift + Drag`).
* **Draw Mode (`2`):** Click and drag on empty grid positions to paint new notes matching the active instrument.
* **Erase Mode (`3`):** Click notes to erase them instantly, or press `Delete` / `Backspace` on selected notes.
* **History Operations:** Undo (`Ctrl + Z`) and Redo (`Ctrl + Y`) support with a 50-step change stack.
* **Visual Pan / Zoom / Follow:** 
  * Keyboard shortcuts (`A` to scroll left, `D` to scroll right, mouse wheel to zoom in/out).
  * Auto-Follow mode that centers and smoothly pans the view during playback or live transcription.

### 2. Multi-Instrument SoundFont & Synth Engine
* **SpessaSynth SF3 Live Preview:** Integrated Web Audio API synthesizer powered by SpessaSynth v4 and local `MS Basic.sf3` soundfont for accurate multi-instrument sound reproduction.
* **Fallback Web Synth:** Synthetic fallback oscillators for drum bursts, plucked guitars, low bass, and general keyboards when soundfont is uninitialized.
* **Solo & Mute Channels:** Individual controls to mute or solo specific tracks during real-time MIDI playback.
* **Volume Controls:** Full scaling of original audio and synth volume via dedicated control sliders.

### 3. Project & File Management
* **Native Desktop File Saving:** Desktop mode (`file://` protocol) routes save requests through a dedicated backend endpoint (`/save_file`) that launches native OS file save dialogs for MIDI and project files.
* **Save Project:** Instantly package all notes, customized tracks, active instruments, and audio references into a `.json` project file.
* **Load Project:** Upload any saved project `.json` to continue editing your transcription seamlessly.
* **Download MIDI:** Export full transcription or edited piano roll notes as standard `.mid` files.
* **Local Auto-Save:** Automatically saves progress (debounced) to LocalStorage with a session restore prompt upon application launch.

### 4. GPU Inference & Backend Audio Rendering
* **GPU Detection:** Automatic detection of CUDA-capable hardware (e.g., NVIDIA GPUs) to run transcription inferences.
* **FluidSynth Backend Rendering:** Utilizes local `MS Basic.sf3` soundfont files and standalone FluidSynth installations for high-quality audio export and auralization.

---

## Installation & Setup

1. **Prerequisites:**
   * Python 3.10+ (installed in `venv`)
   * Standalone FluidSynth binaries placed in `D:\Document\NC-Project\sheetsage\AtoScore_Core\bin`
   * PyTorch installed with CUDA support in the virtual environment.

2. **Patching Backend Dependencies:**
   Run the utility script to override default soundfont loaders in the venv:
   ```bash
   venv/Scripts/python.exe patch_muscriptor.py
   ```

---

## How to Run

### Local Desktop Mode
Run the desktop launcher script in the workspace root:
```bash
run_desktop.bat
```
This starts the Python FastAPI server in the background and launches the desktop GUI window.

### Google Colab (Cloud GPU Mode)
Run NC-Musical on Google Colab with free GPU acceleration:
1. Open the [NC_Musical_Colab.ipynb](https://colab.research.google.com/github/AgentHitmanFaris/NC-Musical/blob/Stable/NC_Musical_Colab.ipynb) notebook in Google Colab.
2. Select **Runtime -> Change runtime type -> T4 GPU**.
3. Run all cells in order.
4. Click the generated public link to open the interactive Web GUI directly in your browser.

---

## License
This project is private and proprietary. All rights reserved.