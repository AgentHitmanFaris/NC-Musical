import io
import math
from pathlib import Path
import mido

try:
    from lyrics_aligner import align_lyrics_to_notes, parse_lyrics
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from lyrics_aligner import align_lyrics_to_notes, parse_lyrics

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


def separate_multichannel_tracks(mid: mido.MidiFile, lyrics: str | Path | list | None = None) -> mido.MidiFile:
    """Separate MIDI channels and instruments into dedicated staves for MuseScore.
    
    1. Piano is partitioned into a complete Grand Staff:
       - 'Piano (Right Hand - Treble Clef)': Notes >= 60 (Treble staff with full polyphonic chords)
       - 'Piano (Left Hand - Bass Clef)': Notes < 60 (Bass staff with full polyphonic chords)
    2. Drums are assigned to Channel 9 with full polyphonic kit (Kick, Snare, Hi-Hat, etc.).
    3. Guitars are separated into distinct tracks:
       - 'Distorted Electric Guitar' (Overdrive/Distortion)
       - 'Clean Electric Guitar' (or Acoustic Guitar)
       - 'Electric Bass' (Bass Clef)
    4. Vocals are assigned to a dedicated Track: 'Vocals (Clean Voice 1)'.
    5. Strings, Brass, Woodwinds, and Synths are assigned to their own dedicated staves.
    """
    new_mid = mido.MidiFile(ticks_per_beat=mid.ticks_per_beat or 480)
    
    # Track 0 preserves global meta messages (tempo, meter, key)
    tempo_track = mido.MidiTrack()
    new_mid.tracks.append(tempo_track)
    
    # Track active program per channel and gather all note pairs & non-note events
    active_program = {}
    note_events_by_group = {}
    other_events = []
    
    # First pass: map tempo track meta messages
    for track in mid.tracks:
        curr_tick = 0
        for msg in track:
            curr_tick += msg.time
            if msg.is_meta and msg.type in ('set_tempo', 'time_signature', 'key_signature', 'smpte_offset'):
                tempo_track.append(msg.copy(time=curr_tick))
                
    tempo_track_events = sorted([(msg.time, msg) for msg in tempo_track], key=lambda x: x[0])
    tempo_track.clear()
    prev = 0
    for tick, msg in tempo_track_events:
        msg.time = max(0, tick - prev)
        tempo_track.append(msg)
        prev = tick
    tempo_track.append(mido.MetaMessage('end_of_track', time=0))

    # Second pass: extract note pairs with instrument classification
    for track in mid.tracks:
        curr_tick = 0
        active_notes = {}
        track_meta_name = ""
        for msg in track:
            if msg.is_meta and msg.type == 'track_name':
                track_meta_name = msg.name.lower()
                break

        for msg in track:
            curr_tick += msg.time
            if msg.is_meta:
                continue
            ch = getattr(msg, 'channel', 0)
            if msg.type == 'program_change':
                active_program[ch] = msg.program
            elif msg.type == 'note_on' and msg.velocity > 0:
                prog = active_program.get(ch, None)
                active_notes.setdefault((ch, msg.note), []).append((curr_tick, msg, prog, track_meta_name))
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                k = (ch, msg.note)
                if k in active_notes and active_notes[k]:
                    start_t, on_msg, prog, tname = active_notes[k].pop(0)
                    
                    # Instrument classification
                    if ch == 9 or "drum" in tname:
                        grp = 'drums'
                    elif "vocal" in tname or "voice" in tname or prog in (52, 53, 54, 85, 91) or (ch == 0 and (prog is None or prog in (52, 53, 54, 85, 91)) and "piano" not in tname and "guitar" not in tname):
                        grp = 'vocal'
                    elif "piano" in tname or "keys" in tname or (prog in (0, 1, 2, 3, 4, 5) and ch != 0) or (prog in (0, 1, 2, 3, 4, 5) and "piano" in tname):
                        grp = 'piano'
                    elif "bass" in tname or prog in (32, 33, 34, 35, 36, 37, 38, 39):
                        grp = 'bass'
                    elif "distort" in tname or prog in (29, 30):
                        grp = 'dist_guitar'
                    elif "guitar" in tname or prog in (24, 25, 26, 27, 28):
                        grp = 'clean_guitar'
                    elif prog is not None and 40 <= prog <= 51:
                        grp = 'strings'
                    elif prog is not None and 56 <= prog <= 63:
                        grp = 'brass'
                    elif prog is not None and 64 <= prog <= 75:
                        grp = 'woodwinds'
                    elif prog is not None and 80 <= prog <= 103:
                        grp = 'synth'
                    elif prog in (0, 1, 2, 3, 4, 5):
                        grp = 'piano'
                    else:
                        grp = 'vocal' if ch == 0 else f'inst_{prog or ch}'

                    note_events_by_group.setdefault(grp, []).append({
                        'channel': ch,
                        'program': prog or 0,
                        'pitch': msg.note,
                        'start': start_t,
                        'end': curr_tick,
                        'on_msg': on_msg,
                        'off_msg': msg
                    })

    # If no structured groups found, fallback to basic tracks
    if not note_events_by_group:
        empty_tr = mido.MidiTrack()
        empty_tr.append(mido.MetaMessage('track_name', name="Lead Melody", time=0))
        empty_tr.append(mido.MetaMessage('end_of_track', time=0))
        new_mid.tracks.append(empty_tr)
        return new_mid

    # Helper to serialize note pairs into a new MidiTrack
    def _create_track(title, channel, program, notes):
        if not notes:
            return None
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage('track_name', name=title, time=0))
        tr.append(mido.Message('program_change', channel=channel, program=program, time=0))
        events = []
        for n in notes:
            on_m = n['on_msg'].copy(channel=channel)
            off_m = n['off_msg'].copy(channel=channel)
            if n.get('lyric'):
                l_info = n['lyric']
                txt = l_info['text'] if isinstance(l_info, dict) else str(l_info)
                if isinstance(l_info, dict) and l_info.get('syllabic') in ('begin', 'middle'):
                    txt = txt + "-"
                events.append((n['start'], 0, mido.MetaMessage('lyrics', text=txt, time=0)))
            events.append((n['start'], 2, on_m))
            events.append((n['end'], 1, off_m))
        events.sort(key=lambda x: (x[0], x[1]))
        prev_t = 0
        for atick, _, m in events:
            m.time = max(0, atick - prev_t)
            tr.append(m)
            prev_t = atick
        tr.append(mido.MetaMessage('end_of_track', time=0))
        return tr

    # 1. Vocals Track (Channel 0, Program 54)
    if 'vocal' in note_events_by_group:
        vocal_notes = note_events_by_group['vocal']
        if lyrics:
            vocal_notes = align_lyrics_to_notes(vocal_notes, lyrics, ticks_per_beat=mid.ticks_per_beat or 480)
        tr = _create_track("Vocals (Clean Voice 1)", 0, 54, vocal_notes)
        if tr: new_mid.tracks.append(tr)

    # 2. Piano Grand Staff: Treble Clef (RH >= 60) and Bass Clef (LH < 60)
    if 'piano' in note_events_by_group:
        piano_notes = note_events_by_group['piano']
        rh_notes = [n for n in piano_notes if n['pitch'] >= 60]
        lh_notes = [n for n in piano_notes if n['pitch'] < 60]

        if rh_notes:
            tr_rh = _create_track("Piano (Right Hand - Treble Clef)", 1, 0, rh_notes)
            if tr_rh: new_mid.tracks.append(tr_rh)
        if lh_notes:
            tr_lh = _create_track("Piano (Left Hand - Bass Clef)", 2, 0, lh_notes)
            if tr_lh: new_mid.tracks.append(tr_lh)
        if not rh_notes and not lh_notes:
            tr_p = _create_track("Piano (Full Grand Staff)", 1, 0, piano_notes)
            if tr_p: new_mid.tracks.append(tr_p)

    # 3. Clean / Acoustic Guitar (Channel 3, Program 27/25)
    if 'clean_guitar' in note_events_by_group:
        tr = _create_track("Clean Electric Guitar", 3, 27, note_events_by_group['clean_guitar'])
        if tr: new_mid.tracks.append(tr)

    # 4. Distorted Electric Guitar (Channel 4, Program 29)
    if 'dist_guitar' in note_events_by_group:
        tr = _create_track("Distorted Electric Guitar", 4, 29, note_events_by_group['dist_guitar'])
        if tr: new_mid.tracks.append(tr)

    # 5. Electric Bass (Channel 5, Program 33 - Bass Clef)
    if 'bass' in note_events_by_group:
        tr = _create_track("Electric Bass", 5, 33, note_events_by_group['bass'])
        if tr: new_mid.tracks.append(tr)

    # 6. Strings (Channel 6, Program 48)
    if 'strings' in note_events_by_group:
        tr = _create_track("Strings Ensemble", 6, 48, note_events_by_group['strings'])
        if tr: new_mid.tracks.append(tr)

    # 7. Brass (Channel 7, Program 61)
    if 'brass' in note_events_by_group:
        tr = _create_track("Brass Section", 7, 61, note_events_by_group['brass'])
        if tr: new_mid.tracks.append(tr)

    # 8. Woodwinds / Flutes (Channel 8, Program 73)
    if 'woodwinds' in note_events_by_group:
        tr = _create_track("Woodwinds / Flutes", 8, 73, note_events_by_group['woodwinds'])
        if tr: new_mid.tracks.append(tr)

    # 9. Synthesizer / Pads (Channel 10, Program 80)
    if 'synth' in note_events_by_group:
        tr = _create_track("Synthesizer", 10, 80, note_events_by_group['synth'])
        if tr: new_mid.tracks.append(tr)

    # 10. Drums (Channel 9, Program 0 - GM Standard Kit)
    if 'drums' in note_events_by_group:
        tr = _create_track("Drums (Full Kit)", 9, 0, note_events_by_group['drums'])
        if tr: new_mid.tracks.append(tr)

    # Any remaining unmapped groups
    for grp, notes in note_events_by_group.items():
        if grp not in ('vocal', 'piano', 'clean_guitar', 'dist_guitar', 'bass', 'strings', 'brass', 'woodwinds', 'synth', 'drums'):
            prog = notes[0].get('program', 0)
            ch = min(15, max(11, notes[0].get('channel', 11)))
            tr = _create_track(f"Instrument (Track {grp})", ch, prog, notes)
            if tr: new_mid.tracks.append(tr)

    return new_mid


