import sqlite3
from dotenv import load_dotenv
import os
from pathlib import Path

load_dotenv()

# first e define the database schema
SCHEMAS = {
    "class_table": {
        "create_sql": """
            CREATE TABLE IF NOT EXISTS class_table (
                class_id TEXT PRIMARY KEY,
                class_name TEXT NOT NULL,
                session TEXT NOT NULL,
                section TEXT
            );
        """,
        "columns": {
            "class_id": "TEXT PRIMARY KEY",
            "class_name": "TEXT NOT NULL",
            "session":    "TEXT NOT NULL",
            "section":    "TEXT"
        }
    },
    "parent_table": {
        "create_sql": """
            CREATE TABLE IF NOT EXISTS parent_table (
                parent_id TEXT PRIMARY KEY,
                parent_name TEXT,
                parent_contact_number TEXT
            );
        """,
        "columns": {
            "parent_id":             "TEXT PRIMARY KEY",
            "parent_name":           "TEXT",
            "parent_contact_number": "TEXT"
        }
    },
    "student_table": {
        "create_sql": """
            CREATE TABLE IF NOT EXISTS student_table (
                stud_id TEXT PRIMARY KEY,
                stud_name TEXT NOT NULL,
                stud_section TEXT,
                class_id TEXT,
                parent_id TEXT,
                FOREIGN KEY (class_id)   REFERENCES class_table(class_id),
                FOREIGN KEY (parent_id)  REFERENCES parent_table(parent_id)
            );
        """,
        "columns": {
            "stud_id":      "TEXT PRIMARY KEY",
            "stud_name":    "TEXT NOT NULL",
            "stud_section": "TEXT",
            "class_id":     "TEXT",
            "parent_id":    "TEXT"
        }
    },
    "fee_table": {
        "create_sql": """
            CREATE TABLE IF NOT EXISTS fee_table (
                fee_id TEXT PRIMARY KEY,
                paid_data TEXT,
                month_name TEXT,
                status TEXT NOT NULL,
                stud_id TEXT,
                FOREIGN KEY (stud_id) REFERENCES student_table(stud_id)
            );
        """,
        "columns": {
            "fee_id":     "TEXT PRIMARY KEY",
            "paid_data":  "TEXT",
            "month_name": "TEXT",
            "status":     "TEXT NOT NULL",
            "stud_id":    "TEXT"
        }
    }
}

def get_existing_columns(cursor, table_name):
    cursor.execute(f"PRAGMA table_info({table_name});")
    return {row[1] for row in cursor.fetchall()}

def database_creation(full_db_path: str, schemas: dict):
    def get_existing_columns(cursor, table_name):
        cursor.execute(f"PRAGMA table_info({table_name});")
        return {row[1] for row in cursor.fetchall()}

    something_changed = False
    try:
        with sqlite3.connect(full_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")

            for table, info in schemas.items():
                cursor.execute(info["create_sql"])
                existing = get_existing_columns(cursor, table)
                for col_name, col_def in info["columns"].items():
                    if col_name not in existing:
                        sql = f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def};"
                        cursor.execute(sql)
                        something_changed = True
                        print(f"Added column '{col_name}' to '{table}'")

            conn.commit()

        if something_changed:
            print("database updated.")
        else:
            print("database is already up-to-date.")

    except sqlite3.OperationalError as e:
        print("database operation failed:", e)


# db_path = os.getenv("DB_PATH") 
# db_name = os.getenv("DB_NAME")     

# # chking if the database exists or not
# Path(db_path).mkdir(parents=True, exist_ok=True)
# full_db_path = os.path.join(db_path, f"{db_name}.sqlite3")

# database_creation(full_db_path=full_db_path, schemas=SCHEMAS)