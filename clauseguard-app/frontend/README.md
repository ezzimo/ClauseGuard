# ClauseGuard Frontend

React + Vite application for ClauseGuard.

## Setup

```powershell
cd clauseguard-app\frontend
npm install
```

## Run

```powershell
npm run dev
```

The dev server runs on `http://localhost:5173` and calls the backend at `http://localhost:8000`.

## Build

```powershell
npm run build
```

## Pages

- `/` — Upload contract with context form
- `/review/:contractId` — Human-in-the-loop review of clauses
- `/report/:contractId` — Final report with export JSON
