import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import mido
import xml.etree.ElementTree as ET
from pathlib import Path
from musicxml_exporter import export_midi_to_musicxml
from midi_processor import postprocess_midi

def test_musicxml_generation():
    mid = mido.MidiFile(ticks_per_beat=480)
    
    # 1. Vocals track
    tr_vocal = mido.MidiTrack()
    tr_vocal.append(mido.MetaMessage('track_name', name="Vocals", time=0))
    tr_vocal.append(mido.Message('program_change', channel=0, program=54, time=0))
    tr_vocal.append(mido.Message('note_on', channel=0, note=64, velocity=80, time=0))
    tr_vocal.append(mido.Message('note_off', channel=0, note=64, velocity=0, time=480))
    mid.tracks.append(tr_vocal)

    # 2. Piano track (RH & LH)
    tr_piano = mido.MidiTrack()
    tr_piano.append(mido.MetaMessage('track_name', name="Piano", time=0))
    tr_piano.append(mido.Message('program_change', channel=1, program=0, time=0))
    tr_piano.append(mido.Message('note_on', channel=1, note=67, velocity=85, time=0)) # G4 RH
    tr_piano.append(mido.Message('note_on', channel=1, note=48, velocity=75, time=0)) # C3 LH
    tr_piano.append(mido.Message('note_off', channel=1, note=67, velocity=0, time=480))
    tr_piano.append(mido.Message('note_off', channel=1, note=48, velocity=0, time=0))
    mid.tracks.append(tr_piano)

    # Post-process into clean staves (Grand Staff piano, etc.)
    processed, _, meta = postprocess_midi(mid, bpm=128.0, time_sig_num=4, time_sig_denom=4, key_signature='G', quantize=True)

    out_xml = Path("test_output.musicxml")
    try:
        export_midi_to_musicxml(processed, out_xml, title="Test Song", bpm=128.0, time_sig_num=4, time_sig_denom=4, key_signature='G')
        assert out_xml.exists(), "MusicXML file was not created"
        
        # Parse generated XML
        tree = ET.parse(out_xml)
        root = tree.getroot()
        assert root.tag == "score-partwise", f"Root tag should be score-partwise, got {root.tag}"

        parts = root.findall('part')
        assert len(parts) >= 2, f"Expected at least 2 parts (Vocals + Piano), got {len(parts)}"

        # Check for presence of G clef (Treble) and F clef (Bass)
        clefs = []
        for p in parts:
            for c in p.iter('clef'):
                sign = c.find('sign')
                if sign is not None:
                    clefs.append(sign.text)

        assert "G" in clefs, "Treble Clef (G) missing in generated MusicXML!"
        assert "F" in clefs, "Bass Clef (F) missing in generated MusicXML!"

        print("✓ MusicXML generation test passed: Valid XML structure with Treble (G) and Bass (F) clefs")
    finally:
        if out_xml.exists():
            out_xml.unlink()

if __name__ == "__main__":
    test_musicxml_generation()
    print("\nALL MUSICXML TESTS PASSED!")
