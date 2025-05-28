import sqlite3
from contextlib import contextmanager
from pathlib import Path
import os
from database_creation import database_creation, SCHEMAS

db_path = os.getenv("DB_PATH") 
db_name = os.getenv("DB_NAME")     

# chking if the database exists or not
Path(db_path).mkdir(parents=True, exist_ok=True)
full_db_path = os.path.join(db_path, f"{db_name}.sqlite3")

database_creation(full_db_path=full_db_path, schemas=SCHEMAS)

@contextmanager
def with_sql_cursor():
    conn = sqlite3.connect(full_db_path)
    cur = conn.cursor()
    try:
        yield conn, cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
