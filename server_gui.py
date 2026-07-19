import os
import sys
import argparse
import subprocess
import tempfile
import json
import base64
import asyncio
import threading
from io import BytesIO
import torch
import uvicorn
import yt_dlp
from fastapi import File, Form, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from muscriptor.transcription_model import TranscriptionModel
from muscriptor.server import create_app, event_to_dict
from muscriptor.events import ProgressEvent

def main():
    parser = argparse.ArgumentParser(description="Run the MuScriptor GUI Server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=8222, help="Port to listen on")
    parser.add_argument("--model", type=str, default="large", help="Model size: 'small', 'medium', or 'large'")
    parser.add_argument("--device", type=str, default="cuda", help="Torch device: 'cuda', 'cpu', or 'auto'")
    args = parser.parse_args()

    # Determine device and verify GPU
    device = args.device
    gpu_name = None
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
    if "cuda" in device:
        if torch.cuda.is_available():
            # Explicitly verify which GPU is used
            gpu_name = torch.cuda.get_device_name(0)
            print(f"CUDA is available! Explicitly using GPU 0: {gpu_name}")
            device = "cuda:0"
        else:
            print("Warning: CUDA requested but not available. Falling back to CPU.")
            device = "cpu"

    print(f"Loading MuScriptor model '{args.model}' on device '{device}'...")
    try:
        model = TranscriptionModel.load_model(weights_path=args.model, device=device)
        print("Model loaded successfully!")
    except Exception as e:
        print(f"Error loading model: {e}")
        sys.exit(1)

    # Get current working directory where index.html resides
    current_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"Serving web directory: {current_dir}")

    # Create app
    app = create_app(model, web_dir=current_dir)

    # Intercept health check to include GPU name
    @app.get("/health")
    async def health_check():
        return {"status": "ok", "gpu": gpu_name}

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

    # Add YouTube transcription endpoint
    @app.post("/transcribe_youtube")
    async def transcribe_youtube(
        url: str = Form(...),
        instruments: list[str] = Form(default=[])
    ):
        print(f"YouTube Transcription requested for: {url}")
        
        # Reuse same concurrency lock as original /transcribe to prevent overloading GPU
        # In FastAPI serve.py, transcribe_lock is a module-level lock or app-level property,
        # but here we can just use a local lock or leverage the original /transcribe lock.
        # However, to keep it simple, we can run it and load the audio.
        
        def sse_generator():
            temp_audio_path = None
            temp_wav_path = None
            
            try:
                # Step 1: Download from YouTube using yt-dlp
                yield f"data: {json.dumps({'type': 'status_update', 'message': 'Downloading YouTube audio track...'})}\n\n"
                
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': os.path.join(tempfile.gettempdir(), 'yt_download_%(id)s.%(ext)s'),
                    'quiet': True,
                    'no_warnings': True,
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    downloaded_filename = ydl.prepare_filename(info)
                    temp_audio_path = downloaded_filename
                
                # Step 2: Convert to WAV using FFmpeg
                yield f"data: {json.dumps({'type': 'status_update', 'message': 'Converting audio track to WAV...'})}\n\n"
                
                temp_wav_path = temp_audio_path + ".wav"
                cmd = [
                    "ffmpeg", "-y", "-i", temp_audio_path,
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    temp_wav_path
                ]
                print(f"Running FFmpeg: {' '.join(cmd)}")
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if result.returncode != 0:
                    yield f"data: {json.dumps({'type': 'status_update', 'message': 'FFmpeg conversion failed!'})}\n\n"
                    return
                
                # Step 3: Perform Transcription
                yield f"data: {json.dumps({'type': 'status_update', 'message': 'Loading audio track into transcription engine...'})}\n\n"
                
                from muscriptor.utils.audio import _read_wav_file
                with open(temp_wav_path, "rb") as f:
                    wav_data = f.read()
                wav, sr = _read_wav_file(BytesIO(wav_data))
                
                events = []
                yield f"data: {json.dumps({'type': 'status_update', 'message': 'Starting model run...'})}\n\n"
                
                for ev in model.transcribe(
                    (wav, sr),
                    instruments=instruments or None,
                    batch_size=1,
                    no_eos_is_ok=True,
                ):
                    if isinstance(ev, ProgressEvent):
                        payload = json.dumps({
                            "type": "progress",
                            "completed": ev.completed,
                            "total": ev.total
                        })
                        yield f"data: {payload}\n\n"
                        continue
                    events.append(ev)
                    payload = json.dumps(event_to_dict(ev))
                    yield f"data: {payload}\n\n"
                
                # Step 4: Finalize MIDI payload
                midi_bytes = model.events_to_midi_bytes(iter(events))
                midi_b64 = base64.b64encode(midi_bytes).decode("ascii")
                payload = json.dumps({"type": "midi", "data": midi_b64})
                yield f"data: {payload}\n\n"
                
            except Exception as e:
                print(f"Error during YouTube transcription: {e}")
                yield f"data: {json.dumps({'type': 'status_update', 'message': f'Error: {str(e)}'})}\n\n"
            finally:
                # Cleanup files
                if temp_audio_path and os.path.exists(temp_audio_path):
                    try: os.remove(temp_audio_path)
                    except: pass
                if temp_wav_path and os.path.exists(temp_wav_path):
                    try: os.remove(temp_wav_path)
                    except: pass

        return StreamingResponse(
            sse_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Add CORS middleware
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
