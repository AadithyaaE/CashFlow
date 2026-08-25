import os

from sqlalchemy import create_engine
from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker, declarative_base


load_dotenv()
# Production points this at Postgres (Neon) via the DATABASE_URL env var —
# see backend/.env.example. Falls back to a local SQLite file so the app and
# `alembic upgrade head` both still work out of the box with zero setup.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cashpilot.db")

connect_args = (
    {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()