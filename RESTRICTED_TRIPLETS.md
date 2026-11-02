# Restricted Triplets Quantization Engine

## Overview

In automated music transcription (AMT), quantization aligns expressive performance timings to a structured musical grid. Historically, quantization engines forced a binary choice:

1. **Straight Binary Grid (`--no-tuplets` / 1/16th Grid):**
   - Strictly quantizes onsets to power-of-two subdivisions (1/4, 1/8, 1/16, 1/32).
   - **Defect:** Obliterates genuine triplets (e.g. an 8th triplet at 160 ticks is warped to 120 or 240 ticks, destroying the phrase).

2. **Forced Triplet Grid (`grid_div=6` or `grid_div=3`):**
   - Quantizes all notes to triplet subdivisions (1/12 or 1/24 beats).
   - **Defect:** Forces all standard straight binary notes into triplet swing, ruining normal rhythms.

**Restricted Triplets** resolves this dilemma: **Straight binary 1/16 notes remain the mandatory priority grid**, while triplets are permitted as secondary candidates **only when a note or phrase genuinely fits a triplet subdivision significantly better than any binary grid point**.

---

## Architectural Mechanism

### 1. Dual-Grid Candidate Evaluation

At 480 PPQ (ticks per quarter note beat):
- **Binary Grid ($\Delta_{\text{binary}}$):** 120 ticks (1/16th note). Grid points: `[0, 120, 240, 360, 480, ...]`.
- **Triplet Grid ($\Delta_{\text{triplet}}$):** 80 ticks (1/16th triplet, covering 8th triplets at 160 ticks). Grid points: `[0, 80, 160, 240, 320, 400, 480, ...]`.

For every onset or duration $t$:
$$\text{snap}_{\text{binary}} = \text{round}\left(\frac{t}{\Delta_{\text{binary}}}\right) \times \Delta_{\text{binary}}, \quad \text{err}_{\text{binary}} = |t - \text{snap}_{\text{binary}}|$$
$$\text{snap}_{\text{triplet}} = \text{round}\left(\frac{t}{\Delta_{\text{triplet}}}\right) \times \Delta_{\text{triplet}}, \quad \text{err}_{\text{triplet}} = |t - \text{snap}_{\text{triplet}}|$$

### 2. Mandatory Binary Priority Rule

Binary rhythm is the baseline expectation of Western notation. Therefore, a note is locked to the binary grid whenever:
$$\text{err}_{\text{binary}} \le \max(4, 0.12 \times \Delta_{\text{binary}})$$

Human timing variance (e.g. playing a 16th note at tick 128 instead of 120) is snapped cleanly to tick 120 and will **never** trigger a false triplet.

### 3. Triplet Selection Criteria

A triplet position is chosen **if and only if** both conditions hold:
1. **Fit Confidence:** The note is tightly aligned with the triplet grid:
   $$\text{err}_{\text{triplet}} \le \max(6, 0.25 \times \Delta_{\text{triplet}})$$
2. **Binary Superiority Threshold:** Snapping to binary would introduce unacceptable distortion:
   $$\text{err}_{\text{binary}} > 1.6 \times \text{err}_{\text{triplet}} + 0.10 \times \Delta_{\text{binary}}$$

---

## Behavior Matrix

| Input Tick | Intended Note | Binary Snap (Err) | Triplet Snap (Err) | Standard (No Tuplets) | Forced Triplet | Restricted Triplets |
|---|---|---|---|---|---|---|
| **120** | Straight 16th | 120 (0) | 80 or 160 (40) | 120 | 80 / 160 (Corrupted) | **120** (Straight) |
| **128** | Jittered 16th | 120 (8) | 160 (32) | 120 | 160 (Corrupted) | **120** (Straight) |
| **160** | 8th Triplet (2/3) | 120 (40) | 160 (0) | 120 (Corrupted) | 160 | **160** (Triplet) |
| **240** | Straight 8th | 240 (0) | 240 (0) | 240 | 240 | **240** (Shared) |
| **320** | 8th Triplet (3/3) | 360 (40) | 320 (0) | 360 (Corrupted) | 320 | **320** (Triplet) |
| **640** | Beat 2 Triplet | 600 (40) | 640 (0) | 600 (Corrupted) | 640 | **640** (Triplet) |

---

## Configuration & Usage

### 1. Google Colab (`NC_Musical_Colab.ipynb` — Cell 4)

In the interactive Colab form:
```python
# @markdown ### 📐 Quantization & Triplets Control
restricted_triplets = True  # @param {type:"boolean"}
use_triplets = False        # @param {type:"boolean"}
```

- When `restricted_triplets = True`: Operates with binary priority, capturing genuine triplets without disturbing straight notes.
- When `restricted_triplets = False` and `use_triplets = False`: Strict straight binary grid (zero tuplets).
- When `use_triplets = True` and `restricted_triplets = False`: Pure forced triplet grid (legacy mode).

### 2. Standalone CLI (`transcribe.py`)

Run transcription with restricted triplets:
```bash
python transcribe.py input.mp3 -o output.mid --restricted-triplets
```

Strict binary grid without triplets:
```bash
python transcribe.py input.mp3 -o output.mid --no-restricted-triplets --no-tuplets
```

### 3. Programmatic API (`midi_processor.py`)

```python
from midi_processor import postprocess_midi

processed_mid, out_bytes, meta = postprocess_midi(
    midi_source="raw_input.mid",
    output_path="quantized.mid",
    bpm=120.0,
    quantize=True,
    grid_div=4,
    restricted_triplets=True
)
```
