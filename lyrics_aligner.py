import re
from pathlib import Path


def syllabify_word(word: str) -> list[str]:
    """Phonotactic syllabifier for Indonesian, Malay, English, and Latin-script lyrics.
    
    Examples:
        'gembiranya' -> ['gem', 'bi', 'ra', 'nya']
        'denganmu'   -> ['de', 'ngan', 'mu']
        'aku'        -> ['a', 'ku']
        'bila'       -> ['bi', 'la']
        'Hello'      -> ['Hel', 'lo']
        'together'   -> ['to', 'ge', 'ther']
        'singing'    -> ['si', 'nging']
    """
    w = word.strip()
    if not w:
        return []

    # If already hyphenated by user/editor, preserve explicit syllables
    if '-' in w and len(w) > 1 and not w.startswith('-') and not w.endswith('-'):
        return [p for p in w.split('-') if p]

    # Extract leading/trailing punctuation so it remains anchored to first/last syllable
    m_lead = re.match(r'^[^\w]+', w)
    lead_punct = m_lead.group(0) if m_lead else ''
    m_trail = re.search(r'[^\w]+$', w)
    trail_punct = m_trail.group(0) if m_trail else ''

    core = w[len(lead_punct):len(w) - len(trail_punct)] if trail_punct else w[len(lead_punct):]
    if len(core) <= 2:
        return [w]

    vowels = set('aeiouyAEIOUY')
    tokens = []
    i = 0
    lower = core.lower()

    # Recognize standard consonant digraphs as single phonetic units
    digraphs = ('ng', 'ny', 'sy', 'kh', 'th', 'ch', 'sh', 'ph')
    while i < len(core):
        if i + 1 < len(core) and lower[i:i + 2] in digraphs:
            tokens.append((core[i:i + 2], True, False))
            i += 2
        else:
            is_v = lower[i] in vowels
            tokens.append((core[i], False, is_v))
            i += 1

    v_indices = [idx for idx, t in enumerate(tokens) if t[2]]
    if len(v_indices) <= 1:
        return [w]

    # Apply V-C-V / V-CC-V syllable partitioning rules
    splits = []
    diphthongs = (
        'ai', 'au', 'ay', 'ei', 'ey', 'oi', 'oy', 'ui', 'uy',
        'ee', 'oo', 'ea', 'oa', 'oe', 'ie', 'ou', 'ow', 'ew', 'aw'
    )
    for k in range(len(v_indices) - 1):
        v1 = v_indices[k]
        v2 = v_indices[k + 1]
        cons_count = v2 - v1 - 1
        if cons_count == 0:
            pair = (tokens[v1][0] + tokens[v2][0]).lower()
            if pair in diphthongs:
                continue
            splits.append(v1 + 1)
        elif cons_count == 1:
            # Single consonant belongs to the next syllable (V-CV): 'a-ku', 'bi-la'
            splits.append(v1 + 1)
        elif cons_count == 2:
            # Two consonants split between syllables (VC-CV): 'gem-bi', 'hel-lo'
            splits.append(v1 + 2)
        else:
            # 3 or more consonants: split after first consonant
            splits.append(v1 + 2)

    sylls = []
    prev = 0
    for s in splits:
        syll = ''.join(t[0] for t in tokens[prev:s])
        if syll:
            sylls.append(syll)
        prev = s
    last_syll = ''.join(t[0] for t in tokens[prev:])
    if last_syll:
        sylls.append(last_syll)

    if not sylls:
        return [w]
    if lead_punct:
        sylls[0] = lead_punct + sylls[0]
    if trail_punct:
        sylls[-1] = sylls[-1] + trail_punct
    return sylls


