# NC-Musical: AI Music Transcription (Google Colab GPU & TPU Pipeline)

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/AgentHitmanFaris/NC-Musical/blob/Stable/NC_Musical_Colab.ipynb)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)
![PyTorch CUDA & TPU](https://img.shields.io/badge/Hardware-CUDA%20%7C%20TPU%20v5e-EE4C2C)
![License](https://img.shields.io/badge/License-Proprietary-red)

**NC-Musical** is a high-performance Automatic Music Transcription (AMT) pipeline running directly inside **Google Colab**. Built on top of the MuScriptor / MT3 architecture, it converts audio, video, or YouTube links into multi-track MIDI notes and sheet music data with instant audio previews and automated chord analysis.

---

## Hardware Acceleration

NC-Musical supports both **NVIDIA GPUs** and **Google Cloud TPUs**:
* **Google Cloud TPU v5e-1** (via PyTorch/XLA & PJRT) — High-throughput inference.
* **NVIDIA GPUs** (T4, L4, A100, V100 via CUDA) — Fast low-latency inference.

---

## Quick Start (Google Colab)

Run NC-Musical with free hardware acceleration:

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/AgentHitmanFaris/NC-Musical/blob/Stable/NC_Musical_Colab.ipynb)

> **Note for Private Repositories:** Because this repository is private:
> 1. Open [colab.research.google.com](https://colab.research.google.com), select the **GitHub** tab, and check **Include private repos**.
> 2. Click **Authorize Colab** and select `AgentHitmanFaris/NC-Musical` -> `NC_Musical_Colab.ipynb`.
> 3. *Alternative:* Click **File -> Upload notebook** in Colab and upload `NC_Musical_Colab.ipynb` directly.

### Step-by-Step Execution:
1. In Colab, select **Runtime -> Change runtime type** and choose **T4 GPU** (recommended).
2. **Step 1 (Optional):** Connect Google Drive for persistent model and SoundFont caching (or uncheck to use fast session storage).
3. **Step 2:** Check Hardware environment and install dependencies with live `yt-dlp` master builds.
4. **Step 3:** Setup `MS Basic.sf3` SoundFont.
5. **Step 4:** Run **AI Music Transcription (Batch & Single)**:
   - Input: Paste single or multiple YouTube URLs (or leave blank to be prompted interactively), or upload multiple audio files.
   - The pipeline transcribes each song sequentially and names output `.mid` and `_chords.txt` files using the real song title.
   - Automatically downloads individual files and creates a combined `.zip` archive for batch jobs.

---

## Core Features

- **Instrument Focus & Isolation (Radio Presets + Custom Checkboxes):** Isolate specific parts from the mix (Piano Only, Acoustic & Electric Guitars, Bass & Drums, Vocals / Melody, Strings / Brass / Woodwinds, or Full Mix).
- **Sequential Batch Transcription:** Queue multiple YouTube links or uploaded audio files; transcribe them in a single run.
- **Original Song Title Naming:** Automatically extracts YouTube video titles (or uploaded file stems) and generates `<Song_Title>.mid` and `<Song_Title>_chords.txt`.
- **Dynamic Interactive Prompts:** No hardcoded YouTube URLs — input via form or interactive prompt.
- **Future-Proof YouTube Ingestion:** Always pulls latest upstream master releases of `yt-dlp` with multi-client fallbacks (`ios`, `android`, `web`, `tv_embedded`) and cookie support.
- **Flexible Storage:** Optional 1-click Google Drive caching or fast ephemeral session storage without requiring permissions.
- **Automated Chord Analysis:** Extracts and timestamps harmonic progressions using `music21`.
- **In-Notebook Audio Synthesis:** FluidSynth auralization rendering MIDI output back to WAV audio directly in Colab.
- **Instant File Downloads & Batch ZIP:** Automatically triggers browser downloads for individual outputs and bundles batch jobs into a `.zip` archive.

---

## Repository Structure

```
NC-Musical/
├── NC_Musical_Colab.ipynb   # Main Google Colab Notebook pipeline
├── patch_muscriptor.py      # Dependency patch utility for muscriptor in Colab
├── transcribe.py            # Standalone CLI transcription script
├── MS Basic.sf3             # High-quality General MIDI SoundFont
└── README.md                # Project documentation
```

---

## License

This project is private and proprietary. All rights reserved.