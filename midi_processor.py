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
    """Parse time signature string such as '4/4 (Common Time)', '3/4', '6/8', or 'auto'."""
    if not ts_str or "auto" in str(ts_str).lower():
        return 4, 4
    clean = str(ts_str).split("(")[0].strip()
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


def detect_time_signature_from_midi(mid: mido.MidiFile) -> tuple[int, int]:
    """Auto-detect time signature (numerator, denominator) from MIDI meta or onset periodicity."""
    for track in mid.tracks:
        for msg in track:
            if msg.type == 'time_signature' and getattr(msg, 'numerator', 0) > 0:
                return int(msg.numerator), int(msg.denominator)

    ticks_per_beat = mid.ticks_per_beat or 480
    onsets_beats = []
    for track in mid.tracks:
        curr = 0
        for msg in track:
            curr += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                onsets_beats.append(curr / ticks_per_beat)

    if len(onsets_beats) < 12:
        return 4, 4

    # Measure alignment with 3-beat (waltz/triple meter) vs 4-beat (common time)
    score_3 = sum(1 for b in onsets_beats if abs(b % 3.0) < 0.15 or abs(3.0 - (b % 3.0)) < 0.15)
    score_4 = sum(1 for b in onsets_beats if abs(b % 4.0) < 0.15 or abs(4.0 - (b % 4.0)) < 0.15)

    if score_3 > score_4 * 1.35:
        return 3, 4

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


def separate_multichannel_tracks(mid: mido.MidiFile) -> mido.MidiFile:
    """Separate any tracks containing multiple MIDI channels into dedicated individual tracks.
    
    This ensures that when opened in MuseScore, each instrument/channel lands on its own
    clean staff rather than being merged into a single staff with overlapping voices.
    """
    new_mid = mido.MidiFile(ticks_per_beat=mid.ticks_per_beat or 480)
    
    # Track 0 preserves global meta messages (tempo, meter, key)
    tempo_track = mido.MidiTrack()
    new_mid.tracks.append(tempo_track)
    
    # Collect all channel events and meta events across all tracks
    channel_tracks = {}
    
    for track in mid.tracks:
        curr_tick = 0
        for msg in track:
            curr_tick += msg.time
            if msg.is_meta:
                if msg.type in ('set_tempo', 'time_signature', 'key_signature', 'smpte_offset'):
                    tempo_track.append(msg.copy(time=curr_tick))
                else:
                    # Generic meta messages can route to channel 0 or active channel
                    channel_tracks.setdefault(0, []).append((curr_tick, msg))
            else:
                ch = getattr(msg, 'channel', 0)
                channel_tracks.setdefault(ch, []).append((curr_tick, msg))
                
    # Sort tempo track events and convert to delta times
    tempo_track_events = sorted([(msg.time, msg) for msg in tempo_track], key=lambda x: x[0])
    tempo_track.clear()
    prev = 0
    for tick, msg in tempo_track_events:
        msg.time = max(0, tick - prev)
        tempo_track.append(msg)
        prev = tick
    tempo_track.append(mido.MetaMessage('end_of_track', time=0))
    
    # GM Instrument name hints for clean MuseScore display
    instrument_names = {
        0: "Vocal / Lead Melody",
        1: "Acoustic Piano",
        2: "Electric Piano",
        3: "Acoustic Guitar",
        4: "Electric Guitar",
        5: "Bass",
        6: "Strings",
        7: "Brass / Horns",
        8: "Woodwinds / Flutes",
        9: "Drums / Percussion",
        10: "Synth Lead",
        11: "Synth Pad"
    }

    # Build separate tracks for each channel
    for ch in sorted(channel_tracks.keys()):
        raw_events = channel_tracks[ch]
        # Skip empty channel tracks
        has_notes = any((getattr(m, 'type', '') == 'note_on' and getattr(m, 'velocity', 0) > 0) for _, m in raw_events)
        if not has_notes and ch != 0:
            continue
            
        track = mido.MidiTrack()
        track_title = instrument_names.get(ch, f"Track (Channel {ch + 1})")
        track.append(mido.MetaMessage('track_name', name=track_title, time=0))
        
        # Sort events by absolute tick
        raw_events.sort(key=lambda x: x[0])
        prev_t = 0
        for atick, msg in raw_events:
            msg_copy = msg.copy()
            msg_copy.time = max(0, atick - prev_t)
            track.append(msg_copy)
            prev_t = atick
        track.append(mido.MetaMessage('end_of_track', time=0))
        new_mid.tracks.append(track)
        
    if len(new_mid.tracks) == 1:
        # If no notes were found, ensure at least one track
        empty_tr = mido.MidiTrack()
        empty_tr.append(mido.MetaMessage('track_name', name="Lead Melody", time=0))
        empty_tr.append(mido.MetaMessage('end_of_track', time=0))
        new_mid.tracks.append(empty_tr)

    return new_mid


