import os
import sys
from pathlib import Path

def patch_file(file_path: Path, target_content: str, replacement_content: str):
    if not file_path.exists():
        print(f"Error: File {file_path} not found. Cannot patch.")
        return False
        
    content = file_path.read_text(encoding="utf-8")
    if target_content in content:
        new_content = content.replace(target_content, replacement_content)
        file_path.write_text(new_content, encoding="utf-8")
        print(f"Successfully patched: {file_path.name}")
        return True
    elif replacement_content in content:
        print(f"Already patched: {file_path.name}")
        return True
    else:
        print(f"Warning: Could not find target content in {file_path.name}. It may have been modified.")
        return False

def main():
    muscriptor_dir = None
    try:
        import muscriptor
        muscriptor_dir = Path(muscriptor.__file__).parent
        print(f"Located muscriptor package at: {muscriptor_dir}")
    except ImportError:
        # Fallback search for venv or site-packages
        workspace = Path(__file__).parent
        candidates = list(workspace.glob("venv/**/muscriptor"))
        if candidates:
            muscriptor_dir = candidates[0]
            print(f"Located muscriptor package in venv at: {muscriptor_dir}")

    if not muscriptor_dir or not muscriptor_dir.exists():
        print("Notice: 'muscriptor' package is not installed yet. Skipping patch.")
        return

    # Patch auralization.py
    auralization_path = muscriptor_dir / "utils" / "auralization.py"
    target_aur = """# Pre-downloaded copy at the repo root (kept for checkouts and Docker images
# that already have one); absent that, the soundfont is fetched from SF2_URL
# and cached under ~/.cache/muscriptor/.
_LOCAL_SOUNDFONT = Path(__file__).parent.parent.parent / "MuseScore_General.sf2"
_SAMPLE_RATE = 44100


def _load_mono_44k(path: Path) -> np.ndarray:
    \"\"\"Return a mono float32 numpy array at 44100 Hz for any audio file.\"\"\"
    wav = load_audio(str(path), target_sr=_SAMPLE_RATE)  # [1, T]
    return wav[0].numpy()


def _resolve_soundfont(soundfont_path: str | Path | None) -> Path:
    if soundfont_path is None:
        if _LOCAL_SOUNDFONT.exists():
            return _LOCAL_SOUNDFONT
        return download_if_necessary(SF2_URL)
    soundfont_path = Path(soundfont_path)
    if not soundfont_path.exists():
        raise FileNotFoundError(
            f"SoundFont not found: {soundfont_path}\\n"
            "Pass --soundfont /path/to/file.sf2, or omit it to use "
            "MuseScore_General.sf2 (downloaded once and cached)."
        )
    return soundfont_path"""

    replacement_aur = """# Point local soundfont to workspace root's MS Basic.sf3
_WORKSPACE_DIR = Path(__file__).parent.parent.parent.parent.parent.parent
_LOCAL_SOUNDFONT = _WORKSPACE_DIR / "MS Basic.sf3"
_SAMPLE_RATE = 44100


def _load_mono_44k(path: Path) -> np.ndarray:
    \"\"\"Return a mono float32 numpy array at 44100 Hz for any audio file.\"\"\"
    wav = load_audio(str(path), target_sr=_SAMPLE_RATE)  # [1, T]
    return wav[0].numpy()


def _resolve_soundfont(soundfont_path: str | Path | None) -> Path:
    # Prepend dynamic fluidsynth binary directory to system PATH if on Windows
    fs_bin = r"D:\\Document\\NC-Project\\sheetsage\\AtoScore_Core\\bin"
    if os.name == "nt" and fs_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = fs_bin + os.path.pathsep + os.environ.get("PATH", "")

    if soundfont_path is None:
        if _LOCAL_SOUNDFONT.exists():
            return _LOCAL_SOUNDFONT
            
        # Check alternative common paths for MS Basic.sf3
        alt_paths = [
            Path("D:/Program Files/MuseScore 4/sound/MS Basic.sf3"),
            Path("C:/Program Files/MuseScore 4/sound/MS Basic.sf3"),
            Path("D:/Document/MuseScore/share/sound/MS Basic.sf3"),
            Path("D:/Document/NC-Research/Music/MS Basic.sf3"),
            Path("/content/NC-Musical/MS Basic.sf3"),
            Path("/content/drive/MyDrive/NC-Musical-Models/MS Basic.sf3"),
        ]
        for path in alt_paths:
            if path.exists():
                return path
                
        # If not found anywhere, fallback to download
        return download_if_necessary(SF2_URL)

    soundfont_path = Path(soundfont_path)
    if not soundfont_path.exists():
        raise FileNotFoundError(
            f"SoundFont not found: {soundfont_path}\\n"
            "Place MS Basic.sf3 in the workspace root or specify a valid file."
        )
    return soundfont_path"""

    patch_file(auralization_path, target_aur, replacement_aur)

    # Patch server.py
    server_path = muscriptor_dir / "server.py"
    target_server = """    @app.get("/soundfonts/MuseScore_General.sf3")
    async def soundfont() -> FileResponse:
        \"\"\"Compressed soundfont for the web UI's in-browser synthesizer.

        Fetched from SF3_URL on first request (in a worker thread, so the
        event loop keeps serving) and cached locally.
        \"\"\"
        path = await asyncio.to_thread(download_if_necessary, SF3_URL)
        return FileResponse(path, media_type="application/octet-stream")"""

    replacement_server = """    @app.get("/soundfonts/MuseScore_General.sf3")
    async def soundfont() -> FileResponse:
        \"\"\"Compressed soundfont for the web UI's in-browser synthesizer.

        Returns MS Basic.sf3 from the local workspace or installation.
        \"\"\"
        workspace_dir = Path(__file__).parent.parent.parent.parent
        sf3_path = workspace_dir / "MS Basic.sf3"
        if not sf3_path.exists():
            fallbacks = [
                Path("D:/Program Files/MuseScore 4/sound/MS Basic.sf3"),
                Path("C:/Program Files/MuseScore 4/sound/MS Basic.sf3"),
                Path("D:/Document/MuseScore/share/sound/MS Basic.sf3"),
                Path("D:/Document/NC-Research/Music/MS Basic.sf3"),
                Path("/content/NC-Musical/MS Basic.sf3"),
                Path("/content/drive/MyDrive/NC-Musical-Models/MS Basic.sf3"),
            ]
            for fb in fallbacks:
                if fb.exists():
                    sf3_path = fb
                    break
        
        if sf3_path.exists():
            return FileResponse(sf3_path, media_type="application/octet-stream")

        path = await asyncio.to_thread(download_if_necessary, SF3_URL)
        return FileResponse(path, media_type="application/octet-stream")"""

    patch_file(server_path, target_server, replacement_server)

    # Patch tokenizer/mt3.py for instrument alias resolution
    mt3_path = muscriptor_dir / "tokenizer" / "mt3.py"
    target_mt3 = """def instrument_group_from_names(names: Iterable[str]) -> str:
    \"\"\"Map exact instrument group names to the model's conditioning string.

    The strict counterpart of :func:`resolve_instrument_names`: every name
    must appear verbatim in ``MT3_FULL_PLUS_GROUP_NAMES``. Raises ValueError
    listing the unknown names otherwise.
    \"\"\"
    names = list(names)
    unknown = [n for n in names if n not in MT3_FULL_PLUS_GROUP_NAMES]
    if unknown:
        raise ValueError(
            f"unknown instrument name(s): {', '.join(map(repr, unknown))}; "
            f"valid names: {', '.join(MT3_FULL_PLUS_GROUP_NAMES)}"
        )
    return " ".join(str(MT3_FULL_PLUS_GROUP_NAMES[n]) for n in names)"""

    replacement_mt3 = """_INSTRUMENT_ALIASES = {
    "piano": "acoustic_piano",
    "guitar": "acoustic_guitar",
    "electric_guitar": "clean_electric_guitar",
    "bass": "electric_bass",
    "drums": "drums",
    "drum": "drums",
    "percussion": "drums",
    "strings": "string_ensemble",
    "brass": "brass_section",
    "sax": "soprano_and_alto_sax",
    "saxophone": "soprano_and_alto_sax",
    "flute": "flutes",
    "synth": "synth_lead",
    "pad": "synth_pad",
    "vocal": "voice",
    "vocals": "voice",
}

def instrument_group_from_names(names: Iterable[str]) -> str:
    \"\"\"Map instrument names or shorthand aliases to conditioning string.\"\"\"
    resolved_names = []
    for n in names:
        key = n.strip().lower()
        if key in MT3_FULL_PLUS_GROUP_NAMES:
            resolved_names.append(key)
        elif key in _INSTRUMENT_ALIASES:
            resolved_names.append(_INSTRUMENT_ALIASES[key])
        else:
            matched = False
            for target_name in MT3_FULL_PLUS_GROUP_NAMES:
                if key in target_name:
                    resolved_names.append(target_name)
                    matched = True
                    break
            if not matched:
                resolved_names.append(n)

    unknown = [n for n in resolved_names if n not in MT3_FULL_PLUS_GROUP_NAMES]
    if unknown:
        raise ValueError(
            f"unknown instrument name(s): {', '.join(map(repr, unknown))}; "
            f"valid names: {', '.join(MT3_FULL_PLUS_GROUP_NAMES)}"
        )
    return " ".join(str(MT3_FULL_PLUS_GROUP_NAMES[n]) for n in resolved_names)"""

    patch_file(mt3_path, target_mt3, replacement_mt3)

if __name__ == "__main__":
    main()
