# Chat Codex Desktop (Windows-ready)

Приложение с интерфейсом в стиле Codex: боковая панель, чат-область и composer для задач по коду.

## 1) Запуск в режиме разработки (Windows)
Откройте 2 окна PowerShell.

### Окно 1 (backend)
```powershell
cd C:\path\to\cht
copy .env.example backend\.env
# заполните backend\.env своими ключами
npm install
npm run dev -w backend
```

### Окно 2 (desktop)
```powershell
cd C:\path\to\cht
npm run dev -w desktop
```

## 2) Сборка .exe для Windows
После `npm install` выполните:
```powershell
npm run build -w desktop
```

Готовый инсталлятор `.exe` появится в:
- `desktop\dist\`

## Важно по Google Login
- В Google Cloud Console добавьте callback URL:
  - `http://localhost:8787/auth/google/callback`
- В `backend/.env` укажите:
  - `GOOGLE_CLIENT_ID`
  - `GOOGLE_CLIENT_SECRET`
  - `OPENAI_API_KEY`
  - `SESSION_SECRET`
