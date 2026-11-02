import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import mido
import midi_processor

def test_key_signature_detection():
    # Construct G Major triad
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    # G4 (67), B4 (71), D5 (74)
    tr.append(mido.Message('note_on', note=67, velocity=80, time=0))
    tr.append(mido.Message('note_off', note=67, velocity=0, time=480))
    tr.append(mido.Message('note_on', note=71, velocity=80, time=0))
    tr.append(mido.Message('note_off', note=71, velocity=0, time=480))
    tr.append(mido.Message('note_on', note=74, velocity=80, time=0))
    tr.append(mido.Message('note_off', note=74, velocity=0, time=480))

    key = midi_processor.detect_key_signature_from_midi(mid)
    assert key == 'G', f"Expected key G, got {key}"
    print("✓ Key signature detection test passed: G Major")


def test_time_signature_and_tempo_embedding():
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.Message('note_on', note=60, velocity=64, time=0))
    tr.append(mido.Message('note_off', note=60, velocity=0, time=480))

    processed, out_bytes, meta = midi_processor.postprocess_midi(
        mid,
        bpm=140.0,
        time_sig_num=3,
        time_sig_denom=4,
        key_signature='F',
        quantize=False
    )

    # Verify track 0 meta messages
    time_sig_found = False
    key_sig_found = False
    tempo_found = False

    for msg in processed.tracks[0]:
        if msg.type == 'time_signature' and msg.numerator == 3 and msg.denominator == 4:
            time_sig_found = True
        elif msg.type == 'key_signature' and msg.key == 'F':
            key_sig_found = True
        elif msg.type == 'set_tempo' and msg.tempo == mido.bpm2tempo(140.0):
            tempo_found = True

    assert time_sig_found, "Time signature 3/4 not embedded properly"
    assert key_sig_found, "Key signature F not embedded properly"
    assert tempo_found, "Tempo 140 BPM not embedded properly"
    print("✓ Time signature (3/4), Key (F), and Tempo (140 BPM) embedding test passed")


def test_quantization_no_tuplets():
    # Irregular onset jitter notes
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    # Jittered onsets: tick 9, 131, 237
    tr.append(mido.Message('note_on', note=60, velocity=80, time=9))
    tr.append(mido.Message('note_off', note=60, velocity=0, time=110))
    tr.append(mido.Message('note_on', note=62, velocity=80, time=12))
    tr.append(mido.Message('note_off', note=62, velocity=0, time=122))

    processed, out_bytes, meta = midi_processor.postprocess_midi(
        mid,
        bpm=120.0,
        time_sig_num=4,
        time_sig_denom=4,
        key_signature='C',
        quantize=True,
        grid_div=4, # 1/16 notes = 120 ticks
        quantize_strength=1.0,
        fill_gaps_beats=0.25
    )

    curr = 0
    onsets = []
    for msg in processed.tracks[0]:
        curr += msg.time
        if msg.type == 'note_on' and msg.velocity > 0:
            onsets.append(curr)

    # 120 ticks per 16th note -> onsets should be multiples of 120 (0, 120, etc.)
    for onset in onsets:
        assert onset % 120 == 0, f"Onset {onset} is not snapped to 120-tick 16th grid (No Tuplets violated)"

    assert meta['no_tuplets'] is True
    print("✓ Quantization with 'No Tuplets' (1/16 sixteenth grid) test passed")


