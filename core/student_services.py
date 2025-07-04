import cv2
import logging
import face_recognition
from config import Config
from utils import with_sql_cursor,archive_db_cursor ,VectorStore
from pathlib import Path
from core.class_services import get_all_classes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


vector_store = VectorStore(Path(Config.VECTOR_STORE_FILE))


def process_image(filepath: Path):
    # filepath: Path to image file
    image = cv2.imread(str(filepath))
    if image is None:
        logger.warning(f"Cannot read image: {filepath}")
        return None

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    scale = Config.MAX_IMAGE_DIMENSION / max(h, w)
    if scale < 1:
        rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        logger.debug(f"Resized {filepath} to {rgb.shape[1]}x{rgb.shape[0]}")

    faces = face_recognition.face_locations(rgb, model=Config.FACE_DETECTION_MODEL)
    if not faces:
        logger.warning(f"No face found in {filepath.name}")
        return None

    top, right, bottom, left = max(
        faces, key=lambda loc: (loc[2]-loc[0])*(loc[1]-loc[3])
    )
    encodings = face_recognition.face_encodings(
        rgb,
        known_face_locations=[(top, right, bottom, left)],
        num_jitters=Config.NUM_ENCODING_JITTERS
    )
    if not encodings:
        logger.warning(f"Failed to encode face in {filepath.name}")
        return None

    return encodings[0].tolist(), (top, right, bottom, left)


