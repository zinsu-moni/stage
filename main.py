from fastapi import FastAPI, HTTPException, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
import os
import random
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from db import SessionLocal, init_db
from schema import Base, Country, Meta
import service

load_dotenv()

app = FastAPI()


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Build a simple field -> message map from validation errors
    details = {}
    for err in exc.errors():
        loc = err.get("loc", [])
        # prefer the last location token as the field name
        field = loc[-1] if loc else "body"
        # collect message
        details[str(field)] = err.get("msg")
    return JSONResponse(status_code=400, content={"error": "Validation failed", "details": details})


@app.exception_handler(Exception)
async def internal_exception_handler(request: Request, exc: Exception):
    # Log could be added here. Return consistent 500 JSON
    return JSONResponse(status_code=500, content={"error": "Internal server error"})

# initialize DB (creates tables if missing)
init_db(Base)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class CountryOut(BaseModel):
    id: int
    name: str
    capital: Optional[str]
    region: Optional[str]
    population: int
    currency_code: Optional[str]
    exchange_rate: Optional[float]
    estimated_gdp: Optional[float]
    flag_url: Optional[str]
    last_refreshed_at: Optional[datetime]

    class Config:
        # Pydantic v2 renamed `orm_mode` -> `from_attributes`.
        # Use `from_attributes = True` for Pydantic v2 compatibility.
        # Keep only `from_attributes` to avoid the v2 warning.
        from_attributes = True


@app.post("/countries/refresh")
def refresh_countries(db: Session = Depends(get_db)):
    # fetch external data first
    ok_c, countries_data = service.fetch_countries()
    if not ok_c:
        return JSONResponse(status_code=503, content={"error": "External data source unavailable", "details": "Could not fetch data from Countries API"})

    ok_r, rates_data = service.fetch_exchange_rates()
    if not ok_r:
        return JSONResponse(status_code=503, content={"error": "External data source unavailable", "details": "Could not fetch data from Exchange Rates API"})

    # ensure expected structure
    rates = rates_data.get("rates") if isinstance(rates_data, dict) else None
    if rates is None:
        return JSONResponse(status_code=503, content={"error": "External data source unavailable", "details": "Exchange rates payload invalid"})

    # process and upsert in a transaction
    processed_count = 0
    now = datetime.now(timezone.utc)
    try:
        for c in countries_data:
            name = c.get("name")
            if not name:
                continue
            capital = c.get("capital")
            region = c.get("region")
            population = c.get("population") or 0
            flag = c.get("flag")

            currencies = c.get("currencies") or []
            if len(currencies) == 0:
                currency_code = None
                exchange_rate = None
                estimated_gdp = 0
            else:
                first = currencies[0] or {}
                currency_code = first.get("code")
                if not currency_code:
                    exchange_rate = None
                    estimated_gdp = 0
                else:
                    exchange_rate = rates.get(currency_code)
                    if exchange_rate is None:
                        estimated_gdp = None
                    else:
                        multiplier = random.randint(1000, 2000)
                        # avoid division by zero
                        try:
                            estimated_gdp = population * multiplier / float(exchange_rate)
                        except Exception:
                            estimated_gdp = None

            # upsert by case-insensitive name
            existing = db.query(Country).filter(func.lower(Country.name) == name.lower()).first()
            if existing:
                existing.capital = capital
                existing.region = region
                existing.population = population
                existing.currency_code = currency_code
                existing.exchange_rate = exchange_rate
                existing.estimated_gdp = estimated_gdp
                existing.flag_url = flag
                existing.last_refreshed_at = now
            else:
                new = Country(
                    name=name,
                    capital=capital,
                    region=region,
                    population=population,
                    currency_code=currency_code,
                    exchange_rate=exchange_rate,
                    estimated_gdp=estimated_gdp,
                    flag_url=flag,
                    last_refreshed_at=now,
                )
                db.add(new)
            processed_count += 1

        # update global meta
        meta = db.query(Meta).filter(Meta.key == "last_refreshed_at").first()
        iso_ts = now.isoformat()
        if meta:
            meta.value = iso_ts
        else:
            db.add(Meta(key="last_refreshed_at", value=iso_ts))

        db.commit()
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

    # generate summary image
    try:
        from PIL import Image, ImageDraw, ImageFont

        cache_dir = Path("cache")
        cache_dir.mkdir(exist_ok=True)
        img_path = cache_dir / "summary.png"

        total = db.query(func.count(Country.id)).scalar() or 0
        top5 = db.query(Country).filter(Country.estimated_gdp != None).order_by(Country.estimated_gdp.desc()).limit(5).all()

        # simple image
        w, h = (800, 600)
        im = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(im)
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

        y = 20
        draw.text((20, y), f"Countries: {total}", fill=(0, 0, 0), font=font)
        y += 30
        draw.text((20, y), f"Last refresh: {iso_ts}", fill=(0, 0, 0), font=font)
        y += 40
        draw.text((20, y), "Top 5 by estimated GDP:", fill=(0, 0, 0), font=font)
        y += 30
        for idx, c in enumerate(top5, start=1):
            draw.text((40, y), f"{idx}. {c.name} — {c.estimated_gdp:.2f}", fill=(0, 0, 0), font=font)
            y += 24

        im.save(img_path)
    except Exception:
        # image generation should not block successful refresh
        pass

    return {"success": True, "processed": processed_count, "last_refreshed_at": iso_ts}


