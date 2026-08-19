import os
import sys
import torch
from muscriptor import TranscriptionModel

def main():
    if len(sys.argv) < 2:
        print("Usage: python transcribe.py <path_to_audio_file> [model_size] [output_midi_path]")
        print("Model sizes: small, medium, large (default: large)")
        sys.exit(1)

    audio_path = sys.argv[1]
    
    # Model size defaults to large
    model_size = "large"
    if len(sys.argv) > 2:
        model_size = sys.argv[2]
        
    # Output file defaults to output.mid
    output_midi_path = "output.mid"
    if len(sys.argv) > 3:
        output_midi_path = sys.argv[3]

    if not os.path.exists(audio_path):
        print(f"Error: Audio file not found: {audio_path}")
        sys.exit(1)

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

    # Ensure Hugging Face Token is set if needed for gated model
    if "HF_TOKEN" not in os.environ:
        print("Note: HF_TOKEN environment variable is not set. If the model fails to download,")
        print("please log in using 'huggingface-cli login' or set the HF_TOKEN environment variable.")

    print(f"Loading MuScriptor model '{model_size}'...")
    try:
        model = TranscriptionModel.load_model(weights_path=model_size, device=device)
        print("Model loaded successfully!")
    except Exception as e:
        print(f"Error loading model: {e}")
        print("If this is a memory error, try using 'medium' or 'small' size.")
        sys.exit(1)

    print(f"Transcribing audio: {audio_path}...")
    try:
        midi_bytes = model.transcribe_to_midi(audio_path)
        
        with open(output_midi_path, "wb") as f:
            f.write(midi_bytes)
            
        print(f"Success! MIDI saved to: {output_midi_path}")
    except Exception as e:
        print(f"Error during transcription: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
