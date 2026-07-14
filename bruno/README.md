# VietLegalGraphRAG API Bruno Collection

Run the backend first:

```powershell
Set-Location -LiteralPath 'D:\Y3S2\[ML]_VietLegalGraphRAG'
conda run -n ml_env python -m dotenv -f .env run -- python -m uvicorn main:app --host 127.0.0.1 --port 8000 --app-dir src/backend/app
```

Then open this `bruno` folder in Bruno and select the `Local` environment.

CLI smoke:

```powershell
bru run --env Local
```

The collection does not store API keys. External credentials are read only by the backend from `.env`.
