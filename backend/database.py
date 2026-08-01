import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Overridable so a persistent disk path can be used in production (SQLite's
# file otherwise lives on the app server's ephemeral filesystem and is lost
# on every redeploy/restart).
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cashpilot.db")

connect_args = (
    {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()