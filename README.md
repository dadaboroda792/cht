# Chat Codex Desktop

Desktop-приложение в стиле ChatGPT + функции код-ассистента (через OpenAI API), с логином через Google OAuth.

## Что внутри
- `desktop/` — Electron клиент.
- `backend/` — Node.js backend (Google OAuth + chat endpoint).

## Быстрый старт
1. Создайте OAuth credentials в Google Cloud (Web app).
2. Для backend callback укажите: `http://localhost:8787/auth/google/callback`.
3. Скопируйте `.env.example` в `backend/.env` и заполните.
4. Установите зависимости:
   ```bash
   npm install
   ```
5. Запустите backend:
   ```bash
   npm run dev -w backend
   ```
6. Запустите desktop:
   ```bash
   npm run dev -w desktop
   ```

## Что дальше
- Добавить локальные tools (файлы/команды) для полноценного codex-режима.
- Добавить хранение истории чатов в БД.
- Сделать packaging (electron-builder) под Windows/macOS/Linux.
