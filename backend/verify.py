from config import settings
from sqlalchemy import create_engine

print(f"--- ATTENTION ---")
print(f"I am trying to connect to: {settings.DATABASE_URL}")

engine = create_engine(settings.DATABASE_URL)
try:
    with engine.connect() as conn:
        print("SUCCESS: The database accepted the connection!")
except Exception as e:
    print(f"FAILURE: The database said: {e}")