import io
import math
import mido

# Krumhansl-Schmuckler Key Profiles (12 pitch classes: C, C#, D, Eb, E, F, F#, G, Ab, A, Bb, B)
_MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

_MIDO_MAJOR_KEYS = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
_MIDO_MINOR_KEYS = ['Cm', 'C#m', 'Dm', 'Ebm', 'Em', 'Fm', 'F#m', 'Gm', 'G#m', 'Am', 'Bbm', 'Bm']

_KEY_PRESET_MAP = {
    "c major / a minor": ("C", "Am"),
    "g major / e minor (1#)": ("G", "Em"),
    "d major / b minor (2#)": ("D", "Bm"),
    "a major / f# minor (3#)": ("A", "F#m"),
    "e major / c# minor (4#)": ("E", "C#m"),
    "b major / g# minor (5#)": ("B", "G#m"),
    "f# major / d# minor (6#)": ("F#", "D#m"),
    "f major / d minor (1b)": ("F", "Dm"),
    "bb major / g minor (2b)": ("Bb", "Gm"),
    "eb major / c minor (3b)": ("Eb", "Cm"),
    "ab major / f minor (4b)": ("Ab", "Fm"),
    "db major / bb minor (5b)": ("Db", "Bbm"),
    "gb major / eb minor (6b)": ("Gb", "Ebm"),
}


def parse_time_signature_string(ts_str: str) -> tuple[int, int]:
    """Parse time signature string such as '4/4 (Common Time)', '3/4', '6/8', etc."""
    clean = ts_str.split("(")[0].strip()
    if "/" in clean:
        parts = clean.split("/")
        try:
            num = int(parts[0].strip())
            denom = int(parts[1].strip())
            if num > 0 and denom in (1, 2, 4, 8, 16, 32):
                return num, denom
        except ValueError:
            pass
    return 4, 4


def detect_key_signature_from_midi(mid: mido.MidiFile) -> str:
    """Analyze MIDI pitch histogram using Krumhansl-Schmuckler algorithm."""
    histogram = [0.0] * 12
    ticks_per_beat = mid.ticks_per_beat or 480

    for track in mid.tracks:
        active = {}
        curr = 0
        for msg in track:
            curr += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                active[msg.note] = curr
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                if msg.note in active:
                    start = active.pop(msg.note)
                    dur = max(1, curr - start)
                    pitch_class = msg.note % 12
                    histogram[pitch_class] += dur / ticks_per_beat

    total = sum(histogram)
    if total == 0:
        return 'C'

    def pearson_corr(x, y):
        n = 12
        mx = sum(x) / n
        my = sum(y) / n
        num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
        den = math.sqrt(sum((x[i] - mx) ** 2 for i in range(n)) * sum((y[i] - my) ** 2 for i in range(n)))
        return num / den if den > 0 else 0

    best_score = -float('inf')
    best_key = 'C'

    for r in range(12):
        maj_r = _MAJOR_PROFILE[-r:] + _MAJOR_PROFILE[:-r]
        min_r = _MINOR_PROFILE[-r:] + _MINOR_PROFILE[:-r]

        c_maj = pearson_corr(histogram, maj_r)
        if c_maj > best_score:
            best_score = c_maj
            best_key = _MIDO_MAJOR_KEYS[r]

        c_min = pearson_corr(histogram, min_r)
        if c_min > best_score:
            best_score = c_min
            best_key = _MIDO_MINOR_KEYS[r]

    return best_key