@app.get("/countries", response_model=List[CountryOut])
def list_countries(
    region: Optional[str] = Query(None),
    currency: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Country)
    if region:
        q = q.filter(Country.region == region)
    if currency:
        q = q.filter(Country.currency_code == currency)
    if sort == "gdp_desc":
        q = q.order_by(Country.estimated_gdp.desc())
    elif sort == "gdp_asc":
        q = q.order_by(Country.estimated_gdp.asc())
    return q.all()


@app.get("/countries/{name}", response_model=CountryOut)
def get_country(name: str, db: Session = Depends(get_db)):
    c = db.query(Country).filter(func.lower(Country.name) == name.lower()).first()
    if not c:
        return JSONResponse(status_code=404, content={"error": "Country not found"})
    return c


@app.delete("/countries/{name}")
def delete_country(name: str, db: Session = Depends(get_db)):
    c = db.query(Country).filter(func.lower(Country.name) == name.lower()).first()
    if not c:
        return JSONResponse(status_code=404, content={"error": "Country not found"})
    db.delete(c)
    db.commit()
    return {"success": True}


@app.get("/status")
def status(db: Session = Depends(get_db)):
    total = db.query(func.count(Country.id)).scalar() or 0
    meta = db.query(Meta).filter(Meta.key == "last_refreshed_at").first()
    last = meta.value if meta else None
    return {"total_countries": total, "last_refreshed_at": last}


@app.get("/countries/image")
def get_image(db: Session = Depends(get_db)):
    path = Path("cache") / "summary.png"
    # If image already exists just serve it
    if path.exists():
        return FileResponse(str(path), media_type="image/png")

    # Attempt to generate the summary image on-demand from DB
    try:
        from PIL import Image, ImageDraw, ImageFont

        cache_dir = Path("cache")
        cache_dir.mkdir(exist_ok=True)
        img_path = cache_dir / "summary.png"

        total = db.query(func.count(Country.id)).scalar() or 0
        top5 = db.query(Country).filter(Country.estimated_gdp != None).order_by(Country.estimated_gdp.desc()).limit(5).all()

        # simple image
        w, h = (800, 600)
        im = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(im)
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

        y = 20
        meta = db.query(Meta).filter(Meta.key == "last_refreshed_at").first()
        iso_ts = meta.value if meta else None

        draw.text((20, y), f"Countries: {total}", fill=(0, 0, 0), font=font)
        y += 30
        draw.text((20, y), f"Last refresh: {iso_ts}", fill=(0, 0, 0), font=font)
        y += 40
        draw.text((20, y), "Top 5 by estimated GDP:", fill=(0, 0, 0), font=font)
        y += 30
        for idx, c in enumerate(top5, start=1):
            val = c.estimated_gdp or 0
            draw.text((40, y), f"{idx}. {c.name} — {val:.2f}", fill=(0, 0, 0), font=font)
            y += 24

        im.save(img_path)
        return FileResponse(str(img_path), media_type="image/png")
    except Exception:
        # If generation fails, return the standard 404 JSON
        return JSONResponse(status_code=404, content={"error": "Summary image not found"})
