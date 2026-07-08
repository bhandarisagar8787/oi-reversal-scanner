from app.database.supabase import db

response = db.table("bars").select("*").limit(1).execute()

print("Connection OK")
print(response.data)