def quantize_midi_tracks(
    mid: mido.MidiFile,
    grid_div: int = 4,
    quantize_strength: float = 1.0,
    fill_gaps_beats: float = 0.0,
    trim_leading_bars: bool = False,
    beats_per_bar: int = 4,
    time_sig_denom: int = 4
) -> mido.MidiFile:
    """Snap note onsets and durations to the specified beat grid.
    
    grid_div=4: sixteenth notes (no tuplets)
    grid_div=2: eighth notes (no tuplets)
    grid_div=8: thirty-second notes (no tuplets)
    grid_div=3: eighth triplets
    grid_div=6: sixteenth triplets
    """
    ticks_per_beat = mid.ticks_per_beat or 480
    ticks_per_quarter = ticks_per_beat
    ticks_per_beat_unit = int(round(ticks_per_quarter * (4.0 / time_sig_denom))) if time_sig_denom else ticks_per_beat

    if not grid_div or grid_div <= 0:
        grid_div = 4

    grid_ticks = max(1, int(round(ticks_per_beat_unit / grid_div)))
    fill_gap_ticks = int(round(fill_gaps_beats * ticks_per_beat_unit)) if fill_gaps_beats > 0 else 0
    ticks_per_bar = max(grid_ticks, int(round(ticks_per_beat_unit * beats_per_bar)))

    # Step 1: Check leading empty bars
    shift_ticks = 0
    if trim_leading_bars:
        earliest_note_tick = float('inf')
        for track in mid.tracks:
            curr = 0
            for msg in track:
                curr += msg.time
                if msg.type == 'note_on' and msg.velocity > 0:
                    if curr < earliest_note_tick:
                        earliest_note_tick = curr
        if earliest_note_tick != float('inf') and earliest_note_tick >= ticks_per_bar:
            shift_bars = int(earliest_note_tick // ticks_per_bar)
            shift_ticks = shift_bars * ticks_per_bar

    # Step 2: Quantize each track
    for t_idx, track in enumerate(mid.tracks):
        curr_tick = 0
        abs_events = []
        for msg in track:
            curr_tick += msg.time
            abs_events.append((curr_tick, msg))

        active_notes = {}
        note_pairs = []
        other_events = []

        for atick, msg in abs_events:
            if msg.type == 'note_on' and msg.velocity > 0:
                key = (msg.channel, msg.note)
                active_notes.setdefault(key, []).append((atick, msg))
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                key = (msg.channel, msg.note)
                if key in active_notes and active_notes[key]:
                    start_tick, on_msg = active_notes[key].pop(0)
                    note_pairs.append({
                        'channel': msg.channel,
                        'pitch': msg.note,
                        'start': start_tick,
                        'end': atick,
                        'on_msg': on_msg,
                        'off_msg': msg
                    })
                else:
                    other_events.append((atick, msg))
            else:
                other_events.append((atick, msg))

        # Close any lingering open notes
        for key, unclosed in active_notes.items():
            for start_tick, on_msg in unclosed:
                note_pairs.append({
                    'channel': key[0],
                    'pitch': key[1],
                    'start': start_tick,
                    'end': start_tick + grid_ticks,
                    'on_msg': on_msg,
                    'off_msg': mido.Message('note_off', channel=key[0], note=key[1], velocity=0, time=0)
                })

        note_pairs.sort(key=lambda n: (n['channel'], n['pitch'], n['start']))

        # Fill small rest gaps between consecutive notes of the same pitch
        if fill_gap_ticks > 0:
            for i in range(len(note_pairs) - 1):
                cur_n = note_pairs[i]
                next_n = note_pairs[i + 1]
                if cur_n['channel'] == next_n['channel'] and cur_n['pitch'] == next_n['pitch']:
                    gap = next_n['start'] - cur_n['end']
                    if 0 < gap <= fill_gap_ticks:
                        cur_n['end'] = next_n['start']

        quantized_events = []
        for n in note_pairs:
            orig_start = n['start']
            orig_dur = max(1, n['end'] - n['start'])

            snapped_start = int(round(orig_start / grid_ticks)) * grid_ticks
            new_start = int(round(orig_start + (snapped_start - orig_start) * quantize_strength))
            new_start = max(0, new_start - shift_ticks)

            snapped_dur = max(grid_ticks, int(round(orig_dur / grid_ticks)) * grid_ticks)
            new_dur = max(grid_ticks // 2, int(round(orig_dur + (snapped_dur - orig_dur) * quantize_strength)))
            new_end = new_start + new_dur

            quantized_events.append((new_start, n['on_msg']))
            quantized_events.append((new_end, n['off_msg']))

        for atick, msg in other_events:
            shifted = max(0, atick - shift_ticks) if atick > 0 else 0
            quantized_events.append((shifted, msg))

        def event_priority(item):
            tick, msg = item
            if getattr(msg, 'type', None) == 'end_of_track':
                return (tick, 999)
            if msg.is_meta:
                return (tick, 0)
            if msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                return (tick, 1)
            if msg.type == 'note_on':
                return (tick, 2)
            return (tick, 3)

        quantized_events.sort(key=event_priority)

        new_track = mido.MidiTrack()
        prev_tick = 0
        for atick, msg in quantized_events:
            delta = max(0, atick - prev_tick)
            msg.time = delta
            new_track.append(msg)
            prev_tick = atick

        mid.tracks[t_idx] = new_track

    return mid


def postprocess_midi(
    midi_source: str | bytes | mido.MidiFile,
    output_path: str | None = None,
    bpm: float = 120.0,
    time_sig_num: int = 4,
    time_sig_denom: int = 4,
    key_signature: str | None = "C",
    quantize: bool = True,
    grid_div: int = 4,
    quantize_strength: float = 1.0,
    fill_gaps_beats: float = 0.25,
    trim_leading_bars: bool = False,
    beat_scale: float = 1.0
) -> tuple[mido.MidiFile, bytes, dict]:
    """Execute complete musical timing, key signature, tempo, and quantization postprocessing."""
    if isinstance(midi_source, bytes):
        mid = mido.MidiFile(file=io.BytesIO(midi_source))
    elif isinstance(midi_source, mido.MidiFile):
        mid = midi_source
    else:
        mid = mido.MidiFile(str(midi_source))

    # Apply beat scale to BPM if specified
    effective_bpm = float(bpm) * float(beat_scale) if (bpm and beat_scale and beat_scale > 0) else float(bpm or 120.0)
    effective_bpm = max(20.0, min(400.0, effective_bpm))

    # Resolve or auto-detect key signature
    final_key = key_signature
    if not key_signature or "auto" in str(key_signature).lower():
        final_key = detect_key_signature_from_midi(mid)
    elif str(key_signature).lower() in _KEY_PRESET_MAP:
        final_key = _KEY_PRESET_MAP[str(key_signature).lower()][0]
    elif key_signature == "None" or "do not embed" in str(key_signature).lower():
        final_key = None

    # Apply quantization if requested
    if quantize:
        mid = quantize_midi_tracks(
            mid,
            grid_div=grid_div,
            quantize_strength=quantize_strength,
            fill_gaps_beats=fill_gaps_beats,
            trim_leading_bars=trim_leading_bars,
            beats_per_bar=time_sig_num,
            time_sig_denom=time_sig_denom
        )

    # Inject MetaMessages into Track 0
    tempo_track = mid.tracks[0] if mid.tracks else mido.MidiTrack()
    if not mid.tracks:
        mid.tracks.append(tempo_track)

    clean_track = []
    for msg in tempo_track:
        if msg.is_meta and msg.type in ('time_signature', 'key_signature', 'set_tempo'):
            continue
        clean_track.append(msg)
    tempo_track.clear()
    tempo_track.extend(clean_track)

    meta_msgs = []
    if time_sig_num and time_sig_denom:
        meta_msgs.append(mido.MetaMessage(
            'time_signature',
            numerator=int(time_sig_num),
            denominator=int(time_sig_denom),
            clocks_per_click=24,
            notated_32nd_notes_per_beat=8,
            time=0
        ))
    if final_key:
        try:
            meta_msgs.append(mido.MetaMessage('key_signature', key=str(final_key), time=0))
        except Exception:
            pass
    if effective_bpm and effective_bpm > 0:
        meta_msgs.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(effective_bpm), time=0))

    for m in reversed(meta_msgs):
        tempo_track.insert(0, m)

    # Serialize to bytes
    out_buf = io.BytesIO()
    mid.save(file=out_buf)
    out_bytes = out_buf.getvalue()

    if output_path:
        with open(output_path, "wb") as f:
            f.write(out_bytes)

    metadata = {
        "bpm": effective_bpm,
        "time_signature": f"{time_sig_num}/{time_sig_denom}",
        "beats_per_bar": time_sig_num,
        "time_sig_denom": time_sig_denom,
        "key_signature": final_key or "Unspecified",
        "quantized": quantize,
        "grid_div": grid_div,
        "no_tuplets": (grid_div in (1, 2, 4, 8, 16)),
    }

    return mid, out_bytes, metadata