def test_single_voice_monophonic_resolution():
    """Verify that overlapping vocal syllables and chord bleeds are strictly reduced to 1 clean voice."""
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)

    # Note 1: C4 (tick 0 to 480)
    tr.append(mido.Message('note_on', note=60, velocity=80, time=0))
    # Note 1b (Ghost bleed/chord at tick 0 with lower velocity): E4
    tr.append(mido.Message('note_on', note=64, velocity=40, time=0))
    # Note 2 starts at tick 240 (BEFORE Note 1 ends! Overlap = Moonlight Sonata dual voice bug)
    tr.append(mido.Message('note_on', note=67, velocity=90, time=240))
    # Note 1 off arrives at tick 240 delta (abs 480)
    tr.append(mido.Message('note_off', note=60, velocity=0, time=240))
    tr.append(mido.Message('note_off', note=64, velocity=0, time=0))
    # Note 2 off arrives at tick 480 delta (abs 960)
    tr.append(mido.Message('note_off', note=67, velocity=0, time=480))

    processed, out_bytes, meta = midi_processor.postprocess_midi(
        mid,
        bpm=120.0,
        time_sig_num=4,
        time_sig_denom=4,
        key_signature='C',
        quantize=True,
        grid_div=4,
        single_voice=True
    )

    # Inspect all notes in processed tracks
    for t in processed.tracks:
        active = {}
        curr = 0
        notes = []
        for msg in t:
            curr += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                active[msg.note] = curr
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                if msg.note in active:
                    start = active.pop(msg.note)
                    notes.append({'pitch': msg.note, 'start': start, 'end': curr})

        notes.sort(key=lambda x: x['start'])
        # Verify strictly NO overlaps (pure Voice 1, no MuseScore 2-voicing)
        for i in range(len(notes) - 1):
            cur_n = notes[i]
            next_n = notes[i + 1]
            assert cur_n['end'] <= next_n['start'], (
                f"Overlap detected: Note {cur_n['pitch']} ({cur_n['start']}..{cur_n['end']}) "
                f"overlaps next note {next_n['pitch']} ({next_n['start']}..{next_n['end']})!"
            )

    print("✓ Single-voice monophonic resolution test passed: Zero overlaps, clean Voice 1 guaranteed")


def test_channel_separation_to_tracks():
    """Verify that multi-channel events in a single track are separated into individual staves."""
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)

    # Channel 0 (Vocal)
    tr.append(mido.Message('note_on', channel=0, note=60, velocity=80, time=0))
    # Channel 1 (Piano)
    tr.append(mido.Message('note_on', channel=1, note=48, velocity=70, time=0))
    tr.append(mido.Message('note_off', channel=0, note=60, velocity=0, time=480))
    tr.append(mido.Message('note_off', channel=1, note=48, velocity=0, time=0))

    separated = midi_processor.separate_multichannel_tracks(mid)
    # Should have Tempo track + Channel 0 track + Channel 1 track
    assert len(separated.tracks) >= 3, f"Expected at least 3 tracks, got {len(separated.tracks)}"
    print("✓ Channel separation test passed: Multi-channel streams split into dedicated staves")


def test_time_signature_auto_detection():
    """Verify auto-detection of time signature (e.g. 3/4 waltz vs 4/4 common time)."""
    # Create 3/4 waltz onsets (every 3 beats: ticks 0, 1440, 2880, 4320...)
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)

    for i in range(16):
        # Downbeat on beat 0 of every 3-beat measure
        tr.append(mido.Message('note_on', note=60, velocity=80, time=0 if i == 0 else 1440))
        tr.append(mido.Message('note_off', note=60, velocity=0, time=240))

    detected_num, detected_denom = midi_processor.detect_time_signature_from_midi(mid)
    assert detected_num == 3 and detected_denom == 4, f"Expected 3/4, got {detected_num}/{detected_denom}"
    print("✓ Time signature auto-detection test passed: 3/4 waltz meter")