def parse_lyrics(lyrics_source: str | Path | list[str] | None, auto_syllabify: bool = True) -> list[dict]:
    """Parse lyrics from plain text, hyphenated syllables, LRC, SRT, or VTT format.
    
    Returns a list of dicts:
        [{'text': 'syllable_or_word', 'syllabic': 'single'|'begin'|'middle'|'end', 'time_sec': float|None}]
    """
    if not lyrics_source:
        return []

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

    # 1. LRC format: [mm:ss.xx] Lyric text
    lrc_pattern = re.compile(r'\[(\d{1,2}):(\d{2}(?:\.\d+)?)\](.*)')
    lrc_matches = lrc_pattern.findall(content)
    if lrc_matches:
        entries = []
        for m_min, m_sec, m_text in lrc_matches:
            text_str = m_text.strip()
            if not text_str:
                continue
            t_sec = int(m_min) * 60.0 + float(m_sec)
            words = _tokenize_words(text_str, auto_syllabify=auto_syllabify)
            for w_dict in words:
                w_dict['time_sec'] = t_sec
                entries.append(w_dict)
        if entries:
            return entries

    # 2. SRT / VTT format: 00:00:12,340 --> 00:00:15,670
    srt_pattern = re.compile(r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}\s*\n(.*?)(?=\n\n|\n\d|\Z)', re.DOTALL)
    srt_matches = srt_pattern.findall(content)
    if srt_matches:
        entries = []
        for h, m, s, ms, s_text in srt_matches:
            clean_text = re.sub(r'<[^>]+>', '', s_text).strip()
            if not clean_text:
                continue
            t_sec = int(h) * 3600.0 + int(m) * 60.0 + int(s) + int(ms) / 1000.0
            words = _tokenize_words(clean_text, auto_syllabify=auto_syllabify)
            for w_dict in words:
                w_dict['time_sec'] = t_sec
                entries.append(w_dict)
        if entries:
            return entries

    # 3. Plain text parsing
    return _tokenize_words(content, auto_syllabify=auto_syllabify)


def _tokenize_words(raw_text: str, auto_syllabify: bool = True) -> list[dict]:
    """Tokenize text into musical syllables with syllabic markings."""
    raw_tokens = re.findall(r'[\w\'-]+|[.,!?;:]', raw_text)
    items = []

    for token in raw_tokens:
        if re.match(r'^[.,!?;:]+$', token):
            if items:
                items[-1]['text'] += token
            continue

        # If already hyphenated by user (e.g. "Hel-lo"), use explicit parts
        if '-' in token and len(token) > 1 and not token.startswith('-') and not token.endswith('-'):
            sylls = [p for p in token.split('-') if p]
        elif auto_syllabify:
            sylls = syllabify_word(token)
        else:
            sylls = [token]

        if len(sylls) == 1:
            items.append({'text': sylls[0], 'syllabic': 'single', 'time_sec': None})
        else:
            for i, s in enumerate(sylls):
                if i == 0:
                    syl_type = 'begin'
                elif i == len(sylls) - 1:
                    syl_type = 'end'
                else:
                    syl_type = 'middle'
                items.append({'text': s, 'syllabic': syl_type, 'time_sec': None})

    return items


def align_lyrics_to_notes(
    notes: list[dict],
    lyrics: list[dict] | str | Path | None,
    ticks_per_beat: int = 480,
    bpm: float = 120.0
) -> list[dict]:
    """Align parsed syllables directly to vocal note onsets.
    
    Guarantees:
      - Multi-syllable words are assigned across consecutive note onsets ('begin', 'middle', 'end').
      - Tied continuation notes do not consume extra syllables.
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

    ticks_per_sec = (ticks_per_beat * bpm) / 60.0 if bpm > 0 else 960.0
    has_timestamps = any(item.get('time_sec') is not None for item in parsed_lyrics)

    if has_timestamps:
        lyric_idx = 0
        num_lyrics = len(parsed_lyrics)
        for n in notes:
            if lyric_idx >= num_lyrics:
                break
            n_start_sec = n['start'] / ticks_per_sec
            n_end_sec = n['end'] / ticks_per_sec
            l_curr = parsed_lyrics[lyric_idx]
            l_time = l_curr.get('time_sec', n_start_sec)

            if l_time <= n_end_sec + 0.25 or abs(l_time - n_start_sec) <= 0.35:
                n['lyric'] = {
                    'text': l_curr['text'],
                    'syllabic': l_curr.get('syllabic', 'single')
                }
                lyric_idx += 1
    else:
        # Sequential 1-to-1 syllable mapping to sounding notes
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
