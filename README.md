# NC-Musical (MuScriptor AMT Desktop Editor)

NC-Musical is a high-performance, GPU-accelerated desktop application for Automatic Music Transcription (AMT) and interactive note editing. Built on top of the MuScriptor engine, it features an interactive **AnthemScore-style Piano Roll Editor** and a real-time synchronized playback engine.

---

## 🚀 Key Features

### 1. Interactive AnthemScore-Style Piano Roll Editor
* **Select Mode (`1`):** Select notes, shift pitch/time via mouse dragging or arrow keys, resize boundaries by dragging note edges, and box-select multiple notes (`Shift + Drag`).
* **Draw Mode (`2`):** Click and drag on empty grid positions to paint new notes matching the active instrument.
* **Erase Mode (`3`):** Click notes to erase them instantly, or press `Delete` / `Backspace` on selected notes.
* **History Operations:** Undo (`Ctrl + Z`) and Redo (`Ctrl + Y`) support with a 50-step change stack.
* **Visual Pan/Scroll:** Keyboard shortcuts (`A` to scroll left, `D` to scroll right, mouse wheel to zoom in/out).

### 2. Multi-Instrument Real-Time Playback Synth
* **Real-Time Client Synth:** Integrates custom Web Audio API synthesis for different instrument classes:
  * 🥁 **Drums/Percussion:** High/low bandpass noise bursts and deep pitch-swept sine thuds to simulate kicks, snares, and cymbals.
  * 🎸 **Bass:** Deep, lowpassed sawtooth wave synthesis.
  * 🎻 **Guitar:** Acoustic plucked triangle waves with rapid decay envelopes.
  * 🎹 **Piano/General:** Clean, round triangle oscillators.
* **Solo & Mute Channels:** Individual controls to mute or solo specific tracks during real-time MIDI playback.
* **Synth Volume Control:** Full scaling of client-side notes via the MIDI Synth Volume slider.

### 3. Session Progress Management
* **Save Project:** Instantly package all notes, customized tracks, active instruments, and audio references into a `.json` project file.
* **Load Project:** Upload any saved project `.json` to continue editing your transcription seamlessly.
* **Local Auto-Save:** Automatically saves progress (debounced) to browser LocalStorage. If the window closes, it prompts you with a banner to restore your session on restart.

### 4. GPU Inference & Local Soundfont rendering
* **GPU Detection:** Automatic detection of CUDA-capable hardware (e.g. GTX 1060) to run transcription inferences.
* **FluidSynth Backend Rendering:** Utilizes local `MS Basic.sf3` soundfont files and standalone FluidSynth installations for high-quality audio export and auralization.

---

## 🛠️ Installation & Setup

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

## 💻 How to Run

Simply double-click the startup script in the workspace root:
```bash
run_desktop.bat
```
This runs the Python FastAPI backend in the background and launches the native webview application instantly.

---

## 📄 License
This project is private and proprietary. All rights reserved.