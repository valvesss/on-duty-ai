// Tells the engine this tab is open. The engine quits when the last tab closes.
(() => {
  const id = Math.random().toString(36).slice(2);
  const send = (path) => navigator.sendBeacon(path, new Blob([JSON.stringify({ tab: id })], { type: 'application/json' }));
  send('/api/ping');
  setInterval(() => send('/api/ping'), 10000);
  addEventListener('pagehide', () => send('/api/bye'));
  addEventListener('pageshow', () => send('/api/ping'));
})();
