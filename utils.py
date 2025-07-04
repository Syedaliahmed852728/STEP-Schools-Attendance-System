import sqlite3
from contextlib import contextmanager
from pathlib import Path
from database_creation import database_creation, SCHEMAS
from config import Config
import pickle
import logging


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


database_creation(full_db_path=Config.DB, schemas=SCHEMAS)

@contextmanager
def with_sql_cursor():
    conn = sqlite3.connect(Config.DB)
    conn.row_factory = sqlite3.Row
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


@contextmanager
def archive_db_cursor():
    conn = sqlite3.connect(Config.LEFT_DB)
    conn.row_factory = sqlite3.Row
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


class VectorStore:
    def __init__(self, path: Path):
        self.path = path
        self._store = None

    def load(self):
        if self._store is None:
            if self.path.exists():
                try:
                    with open(self.path, 'rb') as f:
                        self._store = pickle.load(f)
                        logger.info(f"Loaded vector store with {len(self._store)} entries.")
                except Exception as e:
                    logger.warning(f"Failed to load vector store: {e}")
                    self._store = {}
            else:
                self._store = {}
                logger.info("Initialized empty vector store.")
        return self._store

    def exists(self, stud_id: str) -> bool:
        return stud_id in self.load()

    def add(self, stud_id: str, encoding: list[float]) -> None:
        store = self.load()
        store[stud_id] = encoding
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, 'wb') as f:
                pickle.dump(store, f)
            logger.info(f"Saved encoding for ID {stud_id}.")
        except Exception as e:
            logger.error(f"Failed to save encoding for {stud_id}: {e}")

    def all(self):
        return self.load()
    





with with_sql_cursor() as (conn, cur):
    # ensure you're using the Row factory (it sounds like you already are)
    conn.row_factory = sqlite3.Row  
    cur = conn.cursor()

    cur.execute("SELECT * FROM attendance_table")
    rows = cur.fetchall()

    for row in rows:
        # as a dict, so you see column names and values:
        print(dict(row))