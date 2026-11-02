import re
from pathlib import Path


def parse_lyrics(lyrics_source: str | Path | list[str] | None) -> list[dict]:
    """Parse lyrics from plain text, hyphenated syllables, LRC, SRT, or VTT format.
    
    Returns a list of dicts:
        [{'text': 'word', 'syllabic': 'single'|'begin'|'middle'|'end', 'time_sec': float|None}]
    """
    if not lyrics_source:
        return []

    # If file path provided, read contents
    content = ""
    if isinstance(lyrics_source, Path) or (isinstance(lyrics_source, str) and (Path(lyrics_source).exists() and Path(lyrics_source).is_file())):
        try:
            content = Path(lyrics_source).read_text(encoding="utf-8")
        except Exception:
            try:
                content = Path(lyrics_source).read_text(encoding="latin-1")
            except Exception:
                content = str(lyrics_source)
    elif isinstance(lyrics_source, list):
        content = " ".join(str(s) for s in lyrics_source)
    else:
        content = str(lyrics_source)

    if not content.strip():
        return []

    # Check for LRC format: [mm:ss.xx] Lyric line
    lrc_pattern = re.compile(r'\[(\d{1,2}):(\d{2}(?:\.\d+)?)\](.*)')
    lrc_matches = lrc_pattern.findall(content)
    if lrc_matches:
        entries = []
        for m_min, m_sec, m_text in lrc_matches:
            text_str = m_text.strip()
            if not text_str:
                continue
            t_sec = int(m_min) * 60.0 + float(m_sec)
            words = _tokenize_words(text_str)
            for w_dict in words:
                w_dict['time_sec'] = t_sec
                entries.append(w_dict)
        if entries:
            return entries

    # Check for SRT / VTT format: 00:00:12,340 --> 00:00:15,670
    srt_pattern = re.compile(r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}\s*\n(.*?)(?=\n\n|\n\d|\Z)', re.DOTALL)
    srt_matches = srt_pattern.findall(content)
    if srt_matches:
        entries = []
        for h, m, s, ms, s_text in srt_matches:
            clean_text = re.sub(r'<[^>]+>', '', s_text).strip()
            if not clean_text:
                continue
            t_sec = int(h) * 3600.0 + int(m) * 60.0 + int(s) + int(ms) / 1000.0
            words = _tokenize_words(clean_text)
            for w_dict in words:
                w_dict['time_sec'] = t_sec
                entries.append(w_dict)
        if entries:
            return entries

    # Fallback: Plain text parsing with hyphenated syllable detection
    return _tokenize_words(content)


def _tokenize_words(raw_text: str) -> list[dict]:
    """Tokenize text into words and hyphenated syllables."""
    # Split text while preserving punctuation attached to words
    raw_tokens = re.findall(r'[\w\'-]+|[.,!?;:]', raw_text)
    items = []
    for token in raw_tokens:
        if re.match(r'^[.,!?;:]+$', token):
            # Attach trailing punctuation to previous token if exists
            if items:
                items[-1]['text'] += token
            continue

        # Check if token contains internal syllable hyphens (e.g. "Mu-sic-al")
        if '-' in token and len(token) > 1 and not token.startswith('-') and not token.endswith('-'):
            parts = token.split('-')
            for i, p in enumerate(parts):
                if not p:
                    continue
                if i == 0:
                    syl = 'begin'
                elif i == len(parts) - 1:
                    syl = 'end'
                else:
                    syl = 'middle'
                items.append({'text': p, 'syllabic': syl, 'time_sec': None})
        else:
            items.append({'text': token, 'syllabic': 'single', 'time_sec': None})

    return items


def align_lyrics_to_notes(
    notes: list[dict],
    lyrics: list[dict] | str | Path | None,
    ticks_per_beat: int = 480,
    bpm: float = 120.0
) -> list[dict]:
    """Align parsed lyrics directly to a list of vocal note dicts.
    
    Each note in notes gets:
        note['lyric'] = {'text': str, 'syllabic': 'single'|'begin'|'middle'|'end'}
    """
    if not notes:
        return notes

    if isinstance(lyrics, (str, Path)):
        parsed_lyrics = parse_lyrics(lyrics)
    elif isinstance(lyrics, list) and lyrics and isinstance(lyrics[0], str):
        parsed_lyrics = parse_lyrics(" ".join(lyrics))
    elif isinstance(lyrics, list):
        parsed_lyrics = lyrics
    else:
        parsed_lyrics = []

    if not parsed_lyrics:
        return notes

    # Check if lyrics have timestamp references
    has_timestamps = any(item.get('time_sec') is not None for item in parsed_lyrics)

    ticks_per_sec = (ticks_per_beat * bpm) / 60.0 if bpm > 0 else 960.0

    if has_timestamps:
        # Timestamp-guided alignment: match each lyric token to the closest vocal note onset
        lyric_idx = 0
        num_lyrics = len(parsed_lyrics)

        for n in notes:
            if lyric_idx >= num_lyrics:
                break
            n_start_sec = n['start'] / ticks_per_sec
            n_end_sec = n['end'] / ticks_per_sec

            # Look for best lyric match around note onset
            l_curr = parsed_lyrics[lyric_idx]
            l_time = l_curr.get('time_sec', n_start_sec)

            # If lyric timestamp is within reasonable proximity of this note
            if l_time <= n_end_sec + 0.25:
                n['lyric'] = {
                    'text': l_curr['text'],
                    'syllabic': l_curr.get('syllabic', 'single')
                }
                lyric_idx += 1
            elif abs(l_time - n_start_sec) <= 0.35:
                n['lyric'] = {
                    'text': l_curr['text'],
                    'syllabic': l_curr.get('syllabic', 'single')
                }
                lyric_idx += 1
    else:
        # Sequential alignment: map each lyric word/syllable 1-to-1 to each vocal note
        num_lyrics = len(parsed_lyrics)
        for i, n in enumerate(notes):
            if i < num_lyrics:
                n['lyric'] = {
                    'text': parsed_lyrics[i]['text'],
                    'syllabic': parsed_lyrics[i].get('syllabic', 'single')
                }
            else:
                break

    return notes
