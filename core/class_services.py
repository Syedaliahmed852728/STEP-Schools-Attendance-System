import logging
from config import Config
from utils import with_sql_cursor
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
    today = datetime.now().strftime("%Y-%m-%d")
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
            "SELECT status, COUNT(*) AS cnt "
            "FROM fee_table f "
            "JOIN student_table s ON s.stud_id = f.stud_id "
            "WHERE s.class_id = ? AND f.month_name = ? "
            "GROUP BY status",
            (class_id, current_month)
        )
        fee_counts = {r["status"]: r["cnt"] for r in cur.fetchall()}
        fee_paid    = fee_counts.get("Paid", 0)
        fee_pending = fee_counts.get("Pending", 0)
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
            fee_status = fr["status"] if fr else "Pending"

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