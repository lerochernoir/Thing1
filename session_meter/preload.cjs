// Bridge between the sandboxed window and the main process: state in, commands out.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("meter", {
  onState: (fn) => ipcRenderer.on("state", (_e, s) => fn(s)),
  send: (cmd, arg) => ipcRenderer.send("cmd", cmd, arg),
});
