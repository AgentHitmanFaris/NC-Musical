import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import mido
import xml.etree.ElementTree as ET
from pathlib import Path
from lyrics_aligner import parse_lyrics, align_lyrics_to_notes
from musicxml_exporter import export_midi_to_musicxml
from midi_processor import postprocess_midi


def test_lyrics_parsing():
    # 1. Plain text and hyphenated syllables
    text = "In-to the light we sing"
    parsed = parse_lyrics(text)
    assert len(parsed) == 6, f"Expected 6 tokens, got {len(parsed)}: {parsed}"
    assert parsed[0]['text'] == "In" and parsed[0]['syllabic'] == 'begin'
    assert parsed[1]['text'] == "to" and parsed[1]['syllabic'] == 'end'
    assert parsed[2]['text'] == "the" and parsed[2]['syllabic'] == 'single'
    print("✓ Lyrics parsing test passed (Plain text & Syllables)")

    # 2. LRC parsing
    lrc = """
    [00:01.00] Hello world
    [00:03.50] NC-Musical
    """
    parsed_lrc = parse_lyrics(lrc)
    assert len(parsed_lrc) == 4
    assert parsed_lrc[0]['time_sec'] == 1.0
    assert parsed_lrc[2]['time_sec'] == 3.5
    print("✓ LRC lyrics parsing test passed")


def test_lyrics_underlay_in_musicxml():
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage('track_name', name="Vocals (Clean Voice 1)", time=0))
    tr.append(mido.Message('program_change', channel=0, program=54, time=0))

    # 4 notes: C4, D4, E4, F4 (each 480 ticks)
    pitches = [60, 62, 64, 65]
    for p in pitches:
        tr.append(mido.Message('note_on', channel=0, note=p, velocity=80, time=0))
        tr.append(mido.Message('note_off', channel=0, note=p, velocity=0, time=480))
    mid.tracks.append(tr)

    lyrics_sample = "Sing-ing with joy"
    processed, _, meta = postprocess_midi(
        mid,
        bpm=120.0,
        time_sig_num=4,
        time_sig_denom=4,
        key_signature='C',
        quantize=True,
        lyrics=lyrics_sample
    )

    # Verify MIDI lyrics meta messages exist
    midi_lyric_texts = []
    for t in processed.tracks:
        for msg in t:
            if msg.is_meta and msg.type == 'lyrics':
                midi_lyric_texts.append(msg.text)

    assert len(midi_lyric_texts) == 4, f"Expected 4 MIDI lyrics events, got {len(midi_lyric_texts)}: {midi_lyric_texts}"
    assert midi_lyric_texts[0].rstrip('-') == "Sing"
    assert midi_lyric_texts[1] == "ing"
    print("✓ MIDI track lyrics meta messages embedded successfully")

    # Export to MusicXML and verify XML <lyric> elements
    xml_out = Path("test_lyrics_score.musicxml")
    try:
        export_midi_to_musicxml(
            processed,
            output_xml_path=xml_out,
            title="Lyrics Test Song",
            bpm=120.0,
            time_sig_num=4,
            time_sig_denom=4,
            key_signature='C',
            lyrics=lyrics_sample
        )

        assert xml_out.exists(), "MusicXML file was not generated"
        tree = ET.parse(xml_out)
        root = tree.getroot()

        lyric_elems = root.findall('.//lyric')
        assert len(lyric_elems) >= 4, f"Expected at least 4 <lyric> elements in MusicXML, found {len(lyric_elems)}"

        words_in_xml = [el.find('text').text for el in lyric_elems if el.find('text') is not None]
        assert "Sing" in words_in_xml
        assert "ing" in words_in_xml
        assert "with" in words_in_xml
        assert "joy" in words_in_xml

        # Check syllabic markings for hyphenated word
        syl_types = [el.find('syllabic').text for el in lyric_elems if el.find('syllabic') is not None]
        assert syl_types[0] == 'begin'
        assert syl_types[1] == 'end'

        print("✓ MusicXML <lyric> note underlay test passed: Words and syllables placed directly under notes")
    finally:
        if xml_out.exists():
            xml_out.unlink()


if __name__ == "__main__":
    test_lyrics_parsing()
    test_lyrics_underlay_in_musicxml()
    print("\nALL LYRICS TESTS PASSED!")
