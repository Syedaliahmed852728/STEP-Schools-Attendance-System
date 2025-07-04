import logging
from config import Config
from utils import with_sql_cursor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_all_classes():
    query = "SELECT class_id, class_name, session, section FROM class_table"
    with with_sql_cursor() as (_, cur):
        cur.execute(query)
        class_rows = cur.fetchall()
    
    if class_rows is None:
        return None
    
    classes = []

    for class_row in class_rows:
        classes.append({
            "class_id": class_row["class_id"],
            "class_name": class_row["class_name"],
            "session": class_row["session"],
            "section": class_row["section"],
        })
    return classes