def clean_monophonic_vocal(
    note_pairs: list[dict],
    grid_ticks: int = 120,
    fill_gap_ticks: int = 120
) -> list[dict]:
    """Fine-tuned vocal melody cleaner: produces the cleanest single-voice notation and structure.
    
    1. Rejects spurious transient blips (< 24 ticks / ~30ms) caused by unvoiced consonants/breath noise.
    2. Filters non-vocal acoustic rumble (< 36) and high overtone squeaks (> 90).
    3. Resolves polyphonic overtone collisions: selects the dominant fundamental pitch
       (favoring higher acoustic velocity and melodic continuity within singing range).
    4. Enforces strict zero-overlap: note[i].end <= note[i+1].start (no 2-voicing in MuseScore).
    5. Applies natural legato smoothing: connects syllables across small breath gaps (<= 1/16th)
       while preserving natural pauses.
    """
    if not note_pairs:
        return []

    min_dur = max(24, grid_ticks // 4)
    # Sort chronologically by start time; for same onset, higher velocity and singing-range pitch first
    def sort_key(n):
        vel = getattr(n.get('on_msg'), 'velocity', 64)
        p = n['pitch']
        in_vocal_range = 1 if 40 <= p <= 85 else 0
        return (n['start'], -vel, -in_vocal_range, -p)

    sorted_notes = sorted(note_pairs, key=sort_key)
    chain = []
    
    for n in sorted_notes:
        dur = n['end'] - n['start']
        # Filter micro-jitter blips
        if dur < min_dur:
            continue
        # Filter out-of-range vocal noise if outside standard vocal compass
        if n['pitch'] < 36 or n['pitch'] > 92:
            continue

        if not chain:
            chain.append(dict(n))
            continue

        prev = chain[-1]
        
        # Same onset collision: pick the dominant fundamental vocal note
        if n['start'] == prev['start']:
            n_vel = getattr(n.get('on_msg'), 'velocity', 64)
            prev_vel = getattr(prev.get('on_msg'), 'velocity', 64)
            if n_vel > prev_vel + 10:
                chain[-1] = dict(n)
            elif abs(n_vel - prev_vel) <= 10:
                # Prefer central vocal register (A2 to A5, 45 to 81)
                if 45 <= n['pitch'] <= 81 and (prev['pitch'] < 45 or prev['pitch'] > 81):
                    chain[-1] = dict(n)
                elif n['pitch'] > prev['pitch'] and 45 <= n['pitch'] <= 84:
                    chain[-1] = dict(n)
            continue

        # If previous note extends past the start of the new note, truncate previous note!
        if prev['end'] > n['start']:
            prev['end'] = n['start']
            if prev['end'] - prev['start'] < min_dur:
                chain.pop()
                if chain and chain[-1]['end'] > n['start']:
                    chain[-1]['end'] = n['start']

        chain.append(dict(n))

    # Natural legato smoothing between consecutive syllables
    if fill_gap_ticks > 0:
        for i in range(len(chain) - 1):
            cur_n = chain[i]
            next_n = chain[i + 1]
            gap = next_n['start'] - cur_n['end']
            if 0 < gap <= fill_gap_ticks:
                cur_n['end'] = next_n['start']

    cleaned = [n for n in chain if n['end'] > n['start']]
    for i in range(len(cleaned) - 1):
        if cleaned[i]['end'] > cleaned[i + 1]['start']:
            cleaned[i]['end'] = cleaned[i + 1]['start']

    return cleaned


def clean_monophonic_voice(
    note_pairs: list[dict],
    grid_ticks: int = 120,
    fill_gap_ticks: int = 120
) -> list[dict]:
    """General monophonic voice reduction (for Bass and Lead lines)."""
    return clean_monophonic_vocal(note_pairs, grid_ticks=grid_ticks, fill_gap_ticks=fill_gap_ticks)


def quantize_midi_tracks(
    mid: mido.MidiFile,
    grid_div: int = 4,
    quantize_strength: float = 1.0,
    fill_gaps_beats: float = 0.0,
    trim_leading_bars: bool = False,
    beats_per_bar: int = 4,
    time_sig_denom: int = 4,
    single_voice: bool = True,
    separate_channels: bool = True,
    restricted_triplets: bool = False,
    lyrics: str | Path | list | None = None
) -> mido.MidiFile:
    """Snap note onsets and durations to the specified beat grid and eliminate multi-voicing.
    
    grid_div=4: sixteenth notes (no tuplets)
    grid_div=2: eighth notes (no tuplets)
    grid_div=8: thirty-second notes (no tuplets)
    grid_div=3: eighth triplets
    grid_div=6: sixteenth triplets
    
    restricted_triplets=True: Straight binary grid is primary priority; triplets allowed
                              only when notes clearly fit them, without forcing the entire piece.
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

    # Determine triplet grid for restricted triplets mode
    triplet_ticks = None
    if restricted_triplets:
        if grid_div in (3, 6, 12):
            triplet_ticks = grid_ticks
            base_binary_div = 4 if grid_div == 6 else (2 if grid_div == 3 else 8)
            grid_ticks = max(1, int(round(ticks_per_beat_unit / base_binary_div)))
        else:
            triplet_div = int(round(grid_div * 1.5))
            triplet_ticks = max(1, int(round(ticks_per_beat_unit / triplet_div)))

    def _snap_tick_value(val: int, binary_step: int, triplet_step: int | None, allow_triplets: bool) -> int:
        snapped_b = int(round(val / binary_step)) * binary_step
        if not allow_triplets or triplet_step is None:
            return snapped_b

        snapped_t = int(round(val / triplet_step)) * triplet_step
        err_b = abs(val - snapped_b)
        err_t = abs(val - snapped_t)

        # Straight binary grid is mandatory priority.
        # If binary match is already close (within 12% of step), keep binary.
        if err_b <= max(4, binary_step * 0.12):
            return snapped_b

        # Only accept triplet if it is a strong fit and noticeably better than binary
        if err_t <= max(6, triplet_step * 0.25) and err_b > (err_t * 1.6 + binary_step * 0.10):
            return snapped_t

        return snapped_b

    # Step 1: Optionally separate channels to avoid multi-instrument collisions in a single staff
    working_mid = separate_multichannel_tracks(mid, lyrics=lyrics) if separate_channels else mid

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
        track_lyrics = {}

        for atick, msg in abs_events:
            if msg.is_meta and msg.type == 'lyrics' and getattr(msg, 'text', None):
                track_lyrics[atick] = msg.text
            elif msg.type == 'note_on' and msg.velocity > 0:
                key = (msg.channel, msg.note)
                active_notes.setdefault(key, []).append((atick, msg))
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                key = (msg.channel, msg.note)
                if key in active_notes and active_notes[key]:
                    start_tick, on_msg = active_notes[key].pop(0)
                    lyric_obj = None
                    if start_tick in track_lyrics:
                        lyric_obj = {'text': track_lyrics[start_tick], 'syllabic': 'single'}
                    note_pairs.append({
                        'channel': msg.channel,
                        'pitch': msg.note,
                        'start': start_tick,
                        'end': atick,
                        'on_msg': on_msg,
                        'off_msg': msg,
                        'lyric': lyric_obj
                    })
                else:
                    other_events.append((atick, msg))
            else:
                other_events.append((atick, msg))

        # Close any lingering open notes
        for key, unclosed in active_notes.items():
            for start_tick, on_msg in unclosed:
                lyric_obj = {'text': track_lyrics[start_tick], 'syllabic': 'single'} if start_tick in track_lyrics else None
                note_pairs.append({
                    'channel': key[0],
                    'pitch': key[1],
                    'start': start_tick,
                    'end': start_tick + grid_ticks,
                    'on_msg': on_msg,
                    'off_msg': mido.Message('note_off', channel=key[0], note=key[1], velocity=0, time=0),
                    'lyric': lyric_obj
                })

        if not note_pairs:
            continue

        # Extract track metadata to determine instrument type
        track_name = ""
        for msg in track:
            if msg.is_meta and msg.type == 'track_name':
                track_name = msg.name
                break
        tname_lower = track_name.lower()

        is_piano_track = ("piano" in tname_lower) or ("grand staff" in tname_lower)
        is_drums_track = ("drum" in tname_lower) or any(getattr(m, 'channel', 0) == 9 for m in track if not m.is_meta)
        is_guitar_track = ("guitar" in tname_lower) and ("bass" not in tname_lower)
        is_bass_track = ("bass" in tname_lower) and not is_drums_track and not is_piano_track
        is_other_polyphonic = ("strings" in tname_lower) or ("brass" in tname_lower) or ("woodwinds" in tname_lower) or ("synth" in tname_lower)

        is_polyphonic = is_piano_track or is_drums_track or is_guitar_track or is_other_polyphonic
        is_vocal_track = ("vocal" in tname_lower) or ("voice" in tname_lower) or (not is_polyphonic and not is_bass_track)

        # Voicing strategy:
        # 1. Vocals: Strict fine-tuned monophonic reduction (Voice 1 in MuseScore, zero 2-voicing)
        # 2. Bass: Monophonic bassline reduction (clean bass clef)
        # 3. Piano, Drums, Guitars: PRESERVE FULL POLYPHONY (Chords, Full Drum Kit, Both Piano Hands)
        if is_vocal_track and single_voice:
            note_pairs = clean_monophonic_vocal(
                note_pairs,
                grid_ticks=grid_ticks,
                fill_gap_ticks=fill_gap_ticks
            )
            if lyrics and not any(n.get('lyric') for n in note_pairs):
                note_pairs = align_lyrics_to_notes(note_pairs, lyrics, ticks_per_beat=ticks_per_beat)
        elif is_bass_track and single_voice:
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
        min_step = min(grid_ticks, triplet_ticks) if (restricted_triplets and triplet_ticks) else grid_ticks
        for n in note_pairs:
            orig_start = n['start']
            orig_dur = max(1, n['end'] - n['start'])

            snapped_start = _snap_tick_value(orig_start, grid_ticks, triplet_ticks, restricted_triplets)
            new_start = int(round(orig_start + (snapped_start - orig_start) * quantize_strength))
            new_start = max(0, new_start - shift_ticks)

            snapped_dur = _snap_tick_value(orig_dur, grid_ticks, triplet_ticks, restricted_triplets)
            snapped_dur = max(min_step, snapped_dur)
            new_dur = max(min_step // 2, int(round(orig_dur + (snapped_dur - orig_dur) * quantize_strength)))
            new_end = new_start + new_dur

            quantized_notes.append({
                'channel': n['channel'],
                'pitch': n['pitch'],
                'start': new_start,
                'end': new_end,
                'on_msg': n['on_msg'],
                'off_msg': n['off_msg'],
                'lyric': n.get('lyric')
            })

        # CRITICAL: Post-quantization non-overlap guarantee ONLY for monophonic tracks (Vocals & Bass)
        # Polyphonic tracks (Piano, Drums, Guitars) keep ALL simultaneous chord notes & drum hits!
        if is_vocal_track or (is_bass_track and single_voice):
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
            if qn.get('lyric'):
                l_info = qn['lyric']
                txt = l_info['text'] if isinstance(l_info, dict) else str(l_info)
                if isinstance(l_info, dict) and l_info.get('syllabic') in ('begin', 'middle'):
                    txt = txt + "-"
                quantized_events.append((qn['start'], mido.MetaMessage('lyrics', text=txt, time=0)))
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
    separate_channels: bool = True,
    restricted_triplets: bool = False,
    lyrics: str | Path | list | None = None
) -> tuple[mido.MidiFile, bytes, dict]:
    """Execute complete musical timing, key signature, tempo, quantization, and single-voice postprocessing.
    
    lyrics: Optional text or parsed lyrics list to align directly onto notes of the vocal track.
    restricted_triplets=True: Straight binary grid remains primary/priority, allowing triplets
                              only when notes naturally fit them, without forcing the whole track.
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
            separate_channels=separate_channels,
            restricted_triplets=restricted_triplets,
            lyrics=lyrics
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
        "restricted_triplets": restricted_triplets,
        "no_tuplets": (not restricted_triplets and (grid_div in (1, 2, 4, 8, 16))),
        "single_voice": single_voice,
        "separate_channels": separate_channels
    }

    return mid, out_bytes, metadata
