import os
import sys
import argparse
import torch
from pathlib import Path

try:
    from midi_processor import postprocess_midi, parse_time_signature_string
except ImportError:
    # Fallback to local import
    sys.path.insert(0, str(Path(__file__).parent))
    from midi_processor import postprocess_midi, parse_time_signature_string


def main():
    parser = argparse.ArgumentParser(
        description="NC-Musical CLI: High-Performance AI Music Transcription with Timing, Key Signature & Quantization",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Positional or optional audio input
    parser.add_argument("audio_path", nargs="?", help="Path to input audio file (WAV, MP3, FLAC, M4A, etc.)")
    parser.add_argument("pos_model_size", nargs="?", default=None, help="Legacy positional model size [small, medium, large]")
    parser.add_argument("pos_output", nargs="?", default=None, help="Legacy positional output MIDI path")

    # Flag options
    parser.add_argument("-m", "--model-size", default="large", choices=["small", "medium", "large"], help="MuScriptor model size")
    parser.add_argument("-o", "--output", default="output.mid", help="Output MIDI file path")
    parser.add_argument("--bpm", type=float, default=120.0, help="Tempo in beats per minute")
    parser.add_argument("--beat-scale", type=float, default=1.0, help="Scale tempo factor (e.g. 0.5 for half-time, 2.0 for double-time)")
    parser.add_argument("--time-signature", "--time-sig", default="4/4", help="Time signature (e.g. 4/4, 3/4, 6/8, 12/8, 5/4)")
    parser.add_argument("--beats-per-bar", type=int, default=None, help="Numerator of time signature (overrides time-signature)")
    parser.add_argument("--time-sig-denom", type=int, default=None, help="Denominator of time signature (overrides time-signature)")
    parser.add_argument("--key-signature", "--key", default="auto", help="Key signature (e.g. 'auto', 'C', 'Am', 'G', 'Em', 'D', 'Bb')")

    # Quantization & Tuplets
    parser.add_argument("--quantize", dest="quantize", action="store_true", default=True, help="Enable rhythmic grid quantization")
    parser.add_argument("--no-quantize", dest="quantize", action="store_false", help="Disable rhythmic grid quantization")
    parser.add_argument("--no-tuplets", action="store_true", default=True, help="Enforce straight binary grid (1/16 sixteenth notes, no triplets/tuplets)")
    parser.add_argument("--grid", type=int, default=4, help="Grid subdivision per beat (4 = 1/16 sixteenths, 2 = 1/8 eighths, 3 = triplets, 8 = 1/32)")
    parser.add_argument("--quantize-strength", type=float, default=1.0, help="Quantization strength from 0.0 (no snap) to 1.0 (strict snap)")
    parser.add_argument("--fill-gaps", type=float, default=0.25, help="Hold notes across rests up to this beat fraction to eliminate messy notation rests")
    parser.add_argument("--trim-leading-bars", action="store_true", default=False, help="Drop empty leading measures before the first note")
    parser.add_argument("--instruments", nargs="*", default=None, help="Optional instrument filter list (e.g. acoustic_piano clean_electric_guitar)")

    args = parser.parse_args()

    if not args.audio_path:
        parser.print_help()
        sys.exit(1)

    audio_path = args.audio_path
    if not os.path.exists(audio_path):
        print(f"Error: Audio file not found: {audio_path}")
        sys.exit(1)

    # Resolve legacy positional arguments if provided
    model_size = args.pos_model_size if args.pos_model_size in ("small", "medium", "large") else args.model_size
    output_midi_path = args.pos_output if args.pos_output else args.output

    # Resolve time signature
    parsed_num, parsed_denom = parse_time_signature_string(args.time_signature)
    time_sig_num = args.beats_per_bar if args.beats_per_bar is not None else parsed_num
    time_sig_denom = args.time_sig_denom if args.time_sig_denom is not None else parsed_denom

    # Resolve grid division: if --no-tuplets is active and grid is 3 or 6, force 4 (1/16 notes)
    grid_div = args.grid
    if args.no_tuplets and grid_div in (3, 6):
        grid_div = 4

    print("Checking acceleration device (CUDA / TPU / CPU)...")
    device = "cpu"
    if torch.cuda.is_available():
        device = "cuda"
        print(f"Using CUDA GPU: {torch.cuda.get_device_name(0)}")
    else:
        try:
            import torch_xla.core.xla_model as xm
            device = xm.xla_device()
            print(f"Using Google TPU: {device}")
        except Exception:
            print("Using CPU device")

    if "HF_TOKEN" not in os.environ:
        print("Note: HF_TOKEN environment variable is not set. If the model fails to download,")
        print("please log in using 'huggingface-cli login' or set the HF_TOKEN environment variable.")

    print(f"Loading MuScriptor model '{model_size}'...")
    try:
        from muscriptor import TranscriptionModel
        model = TranscriptionModel.load_model(weights_path=model_size, device=device)
        print("Model loaded successfully!")
    except Exception as e:
        print(f"Error loading model: {e}")
        print("If this is a memory error, try using 'medium' or 'small' size.")
        sys.exit(1)

    print(f"Transcribing audio: {audio_path}...")
    try:
        from muscriptor.utils.audio import _read_wav_file
        with open(audio_path, "rb") as f:
            wav, sr = _read_wav_file(f)

        events = []
        with torch.inference_mode():
            for ev in model.transcribe((wav, sr), instruments=args.instruments, batch_size=1):
                from muscriptor.events import ProgressEvent
                if not isinstance(ev, ProgressEvent):
                    events.append(ev)

        print(f"Transcribed {len(events)} note events.")
        raw_midi_bytes = model.events_to_midi_bytes(iter(events))

        # Apply robust musical timing, key signature, tempo, and tuplet-free quantization
        print("Applying post-processing (Time Signature, Key Signature, Tempo & Quantization)...")
        _, final_midi_bytes, meta = postprocess_midi(
            midi_source=raw_midi_bytes,
            output_path=output_midi_path,
            bpm=args.bpm,
            time_sig_num=time_sig_num,
            time_sig_denom=time_sig_denom,
            key_signature=args.key_signature,
            quantize=args.quantize,
            grid_div=grid_div,
            quantize_strength=args.quantize_strength,
            fill_gaps_beats=args.fill_gaps,
            trim_leading_bars=args.trim_leading_bars,
            beat_scale=args.beat_scale
        )

        print("━" * 60)
        print("✅ Transcription Complete!")
        print(f" • Output MIDI:     {output_midi_path}")
        print(f" • Time Signature: {meta['time_signature']}")
        print(f" • Key Signature:  {meta['key_signature']}")
        print(f" • Tempo (BPM):    {meta['bpm']:.1f}")
        print(f" • Quantization:   {'Enabled (No Tuplets - 1/16 Grid)' if meta.get('no_tuplets') else ('Enabled' if meta['quantized'] else 'Disabled')}")
        print("━" * 60)

    except Exception as e:
        print(f"Error during transcription: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
