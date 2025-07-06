import logging
from config import Config
from utils import with_sql_cursor, archive_db_cursor
from datetime import datetime

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


def prepare_class_index_data(with_sql_cursor, args) -> dict:
    # 1. Load all classes for dropdowns
    with with_sql_cursor() as (_, cur):
        cur.execute("SELECT class_name, section FROM class_table")
        rows = cur.fetchall()
    class_names = sorted({r["class_name"] for r in rows if r["class_name"]})
    sections    = sorted({r["section"] or "" for r in rows})

    # 2. Get selected filters
    selected_class_name = args.get("class_name", "", type=str).strip()
    selected_section    = args.get("section",    "", type=str).strip()

    # 3. Build main query: classes + enrolled student counts
    query = """
    SELECT
      c.class_id,
      c.class_name,
      c.section,
      COUNT(s.stud_id) AS student_count
    FROM class_table c
    LEFT JOIN student_table s
      ON s.class_id = c.class_id
    """
    filters, params = [], {}
    if selected_class_name:
        filters.append("c.class_name = :class_name")
        params["class_name"] = selected_class_name
    if selected_section:
        filters.append("c.section = :section")
        params["section"] = selected_section

    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " GROUP BY c.class_id ORDER BY c.class_name"

    # 4. Execute and collect
    with with_sql_cursor() as (_, cur):
        cur.execute(query, params)
        classes = [dict(r) for r in cur.fetchall()]

    return {
        "class_names":         class_names,
        "sections":            sections,
        "classes":             classes,
        "selected_class_name": selected_class_name,
        "selected_section":    selected_section,
    }


def prepare_view_class_details_data(with_sql_cursor, class_id) -> dict:
    today = datetime.now().strftime('%d-%m-%Y')
    current_month = datetime.now().strftime("%B %Y")

    with with_sql_cursor() as (_, cur):
        # 1. Fetch class meta
        cur.execute(
            "SELECT class_id, class_name, section FROM class_table WHERE class_id = ?",
            (class_id,)
        )
        cls = cur.fetchone()
        class_info = dict(cls) if cls else {}

        # 2. Total students
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM student_table WHERE class_id = ?",
            (class_id,)
        )
        total_students = cur.fetchone()["cnt"] or 0

        # 3. Today's attendance lists
        cur.execute(
            "SELECT s.stud_id, s.stud_name, a.status "
            "FROM attendance_table a "
            "JOIN student_table s ON s.stud_id = a.stud_id "
            "WHERE s.class_id = ? AND a.date_full = ?",
            (class_id, today)
        )
        rows = [dict(r) for r in cur.fetchall()]
        present_today = [r for r in rows if r["status"] == "Present"]
        absent_today  = [r for r in rows if r["status"] == "Absent"]

        # 4. Fee breakdown for current month
        cur.execute(
            """
            SELECT 
            CASE 
                WHEN f.status IS NULL 
                OR f.status = 'None' 
                THEN 'Unpaid' 
                ELSE f.status 
            END AS status,
            COUNT(*) AS cnt
            FROM student_table s
            LEFT JOIN fee_table f
            ON s.stud_id = f.stud_id
            AND f.month_name = ?
            WHERE s.class_id = ?
            GROUP BY status
            """,
            (current_month, class_id)
        )
        fee_counts = { r["status"]: r["cnt"] for r in cur.fetchall() }

        fee_paid    = fee_counts.get("Paid",    0)
        fee_pending = fee_counts.get("Unpaid",  0)
        fee_overdue = fee_counts.get("Overdue", 0)

        # 5. Per-student overview (attendance % & fee status)
        cur.execute(
            "SELECT s.stud_id, s.stud_name "
            "FROM student_table s "
            "WHERE s.class_id = ? "
            "ORDER BY s.stud_name",
            (class_id,)
        )
        students = [dict(r) for r in cur.fetchall()]

        overview = []
        for s in students:
            # attendance summary
            cur.execute(
                "SELECT status, COUNT(*) AS cnt "
                "FROM attendance_table "
                "WHERE stud_id = ? "
                "GROUP BY status",
                (s["stud_id"],)
            )
            atts = {r["status"]: r["cnt"] for r in cur.fetchall()}
            present = atts.get("Present", 0)
            absent  = atts.get("Absent", 0)
            total   = present + absent or 1
            pct     = (present / total) * 100

            # fee status for this month
            cur.execute(
                "SELECT status FROM fee_table "
                "WHERE stud_id = ? AND month_name = ?",
                (s["stud_id"], current_month)
            )
            fr = cur.fetchone()
            fee_status = fr["status"] if fr else "Unpaid"

            overview.append({
                "stud_id":       s["stud_id"],
                "stud_name":     s["stud_name"],
                "present_count": present,
                "absent_count":  absent,
                "attendance_pct": pct,
                "fee_status":    fee_status
            })

    return {
        "class":             class_info,
        "total_students":    total_students,
        "present_today":     present_today,
        "absent_today":      absent_today,
        "today_date":        today,
        "current_month":     current_month,
        "fee_paid":          fee_paid,
        "fee_pending":       fee_pending,
        "fee_overdue":       fee_overdue,
        "students_overview": overview
    }


