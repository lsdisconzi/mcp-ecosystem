const path = require("path");

const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");

const { startDiscoveryServer } = require("../case-server/auto_server_builder");

const SERVER_PORT = Number(process.env.PORT || 0);

let mainWindow = null;
let discoveryServer = null;
let isShuttingDown = false;

async function stopDiscoveryServer() {
  if (!discoveryServer) return;
  const serverToClose = discoveryServer;
  discoveryServer = null;
  await new Promise((resolve) => serverToClose.close(resolve));
}

function createMainWindow() {
  if (!discoveryServer || !discoveryServer.listening) {
    throw new Error("Discovery server is not running");
  }

  const address = discoveryServer.address();
  const resolvedPort = typeof address === "object" && address ? address.port : SERVER_PORT;
  const startPath = (process.env.DISCOVERY_START_PATH || "/").replace(/^\/?/, "/");

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1120,
    minHeight: 760,
    autoHideMenuBar: true,
    backgroundColor: "#191917",
    title: "Discovery",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  return mainWindow.loadURL(`http://127.0.0.1:${resolvedPort}${startPath}`);
}

const handlePickFolder = async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openDirectory", "createDirectory"],
  });

  if (result.canceled || result.filePaths.length === 0) {
    return null;
  }

  return result.filePaths[0];
};

ipcMain.handle("discovery:pick-folder", handlePickFolder);

app.on("before-quit", () => {
  isShuttingDown = true;
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", async () => {
  if (BrowserWindow.getAllWindows().length === 0 && !isShuttingDown) {
    await createMainWindow();
  }
});

app.whenReady().then(async () => {
  const started = await startDiscoveryServer({ port: SERVER_PORT });
  discoveryServer = started.server;
  await createMainWindow();
}).catch(async (error) => {
  console.error("Failed to launch Discovery desktop app:", error);
  await stopDiscoveryServer();
  app.exit(1);
});

app.on("quit", () => {
  void stopDiscoveryServer();
});