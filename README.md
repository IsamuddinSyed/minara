# Minara (Phase 1 +2)

Minara is an AI-powered video clipping tool for Islamic content. **Phase 1:** paste a YouTube URL and get a transcript with **word-level timestamps** (via [AssemblyAI](https://www.assemblyai.com/)). **Phase 2:** send that transcript to **`POST /identify-moments`** to get **3–5 clip-worthy moments** scored by OpenAI **`gpt-4o`** (key moments only—no video cutting yet).

There is no database, auth, or deployment in these phases.

## What you need installed

1. **Python 3.10+** — check with `python3 --version`
2. **Node.js** (LTS) — check with `node --version`
3. **ffmpeg** — required for `yt-dlp` to extract audio  
   - macOS (Homebrew): `brew install ffmpeg`  
   - Then verify: `ffmpeg -version`
4. **AssemblyAI API key** — transcription (`/transcribe`), backend only  
5. **OpenAI API key** — key-moment identification (`/identify-moments`), backend only

### AssemblyAI API key (beginner steps)

1. Sign up at [assemblyai.com](https://www.assemblyai.com/) and open your dashboard.
2. Copy your **API key** (keep it private).
3. Paste it into `backend/.env` as `ASSEMBLYAI_API_KEY=...` (see below).

Transcription uses speech models **`universal-3-pro`** with fallback to **`universal-2`** (required by AssemblyAI for broad language support). See [AssemblyAI pricing](https://www.assemblyai.com/pricing) for usage costs.

### OpenAI API key (Phase 2)

Create a key at [platform.openai.com](https://platform.openai.com/) and add to `backend/.env` as `OPENAI_API_KEY=...`. The app uses model **`gpt-4o`** for moment identification.

## Project layout

- `backend/` — FastAPI: `POST /transcribe`, `POST /identify-moments`.
- `frontend/` — Next.js: transcribe UI and **Find Key Moments** cards.

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
OPENAI_API_KEY=your-openai-key-here
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
3. Paste a YouTube URL and transcribe, then use **Find Key Moments** (requires `OPENAI_API_KEY`).

## Note on git

`create-next-app` may have created a git repo inside `frontend/`. For one repository at the project root, you can remove `frontend/.git` and run `git init` in the `minara` folder if you like.
