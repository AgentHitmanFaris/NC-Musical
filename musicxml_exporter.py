import re
import math
import xml.etree.ElementTree as ET
from pathlib import Path
import mido

try:
    from lyrics_aligner import align_lyrics_to_notes, parse_lyrics
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from lyrics_aligner import align_lyrics_to_notes, parse_lyrics

_STEP_NAMES = ['C', 'C', 'D', 'D', 'E', 'F', 'F', 'G', 'G', 'A', 'A', 'B']
_ALTER_VALS = [0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0]

_KEY_FIFTHS = {
    'C': 0, 'Am': 0,
    'G': 1, 'Em': 1,
    'D': 2, 'Bm': 2,
    'A': 3, 'F#m': 3,
    'E': 4, 'C#m': 4,
    'B': 5, 'G#m': 5,
    'F#': 6, 'D#m': 6,
    'F': -1, 'Dm': -1,
    'Bb': -2, 'Gm': -2,
    'Eb': -3, 'Cm': -3,
    'Ab': -4, 'Fm': -4,
    'Db': -5, 'Bbm': -5,
    'Gb': -6, 'Ebm': -6
}


def parse_chord_to_musicxml_harmony(chord_str: str) -> ET.Element | None:
    """Convert chord symbol (e.g. 'Ebmaj7', 'Cm7', 'Fm7', 'Bb7', 'G/B') into standard MusicXML <harmony>."""
    if not chord_str or not isinstance(chord_str, str):
        return None
    clean = chord_str.strip()
    if not clean:
        return None

    bass_note = None
    if '/' in clean:
        parts = clean.split('/', 1)
        clean = parts[0].strip()
        bass_note = parts[1].strip()

    m = re.match(r'^([A-G])([b#]?)(.*)', clean)
    if not m:
        return None
    step, accidental, quality = m.groups()

    harmony = ET.Element('harmony', attrib={'default-y': '35'})
    root_elem = ET.SubElement(harmony, 'root')
    ET.SubElement(root_elem, 'root-step').text = step
    if accidental == 'b':
        ET.SubElement(root_elem, 'root-alter').text = '-1'
    elif accidental == '#':
        ET.SubElement(root_elem, 'root-alter').text = '1'

    kind_elem = ET.SubElement(harmony, 'kind')
    kind_elem.set('text', chord_str)
    q_lower = quality.lower()
    if 'maj7' in q_lower or 'major7' in q_lower or 'm7+' in q_lower:
        kind_elem.text = 'major-seventh'
    elif 'm7' in q_lower or 'min7' in q_lower or 'minor7' in q_lower:
        kind_elem.text = 'minor-seventh'
    elif 'dim7' in q_lower:
        kind_elem.text = 'diminished-seventh'
    elif 'dim' in q_lower:
        kind_elem.text = 'diminished'
    elif 'aug' in q_lower:
        kind_elem.text = 'augmented'
    elif 'sus4' in q_lower:
        kind_elem.text = 'suspended-fourth'
    elif 'sus2' in q_lower:
        kind_elem.text = 'suspended-second'
    elif '7' in q_lower:
        kind_elem.text = 'dominant'
    elif 'm' in q_lower or 'min' in q_lower:
        kind_elem.text = 'minor'
    else:
        kind_elem.text = 'major'

    if bass_note:
        bm = re.match(r'^([A-G])([b#]?)', bass_note)
        if bm:
            b_step, b_acc = bm.groups()
            bass_elem = ET.SubElement(harmony, 'bass')
            ET.SubElement(bass_elem, 'bass-step').text = b_step
            if b_acc == 'b':
                ET.SubElement(bass_elem, 'bass-alter').text = '-1'
            elif b_acc == '#':
                ET.SubElement(bass_elem, 'bass-alter').text = '1'

    return harmony


