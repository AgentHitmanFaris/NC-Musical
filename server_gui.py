import os
import sys
import shutil

# Configure local D-drive path for HuggingFace home
project_dir = os.path.dirname(os.path.abspath(__file__))
local_hf_home = os.path.join(project_dir, ".cache", "huggingface")

# If old cache exists and local cache does not, copy it to avoid redownloads and keep credentials
old_hf_home = os.path.expanduser("~/.cache/huggingface")
if os.path.exists(old_hf_home) and not os.path.exists(local_hf_home):
    print(f"Migrating HuggingFace cache from C-drive ({old_hf_home}) to D-drive ({local_hf_home}) to save C-drive space...")
    try:
        os.makedirs(os.path.dirname(local_hf_home), exist_ok=True)
        shutil.copytree(old_hf_home, local_hf_home)
        print("Migration complete!")
    except Exception as e:
        print(f"Warning: Failed to auto-migrate cache: {e}")

if "HF_HOME" not in os.environ:
    os.environ["HF_HOME"] = local_hf_home
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
    parser.add_argument("--model", type=str, default="medium", help="Model size: 'small', 'medium', or 'large'")
    parser.add_argument("--device", type=str, default="cuda", help="Torch device: 'cuda', 'cpu', or 'auto'")
    parser.add_argument("--share", action="store_true", help="Launch a public Gradio share link (gradio.live)")
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
                err_msg = str(e)
                if "gated" in err_msg.lower() or "403" in err_msg or "authorized" in err_msg.lower() or "restricted" in err_msg.lower():
                    friendly_err = (
                        f"Access to the '{requested_size}' model is restricted on HuggingFace. "
                        f"Please visit https://huggingface.co/MuScriptor/muscriptor-{requested_size} "
                        f"in your browser, log in, and click 'Accept/Request Access' to authorize your HuggingFace account."
                    )
                    print("\n" + "!" * 85)
                    print(friendly_err)
                    print("!" * 85 + "\n")
                    raise RuntimeError(friendly_err) from e
                else:
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

    def move_route_before_static_mount(app_obj):
        web_idx = len(app_obj.router.routes) - 1
        for i, r in enumerate(app_obj.router.routes):
            if getattr(r, "name", None) == "web" or r.path == "/":
                web_idx = i
                break
        if web_idx < len(app_obj.router.routes) - 1:
            new_r = app_obj.router.routes.pop()
            app_obj.router.routes.insert(web_idx, new_r)

    # Locate and wrap the original health handler to return GPU name
    original_health_route = None
    for route in app.router.routes:
        if route.path == "/health" and hasattr(route, "methods") and "GET" in route.methods:
            original_health_route = route
            break

    if original_health_route:
        app.router.routes.remove(original_health_route)
        print("Successfully intercepted original /health endpoint to include GPU name.")

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "gpu": gpu_name}
    move_route_before_static_mount(app)

    from fastapi.responses import FileResponse
    @app.get("/audio")
    async def get_latest_audio():
        latest_audio_path = os.path.join(current_dir, ".temp", "latest_audio.wav")
        if os.path.exists(latest_audio_path):
            return FileResponse(latest_audio_path, media_type="audio/wav")
        raise HTTPException(status_code=404, detail="No audio file transcribed yet")
    move_route_before_static_mount(app)

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

            filename = file.filename or ""
            ext = os.path.splitext(filename)[1].lower() or ".wav"

            # Async generator function to do file processing and streaming
            def gen():
                temp_input_path = None
                try:
                    temp_dir = os.path.join(current_dir, ".temp")
                    os.makedirs(temp_dir, exist_ok=True)
                    
                    yield f"data: {json.dumps({'type': 'status_update', 'message': 'Processing uploaded file...'})}\n\n"
                    
                    # Save the uploaded file to a temp file
                    with tempfile.NamedTemporaryFile(suffix=ext, dir=temp_dir, delete=False) as temp_in:
                        temp_in.write(file.file.read())
                        temp_input_path = temp_in.name

                    latest_audio_path = os.path.join(temp_dir, "latest_audio.wav")
                    
                    # Convert to standard 16kHz mono WAV using FFmpeg
                    cmd = [
                        ffmpeg_executable, "-y", "-i", temp_input_path,
                        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                        latest_audio_path
                    ]
                    print(f"Running FFmpeg: {' '.join(cmd)}")
                    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if result.returncode != 0:
                        yield f"data: {json.dumps({'type': 'status_update', 'message': 'FFmpeg conversion to standardized WAV failed!'})}\n\n"
                        return

                    from muscriptor.utils.audio import _read_wav_file
                    with open(latest_audio_path, "rb") as f:
                        wav_data = f.read()
                    wav, sr = _read_wav_file(BytesIO(wav_data))

                    # Stream transcription
                    for chunk in run_transcription(wav, sr, instruments, model_size, cancel):
                        yield chunk

                except Exception as e:
                    yield f"data: {json.dumps({'type': 'status_update', 'message': f'Error standardizing audio: {str(e)}'})}\n\n"
                finally:
                    if temp_input_path and os.path.exists(temp_input_path):
                        try: os.remove(temp_input_path)
                        except: pass
                    release_once()

            from starlette.background import BackgroundTask
            return StreamingResponse(
                gen(),
                media_type="text/event-stream",
                background=BackgroundTask(release_once),
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        move_route_before_static_mount(app)

    # Desktop save endpoint — opens native file dialog for pywebview/file:// mode
    @app.post("/save_file")
    async def save_file(
        data: str = Form(...),
        filename: str = Form("output.mid"),
        filetype: str = Form("midi"),
    ):
        """Save file via native OS dialog. Used by desktop mode where blob downloads are blocked."""
        import tkinter as tk
        from tkinter import filedialog

        # Determine file type filters
        filetypes_map = {
            "midi": [("MIDI files", "*.mid"), ("All files", "*.*")],
            "json": [("JSON files", "*.json"), ("All files", "*.*")],
        }
        ft = filetypes_map.get(filetype, [("All files", "*.*")])

        # Decode the base64 data
        file_bytes = base64.b64decode(data)

        # Open native save dialog on a separate thread to avoid blocking
        def do_save():
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            save_path = filedialog.asksaveasfilename(
                initialfile=filename,
                filetypes=ft,
                defaultextension=ft[0][1].replace("*", ""),
            )
            root.destroy()
            return save_path

        import asyncio
        save_path = await asyncio.to_thread(do_save)

        if not save_path:
            return {"status": "cancelled"}

        with open(save_path, "wb") as f:
            f.write(file_bytes)

        return {"status": "saved", "path": save_path}

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

                # Step 1: Download from YouTube — cookieless-first, cookies as fallback
                yield f"data: {json.dumps({'type': 'status_update', 'message': 'Downloading YouTube audio track...'})}\n\n"

                cookie_candidates = [
                    os.path.join(current_dir, "cookies.txt"),
                    os.path.join(current_dir, ".temp", "cookies.txt"),
                ]
                cookie_file = next((cp for cp in cookie_candidates if os.path.exists(cp)), None)

                # Cookieless strategies ordered by bot-bypass reliability
                cookieless_strategies = [
                    ['tv_embedded'],
                    ['android'],
                    ['android_vr'],
                    ['ios'],
                    ['tv_embedded', 'android'],
                    ['android', 'ios'],
                    ['mweb'],
                    ['web_embedded'],
                    ['web', 'android'],
                ]

                base_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': os.path.join(temp_dir, 'yt_download_%(id)s.%(ext)s'),
                    'quiet': True,
                    'no_warnings': True,
                    'noplaylist': True,
                }

                download_err = None
                temp_audio_path = None

                # Phase 1: try all cookieless strategies
                for clients in cookieless_strategies:
                    opts = {**base_opts, 'extractor_args': {'youtube': {'player_client': clients}}}
                    try:
                        print(f"Trying player_client={clients} (no cookies)...")
                        with yt_dlp.YoutubeDL(opts) as ydl:
                            info = ydl.extract_info(url, download=True)
                            candidate = ydl.prepare_filename(info)
                            if candidate and os.path.exists(candidate):
                                temp_audio_path = candidate
                                download_err = None
                                break
                    except Exception as ex:
                        download_err = ex

                # Phase 2: try with cookies if cookieless all failed
                if not temp_audio_path and cookie_file:
                    print(f"Cookieless attempts failed. Retrying with cookies: {cookie_file}")
                    yield f"data: {json.dumps({'type': 'status_update', 'message': 'Retrying with cookies....'})}\n\n"
                    for clients in [['tv_embedded'], ['android'], ['web']]:
                        opts = {**base_opts,
                                'extractor_args': {'youtube': {'player_client': clients}},
                                'cookiefile': cookie_file}
                        try:
                            print(f"Trying player_client={clients} + cookies...")
                            with yt_dlp.YoutubeDL(opts) as ydl:
                                info = ydl.extract_info(url, download=True)
                                candidate = ydl.prepare_filename(info)
                                if candidate and os.path.exists(candidate):
                                    temp_audio_path = candidate
                                    download_err = None
                                    break
                        except Exception as ex:
                            download_err = ex

                if not temp_audio_path or not os.path.exists(temp_audio_path):
                    msg = (f"YouTube download failed: {download_err}. "
                           "Place a cookies.txt in the project folder or upload an audio file directly.")
                    yield f"data: {json.dumps({'type': 'status_update', 'message': msg})}\n\n"
                    return

                
                # Step 2: Convert to WAV using FFmpeg
                yield f"data: {json.dumps({'type': 'status_update', 'message': 'Converting audio track to WAV...'})}\n\n"
                
                latest_audio_path = os.path.join(temp_dir, "latest_audio.wav")
                cmd = [
                    ffmpeg_executable, "-y", "-i", temp_audio_path,
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    latest_audio_path
                ]
                print(f"Running FFmpeg: {' '.join(cmd)}")
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if result.returncode != 0:
                    yield f"data: {json.dumps({'type': 'status_update', 'message': 'FFmpeg conversion failed!'})}\n\n"
                    return
                
                # Step 3: Perform Transcription
                from muscriptor.utils.audio import _read_wav_file
                with open(latest_audio_path, "rb") as f:
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
