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

    # Find FFmpeg path dynamically
    def find_ffmpeg():
        import shutil
        import glob
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            return ffmpeg_path

        # Check in winget directory under AppData\Local
        appdata_local = os.environ.get("LOCALAPPDATA", "")
        if appdata_local:
            winget_pattern = os.path.join(appdata_local, "Microsoft", "WinGet", "Packages", "**", "ffmpeg.exe")
            winget_matches = glob.glob(winget_pattern, recursive=True)
            if winget_matches:
                print(f"Discovered FFmpeg from WinGet: {winget_matches[0]}")
                return winget_matches[0]

        # Check in current working directory
        if os.path.exists("ffmpeg.exe"):
            return os.path.abspath("ffmpeg.exe")

        return "ffmpeg"

    ffmpeg_executable = find_ffmpeg()

    # Keep track of model in a state dictionary
    model_state = {
        "model": model,
        "model_size": args.model
    }

    # Lock & cancellation controls
    transcribe_lock = threading.Lock()
    current_cancel = None
    cancel_guard = threading.Lock()

    def load_model_if_needed(requested_size: str):
        if requested_size not in ("small", "medium", "large"):
            requested_size = "large"
            
        if model_state["model_size"] != requested_size:
            print(f"Swapping model: {model_state['model_size']} -> {requested_size}...")
            # Release model
            model_state["model"] = None
            import gc
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                
            # Load new model (downloads if not present)
            try:
                model_state["model"] = TranscriptionModel.load_model(weights_path=requested_size, device=device)
                model_state["model_size"] = requested_size
                print(f"Successfully loaded model '{requested_size}'!")
            except Exception as e:
                print(f"Error loading model '{requested_size}': {e}")
                raise e

    def make_release_once(lock):
        released = False
        guard = threading.Lock()
        def release():
            nonlocal released
            with guard:
                if released:
                    return
                released = True
            try: lock.release()
            except RuntimeError: pass
        return release

    def run_transcription(wav, sr, instruments, model_size, cancel):
        try:
            # 1. Swap model if needed
            yield f"data: {json.dumps({'type': 'status_update', 'message': f'Initializing transcription model: {model_size}...'})}\n\n"
            try:
                load_model_if_needed(model_size)
            except Exception as e:
                yield f"data: {json.dumps({'type': 'status_update', 'message': f'Failed to load model: {str(e)}'})}\n\n"
                return

            if cancel.is_set():
                return

            # 2. Run model.transcribe
            events = []
            active_model = model_state["model"]
            yield f"data: {json.dumps({'type': 'status_update', 'message': 'Running transcription model...'})}\n\n"
            
            for ev in active_model.transcribe(
                (wav, sr),
                instruments=instruments or None,
                batch_size=1,
                no_eos_is_ok=True,
            ):
                if cancel.is_set():
                    return
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

            # 3. Build MIDI
            if cancel.is_set():
                return
            yield f"data: {json.dumps({'type': 'status_update', 'message': 'Generating MIDI file...'})}\n\n"
            midi_bytes = active_model.events_to_midi_bytes(iter(events))
            midi_b64 = base64.b64encode(midi_bytes).decode("ascii")
            payload = json.dumps({"type": "midi", "data": midi_b64})
            yield f"data: {payload}\n\n"

        except Exception as e:
            print(f"Error in run_transcription: {e}")
            yield f"data: {json.dumps({'type': 'status_update', 'message': f'Error: {str(e)}'})}\n\n"

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
        app.router.routes.remove(original_route)
        print("Successfully intercepted original /transcribe endpoint to add video support.")

        @app.post("/transcribe")
        async def wrapped_transcribe(
            file: UploadFile = File(...),
            instruments: list[str] = Form(default=[]),
            model_size: str = Form(default="large")
        ):
            # Preempt previous runs
            nonlocal current_cancel
            with cancel_guard:
                if current_cancel is not None:
                    current_cancel.set()
            cancel = threading.Event()
            with cancel_guard:
                current_cancel = cancel

            # Acquire Lock
            acquired = transcribe_lock.acquire(blocking=True, timeout=60.0)
            if not acquired:
                raise HTTPException(status_code=503, detail="Server busy")

            release_once = make_release_once(transcribe_lock)

            # Get filename
            filename = file.filename or ""
            ext = os.path.splitext(filename)[1].lower()
            video_exts = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".webm", ".m4v", ".3gp"}

            # Async generator function to do file processing and streaming
            def gen():
                temp_video_path = None
                temp_wav_path = None
                try:
                    if ext in video_exts:
                        # Extract audio from video
                        yield f"data: {json.dumps({'type': 'status_update', 'message': f'Video file detected. Extracting audio track...'})}\n\n"
                        temp_dir = os.path.join(current_dir, ".temp")
                        os.makedirs(temp_dir, exist_ok=True)
                        
                        with tempfile.NamedTemporaryFile(suffix=ext, dir=temp_dir, delete=False) as temp_video:
                            temp_video.write(file.file.read())
                            temp_video_path = temp_video.name

                        temp_wav_path = temp_video_path + ".wav"
                        cmd = [
                            ffmpeg_executable, "-y", "-i", temp_video_path,
                            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                            temp_wav_path
                        ]
                        print(f"Running FFmpeg: {' '.join(cmd)}")
                        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        if result.returncode != 0:
                            yield f"data: {json.dumps({'type': 'status_update', 'message': 'FFmpeg conversion failed!'})}\n\n"
                            return

                        from muscriptor.utils.audio import _read_wav_file
                        with open(temp_wav_path, "rb") as f:
                            wav_data = f.read()
                        wav, sr = _read_wav_file(BytesIO(wav_data))
                    else:
                        # Direct audio
                        data = file.file.read()
                        from muscriptor.utils.audio import _read_non_wav_file, _read_wav_file
                        try:
                            wav, sr = _read_wav_file(BytesIO(data))
                        except (wave.Error, EOFError):
                            try:
                                wav, sr = _read_non_wav_file(BytesIO(data))
                            except Exception as e:
                                yield f"data: {json.dumps({'type': 'status_update', 'message': f'Decoding failed: {str(e)}'})}\n\n"
                                return

                    # Stream transcription
                    for chunk in run_transcription(wav, sr, instruments, model_size, cancel):
                        yield chunk

                finally:
                    # Cleanup
                    if temp_video_path and os.path.exists(temp_video_path):
                        try: os.remove(temp_video_path)
                        except: pass
                    if temp_wav_path and os.path.exists(temp_wav_path):
                        try: os.remove(temp_wav_path)
                        except: pass
                    release_once()

            from starlette.background import BackgroundTask
            return StreamingResponse(
                gen(),
                media_type="text/event-stream",
                background=BackgroundTask(release_once),
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        def move_route_before_static_mount(app_obj):
            web_idx = len(app_obj.router.routes) - 1
            for i, r in enumerate(app_obj.router.routes):
                if getattr(r, "name", None) == "web" or r.path == "/":
                    web_idx = i
                    break
            if web_idx < len(app_obj.router.routes) - 1:
                new_r = app_obj.router.routes.pop()
                app_obj.router.routes.insert(web_idx, new_r)

        move_route_before_static_mount(app)

    # Add YouTube transcription endpoint
    @app.post("/transcribe_youtube")
    async def transcribe_youtube(
        url: str = Form(...),
        instruments: list[str] = Form(default=[]),
        model_size: str = Form(default="large")
    ):
        print(f"YouTube Transcription requested for: {url}")
        
        nonlocal current_cancel
        with cancel_guard:
            if current_cancel is not None:
                current_cancel.set()
        cancel = threading.Event()
        with cancel_guard:
            current_cancel = cancel

        acquired = transcribe_lock.acquire(blocking=True, timeout=60.0)
        if not acquired:
            raise HTTPException(status_code=503, detail="Server busy")

        release_once = make_release_once(transcribe_lock)

        def sse_generator():
            temp_audio_path = None
            temp_wav_path = None
            
            try:
                # Use local temp folder inside the current directory
                temp_dir = os.path.join(current_dir, ".temp")
                os.makedirs(temp_dir, exist_ok=True)

                # Step 1: Download from YouTube using yt-dlp
                yield f"data: {json.dumps({'type': 'status_update', 'message': 'Downloading YouTube audio track...'})}\n\n"
                
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': os.path.join(temp_dir, 'yt_download_%(id)s.%(ext)s'),
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
                    ffmpeg_executable, "-y", "-i", temp_audio_path,
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    temp_wav_path
                ]
                print(f"Running FFmpeg: {' '.join(cmd)}")
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if result.returncode != 0:
                    yield f"data: {json.dumps({'type': 'status_update', 'message': 'FFmpeg conversion failed!'})}\n\n"
                    return
                
                # Step 3: Perform Transcription
                from muscriptor.utils.audio import _read_wav_file
                with open(temp_wav_path, "rb") as f:
                    wav_data = f.read()
                wav, sr = _read_wav_file(BytesIO(wav_data))
                
                for chunk in run_transcription(wav, sr, instruments, model_size, cancel):
                    yield chunk
                
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

    if original_route:
        move_route_before_static_mount(app)

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