def test_piano_grand_staff_and_polyphony():
    """Verify that Piano generates a complete Grand Staff (Treble + Bass clefs) with full polyphony."""
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage('track_name', name="Piano", time=0))
    tr.append(mido.Message('program_change', channel=1, program=0, time=0))
    mid.tracks.append(tr)

    # RH Chord: C4 (60), E4 (64), G4 (67)
    tr.append(mido.Message('note_on', channel=1, note=60, velocity=80, time=0))
    tr.append(mido.Message('note_on', channel=1, note=64, velocity=80, time=0))
    tr.append(mido.Message('note_on', channel=1, note=67, velocity=80, time=0))
    # LH Bass: C3 (48), G2 (43)
    tr.append(mido.Message('note_on', channel=1, note=48, velocity=75, time=0))
    tr.append(mido.Message('note_on', channel=1, note=43, velocity=70, time=0))

    tr.append(mido.Message('note_off', channel=1, note=60, velocity=0, time=480))
    tr.append(mido.Message('note_off', channel=1, note=64, velocity=0, time=0))
    tr.append(mido.Message('note_off', channel=1, note=67, velocity=0, time=0))
    tr.append(mido.Message('note_off', channel=1, note=48, velocity=0, time=0))
    tr.append(mido.Message('note_off', channel=1, note=43, velocity=0, time=0))

    processed, out_bytes, meta = midi_processor.postprocess_midi(mid, quantize=True, single_voice=True)

    rh_track = None
    lh_track = None
    for t in processed.tracks:
        for msg in t:
            if msg.is_meta and msg.type == 'track_name':
                if "Right Hand - Treble Clef" in msg.name:
                    rh_track = t
                elif "Left Hand - Bass Clef" in msg.name:
                    lh_track = t

    assert rh_track is not None, "Piano Right Hand (Treble Clef) track missing!"
    assert lh_track is not None, "Piano Left Hand (Bass Clef) track missing!"

    # Verify RH polyphonic chord (3 notes) and LH polyphonic bass (2 notes)
    rh_notes = [m.note for m in rh_track if m.type == 'note_on' and m.velocity > 0]
    lh_notes = [m.note for m in lh_track if m.type == 'note_on' and m.velocity > 0]

    assert len(rh_notes) == 3, f"Expected 3 RH notes, got {len(rh_notes)}"
    assert len(lh_notes) == 2, f"Expected 2 LH notes, got {len(lh_notes)}"
    assert all(p >= 60 for p in rh_notes), "RH notes must be >= Middle C (60) for Treble Clef"
    assert all(p < 60 for p in lh_notes), "LH notes must be < Middle C (60) for Bass Clef"

    print("✓ Full Piano Grand Staff test passed: Treble & Bass staves with full chords intact")


def test_drums_full_kit_polyphony():
    """Verify that Drums retain simultaneous hits (Kick, Snare, Hi-Hat) without monophonic pruning."""
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage('track_name', name="Drums", time=0))
    mid.tracks.append(tr)

    # Simultaneous Kick (36) and Closed Hat (42)
    tr.append(mido.Message('note_on', channel=9, note=36, velocity=95, time=0))
    tr.append(mido.Message('note_on', channel=9, note=42, velocity=85, time=0))
    tr.append(mido.Message('note_off', channel=9, note=36, velocity=0, time=120))
    tr.append(mido.Message('note_off', channel=9, note=42, velocity=0, time=0))

    processed, out_bytes, meta = midi_processor.postprocess_midi(mid, quantize=True, single_voice=True)

    drum_track = None
    for t in processed.tracks:
        for msg in t:
            if msg.is_meta and msg.type == 'track_name' and "Drums" in msg.name:
                drum_track = t

    assert drum_track is not None, "Drum track missing!"
    drum_notes = [m.note for m in drum_track if m.type == 'note_on' and m.velocity > 0]
    assert 36 in drum_notes and 42 in drum_notes, "Both Kick and Hi-Hat must be preserved simultaneously in Drums!"
    print("✓ Full Drums polyphony test passed: Multi-percussion hits preserved")


def test_guitar_clean_and_distortion_separation():
    """Verify that Distorted Guitar, Clean Guitar, and Electric Bass are separated into distinct staves."""
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)

    # Clean Guitar (prog 27)
    tr.append(mido.Message('program_change', channel=3, program=27, time=0))
    tr.append(mido.Message('note_on', channel=3, note=64, velocity=80, time=0))
    tr.append(mido.Message('note_off', channel=3, note=64, velocity=0, time=240))

    # Distorted Guitar (prog 29)
    tr.append(mido.Message('program_change', channel=4, program=29, time=0))
    tr.append(mido.Message('note_on', channel=4, note=65, velocity=85, time=0))
    tr.append(mido.Message('note_off', channel=4, note=65, velocity=0, time=240))

    # Electric Bass (prog 33)
    tr.append(mido.Message('program_change', channel=5, program=33, time=0))
    tr.append(mido.Message('note_on', channel=5, note=40, velocity=90, time=0))
    tr.append(mido.Message('note_off', channel=5, note=40, velocity=0, time=240))

    processed, out_bytes, meta = midi_processor.postprocess_midi(mid, quantize=True, single_voice=True)

    track_titles = []
    for t in processed.tracks:
        for msg in t:
            if msg.is_meta and msg.type == 'track_name':
                track_titles.append(msg.name)

    assert any("Clean Electric Guitar" in name for name in track_titles), "Clean Electric Guitar track missing!"
    assert any("Distorted Electric Guitar" in name for name in track_titles), "Distorted Electric Guitar track missing!"
    assert any("Electric Bass" in name for name in track_titles), "Electric Bass track missing!"

    print("✓ Guitar & Bass separation test passed: Distortion, Clean, and Bass isolated onto distinct staves")


