import sqlite3
from dotenv import load_dotenv
import os
from pathlib import Path
from config import Config

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
                class_id TEXT,
                parent_id TEXT,
                FOREIGN KEY (class_id)   REFERENCES class_table(class_id),
                FOREIGN KEY (parent_id)  REFERENCES parent_table(parent_id)
            );
        """,
        "columns": {
            "stud_id":      "TEXT PRIMARY KEY",
            "stud_name":    "TEXT NOT NULL",
            "class_id":     "TEXT",
            "parent_id":    "TEXT"
        }
    },
    "fee_table": {
        "create_sql": """
            CREATE TABLE IF NOT EXISTS fee_table (
                fee_id TEXT PRIMARY KEY,
                challan_no TEXT,
                paid_data TEXT,
                month_name TEXT,
                status TEXT,
                amount TEXT,
                stud_id TEXT,
                FOREIGN KEY (stud_id) REFERENCES student_table(stud_id)
            );
        """,
        "columns": {
            "fee_id":     "TEXT PRIMARY KEY",
            "challan_no": "TEXT",
            "paid_data":  "TEXT",
            "month_name": "TEXT",
            "status":     "TEXT",
            "amount":     "TEXT",
            "stud_id":    "TEXT"
        }
    },

    "attendance_table": {
        "create_sql": """
            CREATE TABLE IF NOT EXISTS attendance_table (
                stud_id TEXT,
                date_full TEXT,
                arrival_time TEXT,
                departure_time TEXT,
                status TEXT CHECK(status IN ('Present', 'Absent', 'Off')),
                FOREIGN KEY (stud_id) REFERENCES student_table(stud_id)
            );
        """,
        "columns": {
            "stud_id":        "TEXT",
            "date_full":      "TEXT",
            "arrival_time":   "TEXT",
            "departure_time": "TEXT",
            "status":         "TEXT CHECK(status IN ('Present', 'Absent', 'Off'))"
        }
    },

    "promoted_table": {
        "create_sql": """
            CREATE TABLE IF NOT EXISTS promoted_table (
                promoted_id   TEXT PRIMARY KEY,             
                stud_id       TEXT NOT NULL,
                parent_id     TEXT NOT NULL,
                session       TEXT NOT NULL,
                class_name    TEXT NOT NULL,
                student_name  TEXT NOT NULL,
                parent_name   TEXT,
                total_present INTEGER,
                total_absent  INTEGER,
                fee_status    TEXT
            );
        """,
        "columns": {
            "promoted_id":   "TEXT PRIMARY KEY",
            "stud_id":       "TEXT NOT NULL",
            "parent_id":     "TEXT NOT NULL",
            "session":       "TEXT NOT NULL",
            "class_name":    "TEXT NOT NULL",
            "student_name":  "TEXT NOT NULL",
            "parent_name":   "TEXT",
            "total_present": "INTEGER",
            "total_absent":  "INTEGER",
            "fee_status":    "TEXT"
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


db_path = Config.STORAGE_PATH

# chking if the database exists or not
Path(db_path).mkdir(parents=True, exist_ok=True)
full_db_path = Config.DB
full_mark_left_db_path = Config.LEFT_DB
# full_promoted_student_prev_db_path = Config.PROMOTED_DB

database_creation(full_db_path=full_db_path, schemas=SCHEMAS)

database_creation(full_db_path=full_mark_left_db_path, schemas=SCHEMAS)




