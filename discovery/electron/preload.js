const { contextBridge, ipcRenderer } = require("electron");

const desktopApi = {
  isDesktop: true,
  platform: process.platform,
  pickFolder: () => ipcRenderer.invoke("discovery:pick-folder"),
};

contextBridge.exposeInMainWorld("discoveryDesktop", desktopApi);