def test_restricted_triplets_quantization():
    """Verify restricted triplets: binary grid is priority, genuine triplets captured without forcing binary notes."""
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)

    # Note 1: Straight 16th note at tick 120 (dur: 120)
    # Note 2: Jittered straight note at tick 248 (near straight 8th at 240, dur: 110)
    # Note 3: Genuine triplet note at tick 640 (480 + 160: 8th triplet on beat 2, dur: 160)
    tr.append(mido.Message('note_on', note=60, velocity=80, time=120))
    tr.append(mido.Message('note_off', note=60, velocity=0, time=120))
    tr.append(mido.Message('note_on', note=62, velocity=80, time=8)) # absolute 248
    tr.append(mido.Message('note_off', note=62, velocity=0, time=110)) # absolute 358
    tr.append(mido.Message('note_on', note=64, velocity=80, time=282)) # absolute 640
    tr.append(mido.Message('note_off', note=64, velocity=0, time=160)) # absolute 800

    # Pass 1: With restricted_triplets=True
    processed_rt, _, meta_rt = midi_processor.postprocess_midi(
        mid,
        quantize=True,
        grid_div=4,
        restricted_triplets=True,
        single_voice=False,
        separate_channels=False
    )

    onsets_rt = []
    curr = 0
    for msg in processed_rt.tracks[0]:
        curr += msg.time
        if msg.type == 'note_on' and msg.velocity > 0:
            onsets_rt.append(curr)

    assert onsets_rt[0] == 120, f"Straight 16th note expected at 120, got {onsets_rt[0]}"
    assert onsets_rt[1] == 240, f"Jittered 248 note expected at binary priority 240, got {onsets_rt[1]}"
    assert onsets_rt[2] == 640, f"Genuine triplet note at 640 expected at triplet 640, got {onsets_rt[2]}"
    assert meta_rt['restricted_triplets'] is True

    # Pass 2: With restricted_triplets=False (straight binary only)
    processed_no_rt, _, meta_no_rt = midi_processor.postprocess_midi(
        mid,
        quantize=True,
        grid_div=4,
        restricted_triplets=False,
        single_voice=False,
        separate_channels=False
    )

    onsets_no_rt = []
    curr = 0
    for msg in processed_no_rt.tracks[0]:
        curr += msg.time
        if msg.type == 'note_on' and msg.velocity > 0:
            onsets_no_rt.append(curr)

    assert onsets_no_rt[0] == 120
    assert onsets_no_rt[1] == 240
    # Tick 640 in straight 120-tick grid: 640 / 120 = 5.333 -> snaps to 600
    assert onsets_no_rt[2] % 120 == 0, f"Expected straight binary grid multiple, got {onsets_no_rt[2]}"
    assert onsets_no_rt[2] == 600

    print("✓ Restricted triplets quantization test passed: Binary priority preserved and genuine triplets snapped")


if __name__ == "__main__":
    test_key_signature_detection()
    test_time_signature_and_tempo_embedding()
    test_time_signature_auto_detection()
    test_quantization_no_tuplets()
    test_restricted_triplets_quantization()
    test_single_voice_monophonic_resolution()
    test_channel_separation_to_tracks()
    test_piano_grand_staff_and_polyphony()
    test_drums_full_kit_polyphony()
    test_guitar_clean_and_distortion_separation()
    print("\nALL MIDI PROCESSOR TESTS PASSED!")
