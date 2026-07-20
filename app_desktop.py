import os
import sys
import shutil
import json
import threading
import time
import socket
import urllib.request
import urllib.parse
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

# Non-blocking async cache migration to prevent startup freezing
def _async_migrate_cache():
    if os.path.exists(old_hf_home) and not os.path.exists(local_hf_home):
        print(f"Migrating HuggingFace cache to D-drive in background: {local_hf_home}...")
        try:
            os.makedirs(os.path.dirname(local_hf_home), exist_ok=True)
            shutil.copytree(old_hf_home, local_hf_home)
            print("Migration complete!")
        except Exception as e:
            print(f"Warning: Cache migration failed: {e}")

threading.Thread(target=_async_migrate_cache, daemon=True).start()
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
        self._window = window_ref

    @property
    def win(self):
        return self._window[0]

    def get_last_url(self):
        return load_last_url()

    def open_colab(self):
        webbrowser.open(COLAB_NOTEBOOK_URL)
        return True

    def browse_file(self):
        file_types = ('Audio/Video Files (*.mp3;*.wav;*.mp4;*.m4a;*.flac;*.ogg)', 'All files (*.*)')
        result = self.win.create_file_dialog(webview.OPEN_DIALOG, file_types=file_types)
        if result and len(result) > 0:
            file_path = result[0]
            return {"path": file_path, "name": os.path.basename(file_path)}
        return None

    def open_piano_roll(self, cloud_url):
        write_config_cloud(cloud_url)
        self.win.resize(1380, 860)
        self.win.load_url(f"{cloud_url}/index.html")
        return True

    def connect_and_transcribe(self, payload):
        colab_url = payload.get("colab_url", "").rstrip("/")
        youtube_url = payload.get("youtube_url")
        file_path = payload.get("file_path")

        # 1. Validate Colab connection first
        try:
            req = urllib.request.Request(
                f"{colab_url}/health",
                headers={"User-Agent": "NC-Musical-Desktop/1.0"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status != 200:
                    return {"ok": False, "error": f"Colab server returned HTTP {resp.status}"}
        except Exception as e:
            return {"ok": False, "error": f"Cannot reach Colab at {colab_url}. Make sure Cells 1-4 are running."}

        save_last_url(colab_url)

        # 2. Trigger transcription in background thread
        def run_remote_transcription():
            try:
                if youtube_url:
                    self.win.evaluate_js(f"updateCloudStatus('loading', 'Downloading YouTube audio via Colab GPU...', 10);")
                    params = urllib.parse.urlencode({"url": youtube_url, "model_size": "large"})
                    endpoint = f"{colab_url}/transcribe_youtube?{params}"
                    req = urllib.request.Request(endpoint, headers={"User-Agent": "NC-Musical-Desktop/1.0"})
                    with urllib.request.urlopen(req) as resp:
                        for line in resp:
                            line_str = line.decode('utf-8').strip()
                            if line_str.startswith("data: "):
                                data_json = line_str[6:]
                                try:
                                    evt = json.loads(data_json)
                                    msg = evt.get("message", "Processing...")
                                    self.win.evaluate_js(f"updateCloudStatus('loading', {json.dumps(msg)}, 50);")
                                except:
                                    pass
                elif file_path:
                    self.win.evaluate_js(f"updateCloudStatus('loading', 'Uploading file to Colab GPU...', 20);")
                    import requests
                    with open(file_path, 'rb') as f:
                        files = {'file': (os.path.basename(file_path), f)}
                        data = {'model_size': 'large'}
                        r = requests.post(f"{colab_url}/transcribe", files=files, data=data, stream=True)
                        for chunk in r.iter_lines():
                            if chunk:
                                line_str = chunk.decode('utf-8').strip()
                                if line_str.startswith("data: "):
                                    try:
                                        evt = json.loads(line_str[6:])
                                        msg = evt.get("message", "Processing...")
                                        self.win.evaluate_js(f"updateCloudStatus('loading', {json.dumps(msg)}, 50);")
                                    except:
                                        pass

                self.win.evaluate_js(f"connectedCloudUrl = '{colab_url}';")
                self.win.evaluate_js(f"showResults('{colab_url}/audio', null);")

            except Exception as ex:
                self.win.evaluate_js(f"updateCloudStatus('error', {json.dumps(str(ex))}, 0);")

        threading.Thread(target=run_remote_transcription, daemon=True).start()
        return {"ok": True}

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


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    launcher_path = os.path.join(project_dir, "launcher.html")

    window_ref = [None]
    api = LauncherApi(window_ref)

    window = webview.create_window(
        "NC-Musical — Select Mode",
        launcher_path,
        width=880,
        height=740,
        min_size=(800, 640),
        js_api=api,
        background_color="#07080c",
        resizable=True,
    )
    window_ref[0] = window

    webview.start()
