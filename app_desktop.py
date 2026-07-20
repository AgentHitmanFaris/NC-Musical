import os
import sys
import shutil

# Prepend dynamic fluidsynth binary directory to system PATH
fs_bin = r"D:\Document\NC-Project\sheetsage\AtoScore_Core\bin"
if fs_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = fs_bin + os.path.pathsep + os.environ.get("PATH", "")

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

os.environ["HF_HOME"] = local_hf_home

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

def wait_for_server(port, timeout=15):
    """Wait for the FastAPI backend server to be ready before opening the WebView window."""
    start = time.time()
    health_url = f"http://127.0.0.1:{port}/health"
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(health_url)
            with urllib.request.urlopen(req, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False

if __name__ == "__main__":
    port = find_free_port()
    
    # Write dynamic port configuration to config.js so local file system can find backend
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.js")
    with open(config_path, "w") as f:
        f.write(f"const BACKEND_PORT = {port};\n")
        
    # Start FastAPI server in background daemon thread
    server_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
    server_thread.start()
    
    # Wait for backend server to complete initialization
    print(f"Waiting for backend server to start on port {port}...")
    wait_for_server(port)
    
    server_url = f"http://127.0.0.1:{port}/index.html"
    print(f"Launching GUI window at: {server_url}")
    
    # Start native WebView2 window wrapper pointing to local HTTP server
    webview.create_window(
        "MuScriptor AMT Desktop",
        server_url,
        width=1320,
        height=850,
        background_color='#07080c'
    )
    
    webview.start()