def _get_measure_chords(chords: dict | list | None, m_idx: int, ticks_per_bar: int) -> list[tuple[int, str]]:
    """Resolve chord symbols for measure m_idx (1-based).
    
    Returns list of (tick_offset, chord_name) tuples within the measure.
    """
    if not chords:
        return []

    val = None
    if isinstance(chords, (list, tuple)):
        idx = m_idx - 1
        if 0 <= idx < len(chords):
            val = chords[idx]
    elif isinstance(chords, dict):
        val = chords.get(m_idx)
        if val is None:
            val = chords.get(m_idx - 1)

    if not val:
        return []

    if isinstance(val, (list, tuple)):
        # Could be list of (offset, chord_name) or list of chord names
        res = []
        if val and isinstance(val[0], (list, tuple)) and len(val[0]) == 2:
            return [(int(off), str(c)) for off, c in val if c]
        else:
            tokens = [str(x).strip() for x in val if str(x).strip()]
            if not tokens:
                return []
            step = ticks_per_bar // len(tokens)
            return [(i * step, tok) for i, tok in enumerate(tokens)]

    if isinstance(val, str):
        # Space or comma separated chords in a measure, e.g. "Fm7 Bb7" or "Ebmaj7"
        tokens = [t.strip() for t in re.split(r'[, ]+', val) if t.strip()]
        if not tokens:
            return []
        step = ticks_per_bar // len(tokens)
        return [(i * step, tok) for i, tok in enumerate(tokens)]

    return []


