# Minara (Phase 1)

Minara is an AI-powered video clipping tool for Islamic content. **Phase 1** only: paste a YouTube URL and get a transcript with **word-level timestamps** (JSON from the backend via [AssemblyAI](https://www.assemblyai.com/), shown in the web UI). The response shape matches the earlier OpenAI-style payload (`text`, `words`, etc.) so the frontend stays unchanged.

Later phases may add clip selection, cutting, overlays, and Quran-aware features. There is no database, auth, or deployment in Phase 1.

## What you need installed

1. **Python 3.10+** — check with `python3 --version`
2. **Node.js** (LTS) — check with `node --version`
3. **ffmpeg** — required for `yt-dlp` to extract audio  
   - macOS (Homebrew): `brew install ffmpeg`  
   - Then verify: `ffmpeg -version`
4. **AssemblyAI API key** — used only on the backend (never exposed to the browser)

### AssemblyAI API key (beginner steps)

1. Sign up at [assemblyai.com](https://www.assemblyai.com/) and open your dashboard.
2. Copy your **API key** (keep it private).
3. Paste it into `backend/.env` as `ASSEMBLYAI_API_KEY=...` (see below).

Transcription uses speech models **`universal-3-pro`** with fallback to **`universal-2`** (required by AssemblyAI for broad language support). See [AssemblyAI pricing](https://www.assemblyai.com/pricing) for usage costs.

## Project layout

- `backend/` — FastAPI app: `POST /transcribe` (YouTube URL → download audio → AssemblyAI → JSON).
- `frontend/` — Next.js app: one page that calls the backend and displays the transcript.

## Backend setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `backend/.env` and set:

```bash
ASSEMBLYAI_API_KEY=your-assemblyai-key-here
```

Run the API:

```bash
cd backend
source .venv/bin/activate
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Interactive docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## Frontend setup

```bash
cd frontend
cp env.example .env.local
npm install
```

`NEXT_PUBLIC_API_URL` in `.env.local` should point at your API (default `http://127.0.0.1:8000`).

Run the app:

```bash
cd frontend
npm run dev
```

Open the URL shown (usually [http://localhost:3000](http://localhost:3000)).

## Typical workflow

1. Terminal A: activate venv and run `uvicorn` in `backend/`.
2. Terminal B: run `npm run dev` in `frontend/`.
3. Paste a YouTube URL and transcribe.

## Note on git

`create-next-app` may have created a git repo inside `frontend/`. For one repository at the project root, you can remove `frontend/.git` and run `git init` in the `minara` folder if you like.
