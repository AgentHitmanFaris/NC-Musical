import os
import sys
import threading
import time
import socket
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
    # Using 'medium' as default, device 'auto' to auto-detect CUDA GTX 1060
    sys.argv = [sys.argv[0], "--port", str(port), "--model", "medium", "--device", "auto"]
    main()

if __name__ == "__main__":
    port = find_free_port()
    
    # Start FastAPI server in background daemon thread
    server_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
    server_thread.start()
    
    # Wait for backend server port to bind
    time.sleep(2.5)
    
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
