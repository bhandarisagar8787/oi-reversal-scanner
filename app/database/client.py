from supabase import create_client
from app.config import settings

if not settings.SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL missing")

if not settings.SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY missing")

db = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_KEY
)