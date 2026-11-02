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

    # 2. LRC parsing (with phonotactic syllable split)
    lrc = """
    [00:01.00] Hello world
    [00:03.50] NC-Musical
    """
    parsed_lrc = parse_lyrics(lrc)
    assert len(parsed_lrc) == 5, f"Expected 5 syllables, got {len(parsed_lrc)}: {parsed_lrc}"
    assert parsed_lrc[0]['text'] == 'Hel' and parsed_lrc[0]['time_sec'] == 1.0
    assert parsed_lrc[1]['text'] == 'lo' and parsed_lrc[1]['time_sec'] == 1.0
    assert parsed_lrc[2]['text'] == 'world' and parsed_lrc[2]['time_sec'] == 1.0
    print("✓ LRC lyrics parsing test passed")

    # 3. Indonesian / Malay phonotactic syllabifier test (Image benchmark)
    indonesian_phrase = "Hello hello gembiranya aku bila denganmu"
    indo_sylls = parse_lyrics(indonesian_phrase)
    syll_texts = [s['text'] for s in indo_sylls]
    expected_sylls = ['Hel', 'lo', 'hel', 'lo', 'gem', 'bi', 'ra', 'nya', 'a', 'ku', 'bi', 'la', 'de', 'ngan', 'mu']
    assert syll_texts == expected_sylls, f"Expected {expected_sylls}, got {syll_texts}"
    assert len(indo_sylls) == 15
    print("✓ Indonesian/Malay lyrics syllabification benchmark test passed: 15/15 syllables match sheet music")


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


def test_score_image_benchmark_with_ties_and_chords():
    """Benchmark test modeling the user's uploaded sheet music:
    - 4/4 meter, Eb Major, 195 BPM
    - Chords: Ebmaj7, Cm7, Fm7, Bb7
    - Lyrics: 'Hel-lo hel-lo gem-bi-ra-nya a-ku bi-la de-ngan-mu'
    - Notes tied across barlines (m2->m3 'nya', m3->m4 'la')
    """
    mid = mido.MidiFile(ticks_per_beat=480)
    ticks_per_bar = 480 * 4 # 1920

    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage('track_name', name="Vocals", time=0))

    # Notes matching the user's image:
    # m1: rest(720 ticks), Eb4 (240 ticks 'Hel'), G4 (480 ticks 'lo'), F4 (480 ticks 'hel')
    # m2: Eb4 (240 ticks 'lo'), G4 (480 ticks 'gem'), Bb4 (240 ticks 'bi'), C5 (240 ticks 'ra'),
    #     Bb4 (starts at 1920 + 1200 = 3120, dur = 960 ticks, ends in m3 at 4080 -> 'nya')
    # m3: tied 'nya' stops at 4080 (rel 240). Then G4 (240 ticks 'a'), F4 (240 ticks 'ku'),
    #     Eb4 (480 ticks 'bi'), F4 (starts at 3840 + 1440 = 5280, dur = 480, ends in m4 at 5760 + 240 = 6000 -> 'la')
    # m4: tied 'la' stops at 6000 (rel 240). Then G4 (240 ticks 'de'), F4 (240 ticks 'ngan'), Eb4 (480 ticks 'mu')
    events = [
        # Measure 1
        (720, 960, 63),   # Hel
        (960, 1440, 67),  # lo
        (1440, 1920, 65), # hel
        # Measure 2
        (1920, 2160, 63), # lo
        (2160, 2640, 67), # gem
        (2640, 2880, 70), # bi
        (2880, 3120, 72), # ra
        (3120, 4080, 70), # nya (crosses barline into m3!)
        # Measure 3
        (4080, 4320, 67), # a
        (4320, 4560, 65), # ku
        (4560, 5040, 63), # bi
        (5040, 5760 + 240, 65), # la (crosses barline into m4!)
        # Measure 4
        (6000, 6240, 67), # de
        (6240, 6480, 65), # ngan
        (6480, 6960, 63), # mu
    ]

    abs_events = []
    for st, et, p in events:
        abs_events.append((st, 'note_on', p, 80))
        abs_events.append((et, 'note_off', p, 0))
    abs_events.sort(key=lambda x: (x[0], 0 if x[1] == 'note_off' else 1))

    cur_t = 0
    for at, etype, p, vel in abs_events:
        delta = at - cur_t
        tr.append(mido.Message(etype, channel=0, note=p, velocity=vel, time=delta))
        cur_t = at
    mid.tracks.append(tr)

    lyrics_text = "Hel-lo hel-lo gem-bi-ra-nya a-ku bi-la de-ngan-mu"
    chords_score = ["", "Ebmaj7", "Cm7", "Fm7 Bb7"]

    out_xml = Path("test_score_benchmark.musicxml")
    try:
        export_midi_to_musicxml(
            mid,
            output_xml_path=out_xml,
            title="Benchmark Hello Score",
            bpm=195.0,
            time_sig_num=4,
            time_sig_denom=4,
            key_signature="Eb",
            lyrics=lyrics_text,
            chords=chords_score
        )
        assert out_xml.exists(), "Benchmark MusicXML file was not generated"

        tree = ET.parse(out_xml)
        root = tree.getroot()

        # 1. Verify chords / harmony
        harmonies = root.findall('.//harmony')
        assert len(harmonies) == 4, f"Expected 4 harmony elements, found {len(harmonies)}"
        chord_texts = [h.find('kind').get('text') for h in harmonies if h.find('kind') is not None]
        assert "Ebmaj7" in chord_texts
        assert "Cm7" in chord_texts
        assert "Fm7" in chord_texts
        assert "Bb7" in chord_texts
        print("✓ Sheet music chord symbols verified: Ebmaj7, Cm7, Fm7, Bb7 rendered correctly above measures")

        # 2. Verify ties across barlines
        ties = root.findall('.//tie')
        assert len(ties) >= 4, f"Expected at least 4 <tie> elements for crossed notes, found {len(ties)}"
        tied_notations = root.findall('.//notations/tied')
        assert len(tied_notations) >= 4, f"Expected at least 4 <tied> notations, found {len(tied_notations)}"
        print("✓ Barline-crossing note ties verified: <tie> and <tied> notations hold syllables across measures")

        # 3. Verify syllables underlay
        lyric_elems = root.findall('.//lyric')
        assert len(lyric_elems) == 15, f"Expected exactly 15 syllables under notes, found {len(lyric_elems)}"
        lyrics_found = [el.find('text').text for el in lyric_elems if el.find('text') is not None]
        expected_lyrics = ['Hel', 'lo', 'hel', 'lo', 'gem', 'bi', 'ra', 'nya', 'a', 'ku', 'bi', 'la', 'de', 'ngan', 'mu']
        assert lyrics_found == expected_lyrics, f"Lyrics mismatch: {lyrics_found} vs {expected_lyrics}"
        print("✓ Exact 1:1 Syllable note underlay verified matching sheet music image perfectly")

    finally:
        if out_xml.exists():
            out_xml.unlink()


if __name__ == "__main__":
    test_lyrics_parsing()
    test_lyrics_underlay_in_musicxml()
    test_score_image_benchmark_with_ties_and_chords()
    print("\nALL LYRICS TESTS PASSED!")