def add_the_new_student(
    stud_id: str,
    stud_name: str,
    session: str,
    stud_class: str,
    parent_name: str,
    parent_cnic: str,
    parent_contact: str,
    section: str | None = None,
    img_path: Path | None = None,
) -> None:
    class_id = f"{stud_class}-{section}-{session}" if section else f"{stud_class}-{session}"

    with with_sql_cursor() as (conn, cursor):
        cursor.execute("SELECT stud_id FROM student_table WHERE stud_id = ?", (stud_id,))
        if cursor.fetchone():
            raise ValueError(f"Student '{stud_id}' already exists.")
        cursor.execute("SELECT class_id FROM class_table WHERE class_id = ?", (class_id,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO class_table (class_id, class_name, session, section) VALUES (?, ?, ?, ?)",
                (class_id, stud_class, session, section)
            )
        cursor.execute("SELECT parent_id FROM parent_table WHERE parent_id = ?", (parent_cnic,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO parent_table (parent_id, parent_name, parent_contact_number) VALUES (?, ?, ?)",
                (parent_cnic, parent_name, parent_contact)
            )
        cursor.execute(
            "INSERT INTO student_table (stud_id, stud_name, class_id, parent_id) VALUES (?, ?, ?, ?)",
            (stud_id, stud_name, class_id, parent_cnic)
        )
        logger.info(f"Inserted student {stud_id} into database.")

    if img_path:
        result = process_image(img_path)
        if result:
            encoding, face_box = result
            vector_store.add(stud_id, encoding)
        else:
            logger.error(f"Failed to process image for {stud_id}.")


def get_all_students():
    query = """
    WITH latest_fee AS (
        SELECT 
            stud_id, 
            MAX(paid_data) AS max_paid_data
        FROM fee_table
        WHERE paid_data IS NOT NULL
        GROUP BY stud_id
    )
    SELECT
        s.stud_id AS stud_id,
        s.stud_name AS stud_name,
        c.class_name AS stud_class_name,
        c.section AS stud_class_section,
        c.session AS stud_class_session,
        p.parent_id AS stud_parent_id,
        p.parent_name AS stud_parent_name,
        p.parent_contact_number AS stud_parent_contact_number,
        f.status AS stud_fee_status
    FROM student_table AS s
    LEFT JOIN class_table AS c
        ON s.class_id = c.class_id
    LEFT JOIN parent_table AS p
        ON s.parent_id = p.parent_id
    LEFT JOIN latest_fee AS lf
        ON s.stud_id = lf.stud_id
    LEFT JOIN fee_table AS f
        ON f.stud_id = lf.stud_id
       AND f.paid_data = lf.max_paid_data
    ;
    """
    with with_sql_cursor() as (_, cur):
        cur.execute(query)
        rows = cur.fetchall()
    # Convert sqlite3.Row to dict
    students = []
    for row in rows:
        # sqlite3.Row allows dict-like access
        students.append({
            "stud_id": row["stud_id"],
            "stud_name": row["stud_name"],
            "stud_class_name": row["stud_class_name"],
            "stud_class_section": row["stud_class_section"],
            "stud_class_session": row["stud_class_session"],
            "stud_parent_id": row["stud_parent_id"],
            "stud_parent_name": row["stud_parent_name"],
            "stud_parent_contact_number": row["stud_parent_contact_number"],
            "stud_fee_status": row["stud_fee_status"],
        })
    return students


def get_student(student_id: str):
    query = """
    WITH latest_fee AS (
        SELECT 
            stud_id, 
            MAX(paid_data) AS max_paid_data
        FROM fee_table
        WHERE paid_data IS NOT NULL
        GROUP BY stud_id
    )
    SELECT
        s.stud_id AS stud_id,
        s.stud_name AS stud_name,
        c.class_name AS stud_class_name,
        c.section AS stud_class_section,
        c.session AS stud_class_session,
        p.parent_id AS stud_parent_id,
        p.parent_name AS stud_parent_name,
        p.parent_contact_number AS stud_parent_contact_number,
        f.status AS stud_fee_status
    FROM student_table AS s
    LEFT JOIN class_table AS c
        ON s.class_id = c.class_id
    LEFT JOIN parent_table AS p
        ON s.parent_id = p.parent_id
    LEFT JOIN latest_fee AS lf
        ON s.stud_id = lf.stud_id
    LEFT JOIN fee_table AS f
        ON f.stud_id = lf.stud_id
       AND f.paid_data = lf.max_paid_data
    WHERE s.stud_id = ?
    LIMIT 1
    ;
    """
    with with_sql_cursor() as (_, cur):
        cur.execute(query, (student_id,))
        row = cur.fetchone()
    if row is None:
        return None
    
    return {
        "stud_id": row["stud_id"],
        "stud_name": row["stud_name"],
        "stud_class_name": row["stud_class_name"],
        "stud_class_section": row["stud_class_section"],
        "stud_class_session": row["stud_class_session"],
        "stud_parent_id": row["stud_parent_id"],
        "stud_parent_name": row["stud_parent_name"],
        "stud_parent_contact_number": row["stud_parent_contact_number"],
        "stud_fee_status": row["stud_fee_status"],
    }


def prepare_student_index_data(with_sql_cursor, args) -> dict:
    """
    Gather data for the student index template based on request args.
    - get_all_classes: callable returning list of class dicts.
    - with_sql_cursor: context manager for database access.
    - args: request.args or a dict-like with keys "class_name", "section", "search_id".
    Returns a dict with:
      - class_names: sorted list of distinct class_name
      - sections: set of section values (possibly including None or "")
      - students: list of student dicts from DB
      - selected_class_name, selected_section, search_id: cleaned strings
    """
    # 1. Load all classes and distinct class names
    classes_data = get_all_classes()
    class_names = sorted({cls["class_name"] for cls in classes_data if cls.get("class_name")})

    # 2. Extract and clean filters from args
    selected_class_name = args.get("class_name", default="", type=str).strip() if hasattr(args, 'get') else str(args.get("class_name", "")).strip()
    selected_section = args.get("section", default="", type=str).strip() if hasattr(args, 'get') else str(args.get("section", "")).strip()
    search_id = args.get("search_id", default="", type=str).strip() if hasattr(args, 'get') else str(args.get("search_id", "")).strip()

    # 3. Build section_values based on selected_class_name
    section_values: set = set()
    if selected_class_name:
        for cls in classes_data:
            if cls.get("class_name") == selected_class_name:
                sec = cls.get("section", None)
                section_values.add(sec)
    else:
        for cls in classes_data:
            sec = cls.get("section", None)
            section_values.add(sec)

    # 4. Build SQL query with latest_fee CTE
    query = """
    WITH latest_fee AS (
        SELECT stud_id, MAX(paid_data) AS max_paid_data
        FROM fee_table
        WHERE paid_data IS NOT NULL
        GROUP BY stud_id
    )
    SELECT
        s.stud_id AS stud_id,
        s.stud_name AS stud_name,
        c.class_name AS stud_class_name,
        c.section    AS stud_class_section,
        c.session    AS stud_class_session,
        f.status     AS stud_fee_status
    FROM student_table s
    LEFT JOIN class_table c ON s.class_id = c.class_id
    LEFT JOIN latest_fee lf ON s.stud_id = lf.stud_id
    LEFT JOIN fee_table f
      ON f.stud_id = lf.stud_id AND f.paid_data = lf.max_paid_data
    """
    filters = []
    params: dict = {}
    if selected_class_name:
        filters.append("c.class_name = :class_name")
        params["class_name"] = selected_class_name
    if selected_section:
        if selected_section == "__none__":
            filters.append("(c.section IS NULL OR c.section = '')")
        else:
            filters.append("c.section = :section")
            params["section"] = selected_section
    if search_id:
        filters.append("s.stud_id = :search_id")
        params["search_id"] = search_id

    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY s.stud_name COLLATE NOCASE"

    # 5. Execute query
    with with_sql_cursor() as (_, cur):
        cur.execute(query, params)
        rows = cur.fetchall()
    students = [dict(r) for r in rows]

    return {
        "class_names": class_names,
        "sections": section_values,
        "students": students,
        "selected_class_name": selected_class_name,
        "selected_section": selected_section,
        "search_id": search_id,
    }


def update_the_student(
    stud_id: str,
    stud_name: str,
    session: str,
    stud_class: str,
    parent_name: str,
    parent_cnic: str,
    parent_contact: str,
    section: str | None = None,
    img_path: str | None = None,
):
    # 1. Compute class_id
    if section:
        class_id = f"{stud_class}-{section}-{session}"
    else:
        class_id = f"{stud_class}-{session}"

    parent_id = parent_cnic  # as specified

    # 2. Upsert class_table
    # Using SQLite UPSERT syntax: ON CONFLICT(class_id) DO UPDATE ...
    upsert_class_sql = """
    INSERT INTO class_table (class_id, class_name, session, section)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(class_id) DO UPDATE SET
        class_name=excluded.class_name,
        session=excluded.session,
        section=excluded.section
    ;
    """

    # 3. Upsert parent_table
    upsert_parent_sql = """
    INSERT INTO parent_table (parent_id, parent_name, parent_contact_number)
    VALUES (?, ?, ?)
    ON CONFLICT(parent_id) DO UPDATE SET
        parent_name=excluded.parent_name,
        parent_contact_number=excluded.parent_contact_number
    ;
    """

    # 4. Check student exists
    check_student_sql = "SELECT 1 FROM student_table WHERE stud_id = ? LIMIT 1;"
    update_student_sql = """
    UPDATE student_table
    SET
        stud_name = ?,
        class_id = ?,
        parent_id = ?
    WHERE stud_id = ?
    ;
    """

    with with_sql_cursor() as (_, cur):
        # Upsert class
        cur.execute(upsert_class_sql, (class_id, stud_class, session, section))
        # Upsert parent
        cur.execute(upsert_parent_sql, (parent_id, parent_name, parent_contact))
        # Verify student exists
        cur.execute(check_student_sql, (stud_id,))
        if cur.fetchone() is None:
            raise ValueError(f"Student with id '{stud_id}' does not exist.")
        # Update student row
        cur.execute(update_student_sql, (stud_name, class_id, parent_id, stud_id))

    if img_path:
        if vector_store.exists(stud_id):
            logger.info(f"Found existing embedding for {stud_id}, will update it.")
            result = process_image(img_path)
            if result:
                encoding, face_box = result
                vector_store.add(stud_id, encoding)
            else:
                logger.error(f"Failed to process image for {stud_id}.")
        else:
            logger.error(f"cannot find the student with id {stud_id}. in our data")


def permanent_delete_student(stud_id):
    with with_sql_cursor() as (conn, cursor):
        cursor.execute(
            "SELECT parent_id, class_id FROM student_table WHERE stud_id = ?",
            (stud_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Student '{stud_id}' does not exist.")
        parent_id, class_id = row

        cursor.execute(
            "DELETE FROM fee_table WHERE stud_id = ?",
            (stud_id,)
        )
        logger.info(f"Deleted fee records for student {stud_id}")

        # Delete student record
        cursor.execute(
            "DELETE FROM student_table WHERE stud_id = ?",
            (stud_id,)
        )
        logger.info(f"Deleted student record for {stud_id}")

        # Optionally delete parent if no other student references it
        if parent_id:
            cursor.execute(
                "SELECT 1 FROM student_table WHERE parent_id = ? LIMIT 1",
                (parent_id,)
            )
            if not cursor.fetchone():
                cursor.execute(
                    "DELETE FROM parent_table WHERE parent_id = ?",
                    (parent_id,)
                )
                logger.info(f"Deleted parent {parent_id} as no more students reference it")

        # Optionally delete class if no other student references it
        if class_id:
            cursor.execute(
                "SELECT 1 FROM student_table WHERE class_id = ? LIMIT 1",
                (class_id,)
            )
            if not cursor.fetchone():
                cursor.execute(
                    "DELETE FROM class_table WHERE class_id = ?",
                    (class_id,)
                )
                logger.info(f"Deleted class {class_id} as no more students reference it")


def mark_left_student(stud_id: str):
    with with_sql_cursor() as (conn, cursor):
        cursor.execute("""
            SELECT stud_id, stud_name, parent_id, class_id
            FROM student_table
            WHERE stud_id = ?
        """, (stud_id,))
        student = cursor.fetchone()
        if not student:
            raise ValueError(f"Student '{stud_id}' does not exist.")
        cursor.execute("SELECT * FROM fee_table WHERE stud_id = ?", (stud_id,))
        fees = cursor.fetchall()

        parent = None
        if student[2]:
            cursor.execute("SELECT * FROM parent_table WHERE parent_id = ?", (student[2],))
            parent = cursor.fetchone()
        
        if student[3]:
            cursor.execute("SELECT * FROM class_table where class_id = ?", (student[3],))
            class_or_grade = cursor.fetchone()

    with archive_db_cursor() as (a_conn, a_cursor):
        a_cursor.execute("""
            INSERT INTO student_table (stud_id, stud_name, parent_id, class_id)
            VALUES (?, ?, ?, ?)
        """, student)
        if parent:
            a_cursor.execute("""
                INSERT OR IGNORE INTO parent_table (parent_id, parent_name, parent_contact_number)
                VALUES (?, ?, ? )
            """, parent)
        
        if class_or_grade:
            a_cursor.execute("""
                INSERT OR IGNORE INTO class_table(class_id, class_name, session, section)
                VALUES(?,?,?,?)""", class_or_grade)

        for fee in fees:
            a_cursor.execute("""
                INSERT INTO fee_table (fee_id, paid_data, month_name, status, stud_id)
                VALUES (?, ?, ?, ?, ?)
            """, fee)

    permanent_delete_student(stud_id=stud_id)