# Country Currency & Exchange API

This FastAPI service fetches country data and exchange rates, computes estimated GDP values, caches them in a database, and provides CRUD + status + image endpoints.

Quick start

1. Copy `.env.example` to `.env` and set `DATABASE_URL` and `PORT`.
2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Run the app (development):

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000
```

Endpoints

- POST /countries/refresh — fetch external APIs and cache/update DB
- GET /countries — list countries (filters: ?region=Africa, ?currency=NGN, ?sort=gdp_desc)
- GET /countries/{name} — get a country by name (case-insensitive)
- DELETE /countries/{name} — delete a country
- GET /status — returns total countries and last refresh timestamp
- GET /countries/image — serves generated summary image (cache/summary.png)

Notes

- The project uses SQLAlchemy and reads `DATABASE_URL` from `.env`. If not provided, a local `sqlite` file will be used.
- Image generation uses Pillow and is saved to `cache/summary.png` after a successful refresh.
- If an external API is unavailable, `/countries/refresh` returns 503 and the DB is not modified.