def permanent_delete_class(class_id: str):
    """
    Deletes the class record, all students in it, and all their related records:
    fees, attendance, promoted entries, parents (if orphaned), and promoted_table records.
    """

    from pathlib import Path
    from config import Config

    with with_sql_cursor() as (conn, cursor):
        # 1) Fetch all students in this class
        cursor.execute(
            "SELECT stud_id, parent_id FROM student_table WHERE class_id = ?",
            (class_id,)
        )
        students = cursor.fetchall()  # list of (stud_id, parent_id)

        # 2) Delete fees & attendance & promoted records for each student
        for stud_id, parent_id in students:
            cursor.execute("DELETE FROM fee_table WHERE stud_id = ?", (stud_id,))
            cursor.execute("DELETE FROM attendance_table WHERE stud_id = ?", (stud_id,))
            cursor.execute("DELETE FROM promoted_table WHERE stud_id = ?", (stud_id,))

            # Optionally delete parent if no other students reference
            if parent_id:
                cursor.execute(
                    "SELECT 1 FROM student_table WHERE parent_id = ? AND class_id != ? LIMIT 1",
                    (parent_id, class_id)
                )
                if not cursor.fetchone():
                    cursor.execute("DELETE FROM parent_table WHERE parent_id = ?", (parent_id,))

            # Optionally delete images & embeddings if you used that logic
            # (mirror your permanent_delete_student logic)
            # e.g. delete from vector_store and local files

        # 3) Delete all students in this class
        cursor.execute(
            "DELETE FROM student_table WHERE class_id = ?",
            (class_id,)
        )

        # 4) Delete the class itself
        cursor.execute(
            "DELETE FROM class_table WHERE class_id = ?",
            (class_id,)
        )
        conn.commit()


def archive_class(class_id: str):
    """
    Moves an entire class and all its data into the archive DB,
    then permanently deletes them from the live DB.
    """
    # 1) Copy the class row
    with with_sql_cursor() as (_, cur):
        cur.execute(
            "SELECT class_id, class_name, session, section FROM class_table WHERE class_id = ?",
            (class_id,)
        )
        cls = cur.fetchone()
        if not cls:
            raise ValueError(f"Class '{class_id}' not found.")

        # 2) Fetch all students + their parents, fees, attendance, promoted entries
        cur.execute(
            "SELECT stud_id, stud_name, parent_id FROM student_table WHERE class_id = ?",
            (class_id,)
        )
        students = [dict(r) for r in cur.fetchall()]

        # For each student, fetch their related rows
        data_to_archive = []
        for s in students:
            stud_id   = s["stud_id"]
            parent_id = s["parent_id"]

            cur.execute("SELECT * FROM fee_table WHERE stud_id = ?", (stud_id,))
            fees = cur.fetchall()

            cur.execute("SELECT * FROM attendance_table WHERE stud_id = ?", (stud_id,))
            attendance = cur.fetchall()

            cur.execute("SELECT * FROM promoted_table WHERE stud_id = ?", (stud_id,))
            promoted = cur.fetchall()

            # Fetch parent and collect
            parent = None
            if parent_id:
                cur.execute("SELECT * FROM parent_table WHERE parent_id = ?", (parent_id,))
                parent = cur.fetchone()

            data_to_archive.append((s, parent, fees, attendance, promoted))

    with archive_db_cursor() as (_, a_cur):
        # archive class
        a_cur.execute(
            "INSERT OR IGNORE INTO class_table (class_id, class_name, session, section) VALUES (?, ?, ?, ?)",
            (cls["class_id"], cls["class_name"], cls["session"], cls["section"])
        )

        for s, parent, fees, attendance, promoted in data_to_archive:
            # archive student
            a_cur.execute(
                "INSERT OR IGNORE INTO student_table (stud_id, stud_name, parent_id, class_id) VALUES (?, ?, ?, ?)",
                (s["stud_id"], s["stud_name"], parent["parent_id"] if parent else None, class_id)
            )

            # archive parent
            if parent:
                a_cur.execute(
                    "INSERT OR IGNORE INTO parent_table "
                    "(parent_id, parent_name, parent_contact_number) VALUES (?, ?, ?)",
                    (parent["parent_id"], parent["parent_name"], parent["parent_contact_number"])
                )

            # archive fees
            for f in fees:
                a_cur.execute(
                    "INSERT OR IGNORE INTO fee_table "
                    "(fee_id, challan_no, paid_data, month_name, status, amount, stud_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    f
                )

            # archive attendance
            for a in attendance:
                a_cur.execute(
                    "INSERT OR IGNORE INTO attendance_table "
                    "(stud_id, date_full, arrival_time, departure_time, status) VALUES (?, ?, ?, ?, ?)",
                    a
                )

            # archive promoted entries
            for p in promoted:
                a_cur.execute(
                    "INSERT OR IGNORE INTO promoted_table "
                    "(promoted_id, stud_id, parent_id, session, class_name, student_name, parent_name, total_present, total_absent, fee_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    p
                )
        a_cur.connection.commit()

    # 3) Finally remove from live DB
    permanent_delete_class(class_id)
