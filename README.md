# NyayaNLP — AI Hallucination Detector

Research-oriented system that verifies LLM answers using multi-source evidence (Wikipedia, Wikidata, RestCountries, curated facts) and **Nyaya Shastra**-inspired explainability (Pratyaksha, Shabda, Anumana, Nigrahasthana).

## Features

- Question-anchored claim extraction and verification
- Hybrid lexical + semantic scoring
- Leadership/office queries (`pm of india` ≡ `prime minister of india`; vice president vs president disambiguation)
- Curated geopolitical facts with external-source fallback
- Web UI with Nyaya verdict display

## Project structure

| Path | Description |
|------|-------------|
| `backend/` | FastAPI API and `NyayaVerifier` |
| `frontend/` | Static web UI (`index_v2.html`) |
| `data/curated_facts/` | Curated country/geopolitical JSON |
| `scripts/` | Utility scripts |
| `docs/` | Documentation |

## Requirements

- Python 3.10+ (3.11+ recommended)
- [Ollama](https://ollama.com/) (optional, for local LLM generation)
- Internet access for Wikipedia / Wikidata / RestCountries

## Local setup

```bash
# From project root
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
python -m spacy download en_core_web_sm

copy .env.example .env   # Windows
# cp .env.example .env   # macOS / Linux
```

### Run backend

```bash
# From project root (folder that contains backend/)
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

### Run frontend

Serve the `frontend/` folder with any static server, for example:

```bash
cd frontend
python -m http.server 5500
```

Open http://localhost:5500/index_v2.html — the UI calls the API at `http://localhost:8000` (see `frontend/app.js`).

## Environment variables

Copy `.env.example` to `.env`. Never commit `.env`.

| Variable | Purpose |
|----------|---------|
| `SIMILARITY_THRESHOLD` | Semantic similarity floor (default `0.25`) |
| `OLLAMA_HOST` | Ollama base URL (optional) |

## Tests

```bash
pip install pytest
python -m pytest backend/tests/ -q
```

## Push to GitHub

1. Create a new repository on [GitHub](https://github.com/new) (e.g. `nyay-nlp`). Do **not** add a README if this folder already has one.
2. From the project root:

```bash
git init
git add .
git commit -m "Initial commit: NyayaNLP hallucination verifier"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

Replace `YOUR_USERNAME` and `YOUR_REPO` with your GitHub username and repository name.

### SSH instead of HTTPS

```bash
git remote add origin git@github.com:YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

## What is not in the repo

- `venv/` — create locally after clone
- `.env` — secrets and local config
- `data/results/*` — generated benchmark outputs (structure kept via `.gitignore`)

## License

Add your institute/project license here if required for submission.
