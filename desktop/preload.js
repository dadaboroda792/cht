const { contextBridge } = require('electron');

const API = 'http://localhost:8787';

contextBridge.exposeInMainWorld('appApi', {
  login: () => window.open(`${API}/auth/google`, '_blank'),
  getMe: async () => {
    const r = await fetch(`${API}/auth/me`, { credentials: 'include' });
    return r.json();
  },
  chat: async (messages) => {
    const r = await fetch(`${API}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ messages })
    });
    return r.json();
  }
});
