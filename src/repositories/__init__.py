"""
Data-access layer for the src/ pipeline.

Each module is a thin wrapper around SQL for one table. Functions take an open
psycopg2 cursor (RealDictCursor) as their first argument so callers can compose
several writes inside a single transaction (see services/ingestion.py).
"""
