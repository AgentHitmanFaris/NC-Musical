const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

let mainWindow = null;
let pythonProcess = null;
const PORT = 8222;

function startPythonServer() {
  const pythonBin = process.platform === 'win32' 
    ? path.join(__dirname, 'venv', 'Scripts', 'python.exe')
    : path.join(__dirname, 'venv', 'bin', 'python');

  console.log(`Launching backend server with: ${pythonBin}`);

  // Spawn python server_gui.py
  pythonProcess = spawn(pythonBin, ['server_gui.py', '--port', PORT.toString()], {
    cwd: __dirname,
    stdio: 'pipe'
  });

  pythonProcess.stdout.on('data', (data) => {
    console.log(`[Backend stdout]: ${data}`);
  });

  pythonProcess.stderr.on('data', (data) => {
    console.error(`[Backend stderr]: ${data}`);
  });

  pythonProcess.on('close', (code) => {
    console.log(`Backend process exited with code ${code}`);
  });
}

function checkServerReady(callback) {
  const interval = setInterval(() => {
    http.get(`http://127.0.0.1:${PORT}/health`, (res) => {
      if (res.statusCode === 200) {
        clearInterval(interval);
        callback();
      }
    }).on('error', () => {
      // Still starting...
    });
  }, 500);

  // Stop trying after 30 seconds
  setTimeout(() => {
    clearInterval(interval);
  }, 30000);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    title: "MuScriptor AMT Desktop",
    backgroundColor: '#0a0b10',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true
    }
  });

  mainWindow.loadURL(`http://127.0.0.1:${PORT}/index.html`);

  // Remove menu bar for clean native app look
  mainWindow.setMenuBarVisibility(false);

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.on('ready', () => {
  startPythonServer();
  checkServerReady(() => {
    createWindow();
  });
});

app.on('window-all-closed', () => {
  // Terminate python server cleanly on exit
  if (pythonProcess) {
    console.log("Terminating backend server...");
    if (process.platform === 'win32') {
      spawn("taskkill", ["/pid", pythonProcess.pid, '/f', '/t']);
    } else {
      pythonProcess.kill('SIGINT');
    }
  }
  app.quit();
});
