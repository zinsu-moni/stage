import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv
from urllib.parse import urlsplit, parse_qs, urlunsplit

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    # fallback to a local sqlite for development if not configured
    DATABASE_URL = "sqlite:///./local.db"

# If the URL uses the generic mysql:// scheme, prefer the pymysql driver
# which is pure-Python and already listed in requirements.txt. Otherwise
# SQLAlchemy may try to import MySQLdb (mysqlclient) which may not be installed.
if DATABASE_URL.startswith("mysql://"):
    DATABASE_URL = DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)

# Some provider URLs (e.g. Aiven) append query parameters like `ssl-mode=REQUIRED`.
# SQLAlchemy will pass these as keyword args to the DBAPI connect function which
# can result in errors (e.g. `ssl-mode` is not a valid Python identifier). To avoid
# that, strip the query string and translate known params into connect_args.
connect_args = {}
try:
    parts = urlsplit(DATABASE_URL)
    if parts.query:
        qs = parse_qs(parts.query)
        # handle ssl-mode → pass an ssl dict to pymysql (empty dict requests TLS)
        ssl_mode = qs.get("ssl-mode") or qs.get("ssl_mode")
        if ssl_mode:
            # instruct pymysql to use SSL/TLS; an empty dict is commonly accepted
            # to enable TLS when the server requires it. If your provider needs CA
            # files, adjust to pass {'ca': '/path/to/ca.pem'} here.
            connect_args["ssl"] = {}

        # rebuild URL without the query portion so SQLAlchemy doesn't forward
        # unknown kwargs to the DBAPI.
        DATABASE_URL = urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))
except Exception:
    # if parsing fails, continue with the original DATABASE_URL
    pass

# create engine
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(Base):
    """Create tables. Call with schema.Base."""
    try:
        Base.metadata.create_all(bind=engine)
    except SQLAlchemyError:
        raise