def clean_monophonic_voice(
    note_pairs: list[dict],
    grid_ticks: int = 120,
    fill_gap_ticks: int = 120,
    priority: str = "velocity_pitch"
) -> list[dict]:
    """Force notes into a strictly single, monophonic melody line (Voice 1 in MuseScore).
    
    MuseScore creates 2-voicing (Moonlight Sonata 1st movement style with Voice 1 up-stems
    and Voice 2 down-stems plus separate rests) whenever notes on the same staff overlap
    in time. This function guarantees:
      1. At any tick, at most ONE note sounds (ghost overtones & chord bleed are eliminated).
      2. No note overlaps the subsequent note: note[i].end <= note[i+1].start.
      3. Consecutive notes connect cleanly without fragmented micro-rests.
    """
    if not note_pairs:
        return []

    # Sort strictly chronologically by start time.
    # For simultaneous onsets, place the dominant melody note (highest velocity or highest pitch) first.
    def sort_key(n):
        vel = getattr(n.get('on_msg'), 'velocity', 64)
        return (n['start'], -vel, -n['pitch'])

    sorted_notes = sorted(note_pairs, key=sort_key)
    
    # Pass 1: Eliminate polyphonic simultaneous notes and resolve collisions
    single_chain = []
    for n in sorted_notes:
        if not single_chain:
            single_chain.append(dict(n))
            continue
            
        prev = single_chain[-1]
        
        # If the new note starts at the exact same tick, keep the dominant note
        if n['start'] == prev['start']:
            n_vel = getattr(n.get('on_msg'), 'velocity', 64)
            prev_vel = getattr(prev.get('on_msg'), 'velocity', 64)
            if (n_vel > prev_vel) or (n_vel == prev_vel and n['pitch'] > prev['pitch']):
                single_chain[-1] = dict(n)
            continue
            
        # If previous note extends past the start of the new note, truncate previous note!
        if prev['end'] > n['start']:
            prev['end'] = n['start']
            # If the truncated previous note became negligibly short (< grid_ticks / 4), discard it as noise
            if prev['end'] - prev['start'] < max(1, grid_ticks // 4):
                single_chain.pop()
                if single_chain and single_chain[-1]['end'] > n['start']:
                    single_chain[-1]['end'] = n['start']
                    
        single_chain.append(dict(n))

    # Pass 2: Legato rest filling between consecutive syllables
    if fill_gap_ticks > 0:
        for i in range(len(single_chain) - 1):
            cur_n = single_chain[i]
            next_n = single_chain[i + 1]
            gap = next_n['start'] - cur_n['end']
            if 0 < gap <= fill_gap_ticks:
                cur_n['end'] = next_n['start']

    # Pass 3: Final validation — verify zero overlaps
    cleaned = []
    for n in single_chain:
        if n['end'] > n['start']:
            cleaned.append(n)
            
    for i in range(len(cleaned) - 1):
        if cleaned[i]['end'] > cleaned[i + 1]['start']:
            cleaned[i]['end'] = cleaned[i + 1]['start']

    return cleaned


def quantize_midi_tracks(
    mid: mido.MidiFile,
    grid_div: int = 4,
    quantize_strength: float = 1.0,
    fill_gaps_beats: float = 0.0,
    trim_leading_bars: bool = False,
    beats_per_bar: int = 4,
    time_sig_denom: int = 4,
    single_voice: bool = True,
    separate_channels: bool = True
) -> mido.MidiFile:
    """Snap note onsets and durations to the specified beat grid and eliminate multi-voicing.
    
    grid_div=4: sixteenth notes (no tuplets)
    grid_div=2: eighth notes (no tuplets)
    grid_div=8: thirty-second notes (no tuplets)
    grid_div=3: eighth triplets
    grid_div=6: sixteenth triplets
    
    single_voice=True: Enforces strictly 1 clean voice (Voice 1 in MuseScore) with ZERO overlaps.
    separate_channels=True: Splits channels into dedicated tracks so MuseScore creates clean individual staves.
    """
    ticks_per_beat = mid.ticks_per_beat or 480
    ticks_per_quarter = ticks_per_beat
    ticks_per_beat_unit = int(round(ticks_per_quarter * (4.0 / time_sig_denom))) if time_sig_denom else ticks_per_beat

    if not grid_div or grid_div <= 0:
        grid_div = 4

    grid_ticks = max(1, int(round(ticks_per_beat_unit / grid_div)))
    fill_gap_ticks = int(round(fill_gaps_beats * ticks_per_beat_unit)) if fill_gaps_beats > 0 else 0
    ticks_per_bar = max(grid_ticks, int(round(ticks_per_beat_unit * beats_per_bar)))

    # Step 1: Optionally separate channels to avoid multi-instrument collisions in a single staff
    working_mid = separate_multichannel_tracks(mid) if separate_channels else mid

    # Step 2: Check leading empty bars
    shift_ticks = 0
    if trim_leading_bars:
        earliest_note_tick = float('inf')
        for track in working_mid.tracks:
            curr = 0
            for msg in track:
                curr += msg.time
                if msg.type == 'note_on' and msg.velocity > 0:
                    if curr < earliest_note_tick:
                        earliest_note_tick = curr
        if earliest_note_tick != float('inf') and earliest_note_tick >= ticks_per_bar:
            shift_bars = int(earliest_note_tick // ticks_per_bar)
            shift_ticks = shift_bars * ticks_per_bar

    # Step 3: Quantize and clean each track
    for t_idx, track in enumerate(working_mid.tracks):
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

        if not note_pairs:
            continue

        # If single_voice mode is enabled, enforce monophonic vocal line before quantization
        if single_voice:
            note_pairs = clean_monophonic_voice(
                note_pairs,
                grid_ticks=grid_ticks,
                fill_gap_ticks=fill_gap_ticks
            )
        else:
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

        # Quantize onsets and durations
        quantized_notes = []
        for n in note_pairs:
            orig_start = n['start']
            orig_dur = max(1, n['end'] - n['start'])

            snapped_start = int(round(orig_start / grid_ticks)) * grid_ticks
            new_start = int(round(orig_start + (snapped_start - orig_start) * quantize_strength))
            new_start = max(0, new_start - shift_ticks)

            snapped_dur = max(grid_ticks, int(round(orig_dur / grid_ticks)) * grid_ticks)
            new_dur = max(grid_ticks // 2, int(round(orig_dur + (snapped_dur - orig_dur) * quantize_strength)))
            new_end = new_start + new_dur

            quantized_notes.append({
                'channel': n['channel'],
                'pitch': n['pitch'],
                'start': new_start,
                'end': new_end,
                'on_msg': n['on_msg'],
                'off_msg': n['off_msg']
            })

        # CRITICAL: Post-quantization non-overlap guarantee
        # Quantizing durations can cause snapped notes to bleed into the next note's start.
        # In single_voice mode, clamp each note's end so it never overlaps the next onset!
        if single_voice:
            quantized_notes.sort(key=lambda x: (x['start'], -getattr(x.get('on_msg'), 'velocity', 64), -x['pitch']))
            non_overlapping = []
            for qn in quantized_notes:
                if not non_overlapping:
                    non_overlapping.append(qn)
                    continue
                prev = non_overlapping[-1]
                if qn['start'] <= prev['start']:
                    # Same onset collision post-snap: keep dominant note
                    qn_vel = getattr(qn.get('on_msg'), 'velocity', 64)
                    prev_vel = getattr(prev.get('on_msg'), 'velocity', 64)
                    if (qn_vel > prev_vel) or (qn_vel == prev_vel and qn['pitch'] > prev['pitch']):
                        non_overlapping[-1] = qn
                    continue
                if prev['end'] > qn['start']:
                    prev['end'] = qn['start']
                    if prev['end'] <= prev['start']:
                        non_overlapping.pop()
                non_overlapping.append(qn)
            quantized_notes = [qn for qn in non_overlapping if qn['end'] > qn['start']]

        quantized_events = []
        for qn in quantized_notes:
            quantized_events.append((qn['start'], qn['on_msg']))
            quantized_events.append((qn['end'], qn['off_msg']))

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

        working_mid.tracks[t_idx] = new_track

    return working_mid


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
    beat_scale: float = 1.0,
    single_voice: bool = True,
    separate_channels: bool = True
) -> tuple[mido.MidiFile, bytes, dict]:
    """Execute complete musical timing, key signature, tempo, quantization, and single-voice postprocessing.
    
    single_voice=True (Default): Guarantees clean 1-voice notation (Voice 1 in MuseScore) with NO overlaps.
    separate_channels=True (Default): Splits multi-channel tracks so each instrument gets its own staff.
    """
    if isinstance(midi_source, bytes):
        mid = mido.MidiFile(file=io.BytesIO(midi_source))
    elif isinstance(midi_source, mido.MidiFile):
        mid = midi_source
    else:
        mid = mido.MidiFile(str(midi_source))

    # Apply beat scale to BPM if specified
    effective_bpm = float(bpm) * float(beat_scale) if (bpm and beat_scale and beat_scale > 0) else float(bpm or 120.0)
    effective_bpm = max(20.0, min(400.0, effective_bpm))

    # Resolve or auto-detect time signature
    if time_sig_num is None or str(time_sig_num).lower() in ("auto", "none"):
        eff_ts_num, eff_ts_denom = detect_time_signature_from_midi(mid)
    else:
        eff_ts_num, eff_ts_denom = int(time_sig_num), int(time_sig_denom or 4)

    # Resolve or auto-detect key signature
    final_key = key_signature
    if not key_signature or "auto" in str(key_signature).lower():
        final_key = detect_key_signature_from_midi(mid)
    elif str(key_signature).lower() in _KEY_PRESET_MAP:
        final_key = _KEY_PRESET_MAP[str(key_signature).lower()][0]
    elif key_signature == "None" or "do not embed" in str(key_signature).lower():
        final_key = None

    # Apply quantization and single-voice processing
    if quantize or single_voice or separate_channels:
        mid = quantize_midi_tracks(
            mid,
            grid_div=grid_div,
            quantize_strength=quantize_strength,
            fill_gaps_beats=fill_gaps_beats,
            trim_leading_bars=trim_leading_bars,
            beats_per_bar=eff_ts_num,
            time_sig_denom=eff_ts_denom,
            single_voice=single_voice,
            separate_channels=separate_channels
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
    if eff_ts_num and eff_ts_denom:
        meta_msgs.append(mido.MetaMessage(
            'time_signature',
            numerator=int(eff_ts_num),
            denominator=int(eff_ts_denom),
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
        "time_signature": f"{eff_ts_num}/{eff_ts_denom}",
        "beats_per_bar": eff_ts_num,
        "time_sig_denom": eff_ts_denom,
        "key_signature": final_key or "Unspecified",
        "quantized": quantize,
        "grid_div": grid_div,
        "no_tuplets": (grid_div in (1, 2, 4, 8, 16)),
        "single_voice": single_voice,
        "separate_channels": separate_channels
    }

    return mid, out_bytes, metadata
