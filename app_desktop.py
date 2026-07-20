import os
import sys
import shutil
import json
import threading
import time
import socket
import urllib.request
import urllib.error
import webbrowser

# ── Path setup ────────────────────────────────────────────────────────────────
project_dir = os.path.dirname(os.path.abspath(__file__))

# Prepend dynamic fluidsynth binary directory to system PATH
fs_bin = r"D:\Document\NC-Project\sheetsage\AtoScore_Core\bin"
if fs_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = fs_bin + os.path.pathsep + os.environ.get("PATH", "")

# Configure local D-drive path for HuggingFace home
local_hf_home = os.path.join(project_dir, ".cache", "huggingface")
old_hf_home = os.path.expanduser("~/.cache/huggingface")
if os.path.exists(old_hf_home) and not os.path.exists(local_hf_home):
    print(f"Migrating HuggingFace cache to D-drive: {local_hf_home}...")
    try:
        os.makedirs(os.path.dirname(local_hf_home), exist_ok=True)
        shutil.copytree(old_hf_home, local_hf_home)
        print("Migration complete!")
    except Exception as e:
        print(f"Warning: Cache migration failed: {e}")

os.environ["HF_HOME"] = local_hf_home

# ── Log redirect (pythonw.exe has no console) ─────────────────────────────────
if sys.stdout is None or sys.stderr is None:
    log_dir = os.path.join(project_dir, ".temp")
    os.makedirs(log_dir, exist_ok=True)
    log_file = open(os.path.join(log_dir, "desktop_server.log"), "a", encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file

import webview

COLAB_NOTEBOOK_URL = (
    "https://colab.research.google.com/github/AgentHitmanFaris/NC-Musical"
    "/blob/Stable/NC_Musical_Colab.ipynb"
)
LAST_URL_FILE = os.path.join(project_dir, ".temp", "last_cloud_url.json")

# ── Helpers ───────────────────────────────────────────────────────────────────
def find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for_server(port, timeout=180):
    start = time.time()
    url = f"http://127.0.0.1:{port}/health"
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def write_config_local(port):
    with open(os.path.join(project_dir, "config.js"), "w") as f:
        f.write(f"const BACKEND_PORT = {port};\n")


def write_config_cloud(url):
    with open(os.path.join(project_dir, "config.js"), "w") as f:
        f.write(f'const BACKEND_URL = "{url}";\n')


def save_last_url(url):
    os.makedirs(os.path.dirname(LAST_URL_FILE), exist_ok=True)
    with open(LAST_URL_FILE, "w") as f:
        json.dump({"url": url}, f)


def load_last_url():
    if os.path.exists(LAST_URL_FILE):
        try:
            with open(LAST_URL_FILE) as f:
                return json.load(f).get("url", "")
        except Exception:
            pass
    return ""


# ── Launcher JS API ───────────────────────────────────────────────────────────
class LauncherApi:
    def __init__(self, window_ref):
        self._window = window_ref  # list so we can set it after creation

    @property
    def win(self):
        return self._window[0]

    def get_last_url(self):
        return load_last_url()

    def open_colab(self):
        webbrowser.open(COLAB_NOTEBOOK_URL)
        return True

    def validate_cloud_url(self, url):
        url = url.rstrip("/")
        try:
            req = urllib.request.Request(
                f"{url}/health",
                headers={"User-Agent": "NC-Musical-Desktop/1.0"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    return {"ok": True}
                return {"ok": False, "error": f"Server returned HTTP {resp.status}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def launch_local(self):
        """Start local server_gui.py in background, navigate when ready."""
        port = find_free_port()
        write_config_local(port)

        def run_server():
            sys.argv = [sys.argv[0], "--port", str(port), "--model", "medium", "--device", "auto"]
            from server_gui import main
            main()

        threading.Thread(target=run_server, daemon=True).start()

        def navigate_when_ready():
            if wait_for_server(port, timeout=180):
                self.win.resize(1380, 860)
                self.win.load_url(f"http://127.0.0.1:{port}/index.html")
            else:
                self.win.evaluate_js(
                    "document.getElementById('loading-overlay').classList.remove('visible');"
                    "document.getElementById('local-status-text').textContent='Server failed to start — check your GPU/CUDA installation.';"
                    "document.getElementById('local-status').className='status-msg error visible';"
                    "document.getElementById('local-btn').disabled=false;"
                    "document.getElementById('local-btn').innerHTML='⚡ Launch Locally';"
                )

        threading.Thread(target=navigate_when_ready, daemon=True).start()
        return {"ok": True, "message": "Starting server… loading AI model (may take 1–2 minutes)"}

    def launch_cloud(self, url):
        """Validate cloud URL and navigate the window to it."""
        url = url.rstrip("/")
        result = self.validate_cloud_url(url)
        if result.get("ok"):
            save_last_url(url)
            write_config_cloud(url)
            self.win.resize(1380, 860)
            self.win.load_url(f"{url}/index.html")
            return {"ok": True}
        return result


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    launcher_path = os.path.join(project_dir, "launcher.html")

    # window ref holder (mutable so LauncherApi can access it after creation)
    window_ref = [None]
    api = LauncherApi(window_ref)

    window = webview.create_window(
        "NC-Musical — Select Mode",
        launcher_path,
        width=720,
        height=580,
        js_api=api,
        background_color="#07080c",
        resizable=False,
    )
    window_ref[0] = window

    webview.start()
