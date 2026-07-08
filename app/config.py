from dotenv import load_dotenv
import os

load_dotenv()

class Settings:

    SUPABASE_URL = os.getenv("SUPABASE_URL")

    SUPABASE_KEY = os.getenv("SUPABASE_KEY")

settings = Settings()