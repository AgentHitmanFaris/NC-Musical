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


if __name__ == "__main__":
    test_key_signature_detection()
    test_time_signature_and_tempo_embedding()
    test_quantization_no_tuplets()
    print("\nALL MIDI PROCESSOR TESTS PASSED!")
