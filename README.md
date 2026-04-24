# Signal Terminal

Browser-based news terminal with RSS scanning, signal scoring, focus filtering, and Gemini headline analysis.

## Local run

```powershell
powershell -ExecutionPolicy Bypass -File .\run_news_terminal.ps1
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Render deployment

1. Put this folder in a GitHub repository.
2. In Render, create a new Blueprint deployment and point it at that repo.
3. Render will detect [render.yaml](./render.yaml).
4. Add `GEMINI_API_KEY` in the Render environment settings.
5. Deploy.

The app serves:

- `/` for the terminal UI
- `/api/scan` for the news scan and AI analysis

## Notes

- The app uses Python's built-in HTTP server, so it is fine for lightweight personal use.
- Free hosting tiers may sleep after inactivity.
- Gemini analysis requires the `google-genai` package and a valid `GEMINI_API_KEY`.
