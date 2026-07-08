from app.supabase_client import supabase

response = supabase.table("bars").select("*").limit(1).execute()

print(response.data)

print("Connected Successfully")