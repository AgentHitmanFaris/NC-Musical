## 2026-08-26 - Fast Timeline Sweep vs `music21.score.chordify()`
**Learning:** `music21.score.chordify()` is extremely slow (O(N^2) measure-level score re-alignment) when extracting chord labels from multi-track MIDI scores. Performing an O(N log N) event timeline sweep (sorting pitch onset/offset events) yields ~10x-13x faster chord analysis while generating identical harmonic progression labels.
**Action:** Replace `score.chordify()` with an event-driven note-on/note-off timeline sweep whenever harmonic progressions are extracted from MIDI notes in Python.
