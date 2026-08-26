import time
from collections import defaultdict
from music21 import stream, chord as m21chord


def run_legacy_chord_analysis(score):
    """Legacy chord analysis using score.chordify()"""
    chordified = score.chordify()
    lines = ["CHORD ANALYSIS", "=" * 50]
    prev_label = None
    for c in chordified.flatten().getElementsByClass(m21chord.Chord):
        offset_sec = float(c.offset)
        ts = f"{int(offset_sec//60)}:{offset_sec%60:05.2f}"
        try:
            label = f"{c.root().name} {c.commonName}" if c.root() else " ".join(p.name for p in c.pitches)
        except Exception:
            label = " ".join(p.name for p in c.pitches)
        if label != prev_label:
            lines.append(f"[{ts}]  {label}")
            prev_label = label
    return lines


def run_optimized_chord_analysis(score):
    """Optimized timeline sweep chord analysis avoiding score.chordify()"""
    time_groups = defaultdict(list)
    for el in score.flatten().notes:
        start = float(el.offset)
        end = start + float(el.quarterLength)
        pitches = [el.pitch] if el.isNote else el.pitches
        for p in pitches:
            time_groups[start].append((1, p))
            time_groups[end].append((-1, p))

    lines = ["CHORD ANALYSIS", "=" * 50]
    active_pitches = defaultdict(int)
    prev_label = None
    prev_pitch_set = None

    for t in sorted(time_groups.keys()):
        # Process note-offs (-1) first, then note-ons (1)
        for event_type, p in sorted(time_groups[t], key=lambda x: x[0]):
            if event_type == -1:
                active_pitches[p] -= 1
                if active_pitches[p] <= 0:
                    del active_pitches[p]
            elif event_type == 1:
                active_pitches[p] += 1

        if active_pitches:
            current_pitch_set = frozenset(active_pitches.keys())
            if current_pitch_set != prev_pitch_set:
                c = m21chord.Chord(sorted(list(current_pitch_set)))
                ts = f"{int(t//60)}:{t%60:05.2f}"
                try:
                    label = f"{c.root().name} {c.commonName}" if c.root() else " ".join(p.name for p in c.pitches)
                except Exception:
                    label = " ".join(p.name for p in c.pitches)
                if label != prev_label:
                    lines.append(f"[{ts}]  {label}")
                    prev_label = label
                prev_pitch_set = current_pitch_set
    return lines


def test_chord_analysis_accuracy_and_performance():
    s = stream.Score()
    p1 = stream.Part()
    p2 = stream.Part()
    p3 = stream.Part()

    for i in range(200):
        c1 = m21chord.Chord(['C4', 'E4', 'G4'])
        c1.offset = i * 0.25
        c1.quarterLength = 0.5
        p1.insert(c1.offset, c1)

        c2 = m21chord.Chord(['A3', 'C4', 'E4'])
        c2.offset = i * 0.25 + 0.125
        c2.quarterLength = 0.5
        p2.insert(c2.offset, c2)

        c3 = m21chord.Chord(['G3', 'B3', 'D4'])
        c3.offset = (i % 20) * 2.5
        c3.quarterLength = 2.0
        p3.insert(c3.offset, c3)

    s.insert(0, p1)
    s.insert(0, p2)
    s.insert(0, p3)

    t0 = time.time()
    legacy_lines = run_legacy_chord_analysis(s)
    t_legacy = time.time() - t0

    t0 = time.time()
    optimized_lines = run_optimized_chord_analysis(s)
    t_optimized = time.time() - t0

    assert legacy_lines == optimized_lines, "Optimized chord analysis output must match legacy output"
    print(f"Test passed! Legacy: {t_legacy:.4f}s, Optimized: {t_optimized:.4f}s, Speedup: {t_legacy / max(t_optimized, 1e-6):.2f}x")


if __name__ == "__main__":
    test_chord_analysis_accuracy_and_performance()
