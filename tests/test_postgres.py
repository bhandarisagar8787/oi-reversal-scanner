from sqlalchemy import text
from app.database.client import get_engine

engine = get_engine()

print("Connecting to PostgreSQL...")

with engine.connect() as conn:
    result = conn.execute(text("SELECT current_database(), current_user, version();"))
    row = result.fetchone()

print("\nConnected Successfully!\n")
print(f"Database : {row[0]}")
print(f"User     : {row[1]}")
print(f"Version  : {row[2][:80]}...")