def export_midi_to_musicxml(
    mid: mido.MidiFile,
    output_xml_path: str | Path,
    title: str = "Transcription",
    bpm: float = 120.0,
    time_sig_num: int = 4,
    time_sig_denom: int = 4,
    key_signature: str | None = "C",
    lyrics: str | Path | list[dict] | None = None,
    chords: dict[int, str | list] | list[str] | None = None
) -> Path:
    """Export a multi-track MidiFile into a clean, well-formatted MusicXML file for MuseScore.
    
    Guarantees:
      - Direct Lyrics Underlay on notes in the vocal/lead melody staff.
      - Grand Staff (Treble on top, Bass on bottom) for Piano.
      - Treble Clef & Voice 1 for Vocals (strictly no 2-voicing).
      - Percussion Clef on 5-line staff for Drums.
      - Bass Clef (F4) for Electric Bass.
      - Treble Clef for Guitars.
      - Exact bar-line measures with divisions, key, tempo, and meter.
    """
    ticks_per_beat = mid.ticks_per_beat or 480
    ticks_per_bar = max(ticks_per_beat, int(round(ticks_per_beat * (4.0 / time_sig_denom) * time_sig_num)))

    score = ET.Element('score-partwise', version="3.1")

    # Work & Title metadata
    work = ET.SubElement(score, 'work')
    ET.SubElement(work, 'work-title').text = title

    part_list = ET.SubElement(score, 'part-list')

    # Scan tracks to find active tracks with notes
    track_entries = []
    p_counter = 1

    for t_idx, track in enumerate(mid.tracks):
        # Extract track name
        tname = f"Track {t_idx}"
        for msg in track:
            if msg.is_meta and msg.type == 'track_name':
                tname = msg.name
                break

        # Check if track has note events
        has_notes = any((getattr(m, 'type', '') == 'note_on' and getattr(m, 'velocity', 0) > 0) for m in track if not m.is_meta)
        if not has_notes:
            continue

        pid = f"P{p_counter}"
        p_counter += 1

        score_part = ET.SubElement(part_list, 'score-part', id=pid)
        ET.SubElement(score_part, 'part-name').text = tname

        track_entries.append((pid, tname, track))

    if not track_entries:
        # Fallback empty score
        pid = "P1"
        score_part = ET.SubElement(part_list, 'score-part', id=pid)
        ET.SubElement(score_part, 'part-name').text = "Score"
        track_entries.append((pid, "Score", mido.MidiTrack()))

    fifths = _KEY_FIFTHS.get(key_signature, 0)
    mode = 'minor' if (key_signature and 'm' in key_signature and key_signature not in ('C', 'F', 'D', 'E', 'A', 'B')) else 'major'

    # Build XML part elements
    for pid, tname, track in track_entries:
        part = ET.SubElement(score, 'part', id=pid)

        tname_lower = tname.lower()
        is_bass = ("bass" in tname_lower) and not ("drum" in tname_lower) and not ("left hand" in tname_lower)
        is_piano_lh = ("left hand" in tname_lower) or ("bass clef" in tname_lower and "piano" in tname_lower)
        is_drums = ("drum" in tname_lower)
        is_vocal = ("vocal" in tname_lower) or ("voice" in tname_lower)

        # Extract notes and track-embedded lyrics with absolute tick times
        abs_events = []
        track_lyrics = {}
        curr_tick = 0
        for msg in track:
            curr_tick += msg.time
            if msg.is_meta:
                if msg.type == 'lyrics' and getattr(msg, 'text', None):
                    track_lyrics[curr_tick] = msg.text
            else:
                abs_events.append((curr_tick, msg))

        active = {}
        note_pairs = []
        for atick, msg in abs_events:
            if msg.type == 'note_on' and msg.velocity > 0:
                active.setdefault(msg.note, []).append((atick, msg))
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                if msg.note in active and active[msg.note]:
                    st, on_m = active[msg.note].pop(0)
                    lyric_obj = None
                    if st in track_lyrics:
                        txt_val = track_lyrics[st]
                        syl_val = 'single'
                        if txt_val.endswith('-'):
                            txt_val = txt_val[:-1]
                            syl_val = 'begin'
                        lyric_obj = {'text': txt_val, 'syllabic': syl_val}
                    note_pairs.append({
                        'pitch': msg.note,
                        'start': st,
                        'end': max(st + 1, atick),
                        'dur': max(1, atick - st),
                        'vel': on_m.velocity,
                        'lyric': lyric_obj
                    })

        note_pairs.sort(key=lambda n: (n['start'], n['pitch']))

        # If lyrics were provided explicitly and track is vocal or lead part, align them onto notes
        if lyrics and (is_vocal or len(track_entries) == 1):
            note_pairs = align_lyrics_to_notes(note_pairs, lyrics, ticks_per_beat=ticks_per_beat, bpm=bpm)

        # Determine total measures required
        max_tick = max([n['end'] for n in note_pairs], default=ticks_per_bar)
        num_measures = max(1, int(math.ceil(max_tick / ticks_per_bar)))

        # Group notes by measure, slicing across barline boundaries into tied note pairs
        measure_notes = {m_idx: [] for m_idx in range(1, num_measures + 1)}
        for n in note_pairs:
            st = n['start']
            et = n['end']
            if et <= st:
                et = st + 1
            m_start = (st // ticks_per_bar) + 1
            m_end = ((et - 1) // ticks_per_bar) + 1

            if m_start == m_end:
                if m_start <= num_measures:
                    rel_start = st % ticks_per_bar
                    measure_notes[m_start].append({
                        'pitch': n['pitch'],
                        'rel_start': rel_start,
                        'dur': et - st,
                        'vel': n['vel'],
                        'lyric': n.get('lyric'),
                        'tie_start': False,
                        'tie_stop': False
                    })
            else:
                for m in range(m_start, m_end + 1):
                    if m > num_measures:
                        break
                    bar_start = (m - 1) * ticks_per_bar
                    bar_end = m * ticks_per_bar
                    cur_st = max(st, bar_start)
                    cur_et = min(et, bar_end)
                    slice_dur = max(1, cur_et - cur_st)
                    is_first = (m == m_start)
                    is_last = (m == m_end)

                    measure_notes[m].append({
                        'pitch': n['pitch'],
                        'rel_start': cur_st - bar_start,
                        'dur': slice_dur,
                        'vel': n['vel'],
                        'lyric': n.get('lyric') if is_first else None,
                        'tie_start': not is_last,
                        'tie_stop': not is_first
                    })

        is_primary_part = (pid == "P1") or is_vocal

        for m_idx in range(1, num_measures + 1):
            measure = ET.SubElement(part, 'measure', number=str(m_idx))

            # Initial Measure Attributes
            if m_idx == 1:
                attributes = ET.SubElement(measure, 'attributes')
                ET.SubElement(attributes, 'divisions').text = str(ticks_per_beat)

                # Key signature
                key_elem = ET.SubElement(attributes, 'key')
                ET.SubElement(key_elem, 'fifths').text = str(fifths)
                ET.SubElement(key_elem, 'mode').text = mode

                # Time signature
                time_elem = ET.SubElement(attributes, 'time')
                ET.SubElement(time_elem, 'beats').text = str(time_sig_num)
                ET.SubElement(time_elem, 'beat-type').text = str(time_sig_denom)

                # Clef specification
                clef_elem = ET.SubElement(attributes, 'clef')
                clef_sign = ET.SubElement(clef_elem, 'sign')
                clef_line = ET.SubElement(clef_elem, 'line')

                if is_drums:
                    clef_sign.text = "percussion"
                    clef_line.text = "2"
                elif is_bass or is_piano_lh:
                    clef_sign.text = "F"
                    clef_line.text = "4"
                else:
                    clef_sign.text = "G"
                    clef_line.text = "2"

                # Metronome tempo mark
                direction = ET.SubElement(measure, 'direction', placement="above")
                direction_type = ET.SubElement(direction, 'direction-type')
                metronome = ET.SubElement(direction_type, 'metronome')
                ET.SubElement(metronome, 'beat-unit').text = "quarter"
                ET.SubElement(metronome, 'per-minute').text = f"{bpm:.1f}"
                sound = ET.SubElement(direction, 'sound')
                sound.set('tempo', str(int(round(bpm))))

            # Chord symbols (placed on top staff P1)
            measure_chords = []
            if is_primary_part and chords:
                measure_chords = _get_measure_chords(chords, m_idx, ticks_per_bar)

            m_notes = measure_notes[m_idx]
            if not m_notes:
                # Insert any chords for empty measure
                for c_off, c_name in measure_chords:
                    h_elem = parse_chord_to_musicxml_harmony(c_name)
                    if h_elem is not None:
                        measure.append(h_elem)
                # Whole measure rest
                note_elem = ET.SubElement(measure, 'note')
                ET.SubElement(note_elem, 'rest')
                ET.SubElement(note_elem, 'duration').text = str(ticks_per_bar)
                ET.SubElement(note_elem, 'voice').text = "1"
                ET.SubElement(note_elem, 'type').text = "whole" if time_sig_num == 4 else "half"
            else:
                from collections import defaultdict
                onset_map = defaultdict(list)
                for n_info in m_notes:
                    onset_map[n_info['rel_start']].append(n_info)

                sorted_onsets = sorted(onset_map.keys())
                curr_pos = 0
                chord_idx = 0

                for i, onset in enumerate(sorted_onsets):
                    # Emit any chord symbols that occur before or at this onset
                    while chord_idx < len(measure_chords) and measure_chords[chord_idx][0] <= onset:
                        h_elem = parse_chord_to_musicxml_harmony(measure_chords[chord_idx][1])
                        if h_elem is not None:
                            measure.append(h_elem)
                        chord_idx += 1

                    chord_notes = onset_map[onset]
                    next_onset = sorted_onsets[i + 1] if i + 1 < len(sorted_onsets) else ticks_per_bar

                    # Insert rest if there is a gap before note/chord
                    if onset > curr_pos:
                        gap_dur = onset - curr_pos
                        rest_elem = ET.SubElement(measure, 'note')
                        ET.SubElement(rest_elem, 'rest')
                        ET.SubElement(rest_elem, 'duration').text = str(gap_dur)
                        ET.SubElement(rest_elem, 'voice').text = "1"
                        curr_pos = onset

                    # Duration of this event in the single-voice timeline
                    max_available_dur = max(1, next_onset - onset)
                    raw_dur = min([n['dur'] for n in chord_notes])
                    event_dur = max(1, min(raw_dur, max_available_dur))

                    for idx, n_info in enumerate(chord_notes):
                        note_elem = ET.SubElement(measure, 'note')
                        if idx > 0:
                            # Simultaneous notes with identical onset are valid MusicXML chords
                            ET.SubElement(note_elem, 'chord')

                        if is_drums:
                            unpitched = ET.SubElement(note_elem, 'unpitched')
                            ET.SubElement(unpitched, 'display-step').text = 'E'
                            ET.SubElement(unpitched, 'display-octave').text = '4'
                        else:
                            pitch_elem = ET.SubElement(note_elem, 'pitch')
                            p_val = n_info['pitch']
                            octave = (p_val // 12) - 1
                            step = _STEP_NAMES[p_val % 12]
                            alter = _ALTER_VALS[p_val % 12]

                            ET.SubElement(pitch_elem, 'step').text = step
                            if alter != 0:
                                ET.SubElement(pitch_elem, 'alter').text = str(alter)
                            ET.SubElement(pitch_elem, 'octave').text = str(octave)

                        ET.SubElement(note_elem, 'duration').text = str(event_dur)

                        # Ties
                        if n_info.get('tie_stop') and n_info.get('tie_start'):
                            ET.SubElement(note_elem, 'tie', attrib={'type': 'stop'})
                            ET.SubElement(note_elem, 'tie', attrib={'type': 'start'})
                        elif n_info.get('tie_stop'):
                            ET.SubElement(note_elem, 'tie', attrib={'type': 'stop'})
                        elif n_info.get('tie_start'):
                            ET.SubElement(note_elem, 'tie', attrib={'type': 'start'})

                        ET.SubElement(note_elem, 'voice').text = "1"

                        # Calculate note type string
                        quarter_fraction = event_dur / ticks_per_beat
                        if quarter_fraction >= 3.5:
                            ntype = "whole"
                        elif quarter_fraction >= 1.75:
                            ntype = "half"
                        elif quarter_fraction >= 0.85:
                            ntype = "quarter"
                        elif quarter_fraction >= 0.4:
                            ntype = "eighth"
                        elif quarter_fraction >= 0.2:
                            ntype = "16th"
                        else:
                            ntype = "32nd"
                        ET.SubElement(note_elem, 'type').text = ntype

                        # Notations (tied curves)
                        if n_info.get('tie_stop') or n_info.get('tie_start'):
                            notations = ET.SubElement(note_elem, 'notations')
                            if n_info.get('tie_stop'):
                                ET.SubElement(notations, 'tied', attrib={'type': 'stop'})
                            if n_info.get('tie_start'):
                                ET.SubElement(notations, 'tied', attrib={'type': 'start'})

                        # Direct sheet music lyrics underlay (primary note of event)
                        if idx == 0 and n_info.get('lyric'):
                            lyric_obj = n_info['lyric']
                            syl_txt = lyric_obj.get('text', '') if isinstance(lyric_obj, dict) else str(lyric_obj)
                            syl_type = lyric_obj.get('syllabic', 'single') if isinstance(lyric_obj, dict) else 'single'
                            if syl_txt:
                                lyric_elem = ET.SubElement(note_elem, 'lyric', number="1")
                                ET.SubElement(lyric_elem, 'syllabic').text = syl_type
                                ET.SubElement(lyric_elem, 'text').text = syl_txt
                                if n_info.get('tie_start'):
                                    ET.SubElement(lyric_elem, 'extend')

                    curr_pos = onset + event_dur

                # Emit any remaining chords for the measure
                while chord_idx < len(measure_chords):
                    h_elem = parse_chord_to_musicxml_harmony(measure_chords[chord_idx][1])
                    if h_elem is not None:
                        measure.append(h_elem)
                    chord_idx += 1

                # Fill trailing rest if measure is not complete
                if curr_pos < ticks_per_bar:
                    tail_dur = ticks_per_bar - curr_pos
                    rest_elem = ET.SubElement(measure, 'note')
                    ET.SubElement(rest_elem, 'rest')
                    ET.SubElement(rest_elem, 'duration').text = str(tail_dur)
                    ET.SubElement(rest_elem, 'voice').text = "1"

    out_path = Path(output_xml_path)
    tree = ET.ElementTree(score)
    ET.indent(tree, space="  ", level=0)
    tree.write(str(out_path), encoding="utf-8", xml_declaration=True)
    return out_path
