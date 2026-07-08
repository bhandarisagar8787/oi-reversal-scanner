from app.database.client import db
from app.database.schema import BARS

def check_connection():

    result = db.table(BARS).select("*").limit(1).execute()

    return result.data