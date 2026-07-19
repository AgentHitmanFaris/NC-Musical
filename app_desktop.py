import os
import sys

# Redirect standard streams if running under pythonw.exe (no console attached)
# This prevents uvicorn and print statements from crashing on NoneType attributes.
if sys.stdout is None or sys.stderr is None:
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".temp")
    os.makedirs(log_dir, exist_ok=True)
    log_file = open(os.path.join(log_dir, "desktop_server.log"), "a", encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file

import threading
import time
import socket
import urllib.request
import urllib.error
import webview

def find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def run_server(port):
    from server_gui import main
    # Pass arguments to server_gui.py
    sys.argv = [sys.argv[0], "--port", str(port), "--model", "medium", "--device", "auto"]
    main()

if __name__ == "__main__":
    port = find_free_port()
    
    # Start FastAPI server in background daemon thread
    server_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
    server_thread.start()
    
    # Poll the health check endpoint until uvicorn binds and responds
    health_url = f"http://127.0.0.1:{port}/health"
    print(f"Waiting for backend server to start at {health_url}...")
    
    server_ready = False
    for i in range(120):  # Wait up to 60 seconds (120 * 0.5s)
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as response:
                if response.status == 200:
                    server_ready = True
                    break
        except Exception:
            time.sleep(0.5)
            
    if not server_ready:
        print("Backend server failed to start or load model weights in time.")
        sys.exit(1)
        
    print(f"Launching GUI window at: http://127.0.0.1:{port}/index.html")
    
    # Start native WebView2 window wrapper
    webview.create_window(
        "MuScriptor AMT Desktop",
        f"http://127.0.0.1:{port}/index.html",
        width=1320,
        height=850,
        background_color='#07080c'
    )
    
    webview.start()
