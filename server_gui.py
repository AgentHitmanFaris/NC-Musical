import os
import sys
import argparse
import subprocess
import tempfile
import uvicorn
from io import BytesIO
from fastapi import File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from muscriptor.transcription_model import TranscriptionModel
from muscriptor.server import create_app

def main():
    parser = argparse.ArgumentParser(description="Run the MuScriptor GUI Server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=8222, help="Port to listen on")
    parser.add_argument("--model", type=str, default="large", help="Model size: 'small', 'medium', or 'large'")
    parser.add_argument("--device", type=str, default="cuda", help="Torch device: 'cuda', 'cpu', or 'auto'")
    args = parser.parse_args()

    # Determine device
    import torch
    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    elif device == "cuda" and not torch.cuda.is_available():
        print("Warning: CUDA requested but not available. Falling back to CPU.")
        device = "cpu"

    print(f"Loading MuScriptor model '{args.model}' on device '{device}'...")
    try:
        model = TranscriptionModel.load_model(weights_path=args.model, device=device)
        print("Model loaded successfully!")
    except Exception as e:
        print(f"Error loading model: {e}")
        sys.exit(1)

    # Get current working directory where gui.html (or index.html) will reside
    current_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"Serving web directory: {current_dir}")

    # Create app
    app = create_app(model, web_dir=current_dir)

    # Locate and wrap the original transcribe handler to intercept video files
    original_route = None
    for route in app.router.routes:
        if route.path == "/transcribe" and hasattr(route, "methods") and "POST" in route.methods:
            original_route = route
            break

    if original_route:
        original_handler = original_route.endpoint
        print("Successfully intercepted original /transcribe endpoint to add video support.")

        @app.post("/transcribe")
        async def wrapped_transcribe(
            file: UploadFile = File(...),
            instruments: list[str] = Form(default=[])
        ):
            filename = file.filename or ""
            ext = os.path.splitext(filename)[1].lower()
            video_exts = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".webm", ".m4v", ".3gp"}

            if ext in video_exts:
                print(f"Video file detected: {filename}. Extracting audio track...")
                
                # Save uploaded video to temporary file
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as temp_video:
                    temp_video.write(await file.read())
                    temp_video_path = temp_video.name

                temp_wav_path = temp_video_path + ".wav"

                try:
                    # Run FFmpeg to extract audio as 16kHz mono WAV
                    cmd = [
                        "ffmpeg", "-y", "-i", temp_video_path,
                        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                        temp_wav_path
                    ]
                    print(f"Running FFmpeg: {' '.join(cmd)}")
                    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    
                    if result.returncode != 0:
                        raise HTTPException(
                            status_code=500,
                            detail=f"FFmpeg failed to extract audio: {result.stderr.decode('utf-8')}"
                        )

                    # Read extracted WAV bytes
                    with open(temp_wav_path, "rb") as wav_file:
                        wav_bytes = wav_file.read()

                    # Wrap in new UploadFile object
                    wrapped_file = UploadFile(
                        file=BytesIO(wav_bytes),
                        filename=os.path.splitext(filename)[0] + ".wav",
                        headers=file.headers
                    )
                    
                    # Forward to original transcription handler
                    return await original_handler(wrapped_file, instruments)

                except Exception as e:
                    print(f"Error extracting audio from video: {e}")
                    raise HTTPException(status_code=500, detail=f"Failed to process video audio track: {e}")
                
                finally:
                    # Cleanup temporary files
                    if os.path.exists(temp_video_path):
                        os.remove(temp_video_path)
                    if os.path.exists(temp_wav_path):
                        os.remove(temp_wav_path)
            else:
                # Normal audio file, pass through
                return await original_handler(file, instruments)

    # Add CORS middleware just in case user opens index.html locally via file:// protocol
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    print(f"Starting server on http://{args.host}:{args.port}")
    print(f"To open GUI, visit: http://{args.host}:{args.port}/index.html")
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()
