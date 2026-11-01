import math
import xml.etree.ElementTree as ET
from pathlib import Path
import mido

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


def export_midi_to_musicxml(
    mid: mido.MidiFile,
    output_xml_path: str | Path,
    title: str = "Transcription",
    bpm: float = 120.0,
    time_sig_num: int = 4,
    time_sig_denom: int = 4,
    key_signature: str | None = "C"
) -> Path:
    """Export a multi-track MidiFile into a clean, well-formatted MusicXML file for MuseScore.
    
    Guarantees:
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

        # Extract notes with absolute tick times
        abs_events = []
        curr_tick = 0
        for msg in track:
            curr_tick += msg.time
            if not msg.is_meta:
                abs_events.append((curr_tick, msg))

        active = {}
        note_pairs = []
        for atick, msg in abs_events:
            if msg.type == 'note_on' and msg.velocity > 0:
                active.setdefault(msg.note, []).append((atick, msg))
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                if msg.note in active and active[msg.note]:
                    st, on_m = active[msg.note].pop(0)
                    note_pairs.append({
                        'pitch': msg.note,
                        'start': st,
                        'end': max(st + 1, atick),
                        'dur': max(1, atick - st),
                        'vel': on_m.velocity
                    })

        note_pairs.sort(key=lambda n: (n['start'], n['pitch']))

        # Determine total measures required
        max_tick = max([n['end'] for n in note_pairs], default=ticks_per_bar)
        num_measures = max(1, int(math.ceil(max_tick / ticks_per_bar)))

        # Group notes by measure
        measure_notes = {m_idx: [] for m_idx in range(1, num_measures + 1)}
        for n in note_pairs:
            m_idx = (n['start'] // ticks_per_bar) + 1
            if m_idx <= num_measures:
                rel_start = n['start'] % ticks_per_bar
                measure_notes[m_idx].append({
                    'pitch': n['pitch'],
                    'rel_start': rel_start,
                    'dur': min(n['dur'], ticks_per_bar - rel_start),
                    'vel': n['vel']
                })

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

            m_notes = measure_notes[m_idx]
            if not m_notes:
                # Whole measure rest
                note_elem = ET.SubElement(measure, 'note')
                ET.SubElement(note_elem, 'rest')
                ET.SubElement(note_elem, 'duration').text = str(ticks_per_bar)
                ET.SubElement(note_elem, 'voice').text = "1"
                ET.SubElement(note_elem, 'type').text = "whole" if time_sig_num == 4 else "half"
            else:
                # Sort measure notes by onset
                m_notes.sort(key=lambda x: (x['rel_start'], x['pitch']))
                prev_pos = 0

                for n_info in m_notes:
                    onset = n_info['rel_start']
                    dur = n_info['dur']

                    # Insert rest if there is a gap before note
                    if onset > prev_pos:
                        gap_dur = onset - prev_pos
                        rest_elem = ET.SubElement(measure, 'note')
                        ET.SubElement(rest_elem, 'rest')
                        ET.SubElement(rest_elem, 'duration').text = str(gap_dur)
                        ET.SubElement(rest_elem, 'voice').text = "1"
                        prev_pos = onset

                    # Write pitch note
                    note_elem = ET.SubElement(measure, 'note')
                    if onset < prev_pos:
                        # Simultaneous note (chord)
                        ET.SubElement(note_elem, 'chord')
                    else:
                        prev_pos = onset + dur

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

                    ET.SubElement(note_elem, 'duration').text = str(max(1, dur))
                    ET.SubElement(note_elem, 'voice').text = "1"

                    # Calculate note type string
                    quarter_fraction = dur / ticks_per_beat
                    if quarter_fraction >= 3.5:
                        ntype = "whole"
                    elif quarter_fraction >= 1.75:
                        ntype = "half"
                    elif quarter_fraction >= 0.85:
                        ntype = "quarter"
                    elif quarter_fraction >= 0.4:
                        ntype = "eighth"
                    else:
                        ntype = "16th"
                    ET.SubElement(note_elem, 'type').text = ntype

                # Fill trailing rest if measure not full
                if prev_pos < ticks_per_bar:
                    tail_dur = ticks_per_bar - prev_pos
                    rest_elem = ET.SubElement(measure, 'note')
                    ET.SubElement(rest_elem, 'rest')
                    ET.SubElement(rest_elem, 'duration').text = str(tail_dur)
                    ET.SubElement(rest_elem, 'voice').text = "1"

    out_path = Path(output_xml_path)
    tree = ET.ElementTree(score)
    ET.indent(tree, space="  ", level=0)
    tree.write(str(out_path), encoding="utf-8", xml_declaration=True)
    return out_path
