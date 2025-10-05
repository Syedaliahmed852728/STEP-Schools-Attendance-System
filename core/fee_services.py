from core.class_services import get_all_classes
import sqlite3
from contextlib import contextmanager
from typing import List, Dict, Optional
from utils import with_sql_cursor
import datetime

def prepare_fee_management_data(with_sql_cursor, args) -> dict:
    # 1. load classes & build class/section lists exactly like student index
    classes_data      = get_all_classes()
    class_names       = sorted({cls["class_name"] for cls in classes_data if cls.get("class_name")})

    selected_class_name = args.get("class_name", "").strip()
    selected_section    = args.get("section",    "").strip()
    selected_status     = args.get("status",     "").strip()
    search_id           = args.get("search_id",  "").strip()

    # build section list based on class_name
    section_values = set()
    for cls in classes_data:
        if not selected_class_name or cls["class_name"] == selected_class_name:
            section_values.add(cls.get("section") or "")

    # possible fee statuses
    statuses = ["Unpaid", "Paid", "Overdue"]

    # 2. SQL — pull each student + their latest fee row (for historical context)
    query = """
    WITH latest_fee AS (
      SELECT stud_id, MAX(paid_data) AS max_paid_data
      FROM fee_table
      WHERE paid_data IS NOT NULL
      GROUP BY stud_id
    )
    SELECT
      s.stud_id,
      s.stud_name,
      c.class_name            AS stud_class_name,
      c.section               AS stud_class_section,
      c.session               AS stud_class_session,
      f.status                AS stud_fee_status
    FROM student_table s
    LEFT JOIN class_table   c  ON s.class_id = c.class_id
    LEFT JOIN latest_fee    lf ON s.stud_id = lf.stud_id
    LEFT JOIN fee_table     f  ON f.stud_id = lf.stud_id
                             AND f.paid_data = lf.max_paid_data
    """
    filters, params = [], {}
    if selected_class_name:
        filters.append("c.class_name = :class_name")
        params["class_name"] = selected_class_name
    if selected_section:
        if selected_section == "__none__":
            filters.append("(c.section IS NULL OR c.section = '')")
        else:
            filters.append("c.section = :section")
            params["section"] = selected_section
    if selected_status:
        # we'll override below, but allow filtering by historical status if desired
        filters.append("f.status = :status")
        params["status"] = selected_status
    if search_id:
        filters.append("s.stud_id = :search_id")
        params["search_id"] = search_id

    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY s.stud_name COLLATE NOCASE"

    # 3. execute and post‐process
    with with_sql_cursor() as (_, cur):
        cur.execute(query, params)
        rows = cur.fetchall()
        students = [dict(r) for r in rows]
 
        # determine the current month label
        current_month = datetime.datetime.now().strftime("%B %Y")  # e.g. "July 2025"

        # override each student's fee status based on THIS month
        for stu in students:
            cur.execute(
                "SELECT status FROM fee_table WHERE stud_id = ? AND month_name = ?",
                (stu["stud_id"], current_month)
            )
            fee_row = cur.fetchone()
            if fee_row and fee_row["status"] == "Paid":
                stu["stud_fee_status"] = "Paid"
            else:
                stu["stud_fee_status"] = "Unpaid"

    return {
        "class_names":          class_names,
        "sections":             section_values,
        "statuses":             statuses,
        "students":             students,
        "selected_class_name":  selected_class_name,
        "selected_section":     selected_section,
        "selected_status":      selected_status,
        "search_id":            search_id,
    }


def add_fee_record(
    stud_id: str,
    fee_id: str,
    challan_no: str,
    paid_date: str,
    month_name: str,
    status: str,
    amount: str
) -> None:
    with with_sql_cursor() as (_, cur):
        cur.execute("""
            INSERT INTO fee_table
              (fee_id, challan_no, paid_data, month_name, status, amount, stud_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (fee_id, challan_no, paid_date, month_name, status, amount, stud_id))


def get_fee_records_by_student(stud_id: str) -> List[Dict]:
    with with_sql_cursor() as (_, cur):
        cur.execute("""
            SELECT fee_id, challan_no, paid_data, month_name, status, amount
            FROM fee_table
            WHERE stud_id = ?
            ORDER BY month_name
        """, (stud_id,))
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def update_fee_record(
    fee_id: str,
    challan_no: Optional[str] = None,
    paid_date:   Optional[str] = None,
    amount:      Optional[str] = None,
    status:      Optional[str] = None
) -> bool:
    clauses, params = [], []
    if challan_no is not None:
        clauses.append("challan_no = ?"); params.append(challan_no)
    if paid_date   is not None:
        clauses.append("paid_data   = ?"); params.append(paid_date)
    if amount      is not None:
        clauses.append("amount      = ?"); params.append(amount)
    if status      is not None:
        clauses.append("status      = ?"); params.append(status)
    if not clauses:
        return False

    params.append(fee_id)
    sql = f"UPDATE fee_table SET {', '.join(clauses)} WHERE fee_id = ?"
    with with_sql_cursor() as (_, cur):
        cur.execute(sql, params)
        return cur.rowcount > 0


def delete_fee_record(fee_id: str) -> bool:
    with with_sql_cursor() as (_, cur):
        cur.execute("DELETE FROM fee_table WHERE fee_id = ?", (fee_id,))
        return cur.rowcount > 0



def sync_fee_records_for_student(stud_id: str, today: datetime.date) -> None:
    current_month = today.strftime("%B %Y")
    with with_sql_cursor() as (_, cur):
        cur.execute("""
            SELECT fee_id, month_name, status
            FROM fee_table
            WHERE stud_id = ?
        """, (stud_id,))
        existing = { r["month_name"]: r for r in cur.fetchall() }

        # 1) add current-month if missing
        if current_month not in existing:
            new_id = f"{stud_id}-{today.strftime('%Y%m')}"
            cur.execute("""
                INSERT INTO fee_table
                  (fee_id, challan_no, paid_data, month_name, status, amount, stud_id)
                VALUES (?, NULL, NULL, ?, 'Unpaid', NULL, ?)
            """, (new_id, current_month, stud_id))

        # 2) mark past Unpaid as Overdue
        for m, row in existing.items():
            try:
                dt = datetime.datetime.strptime(m, "%B %Y").date()
            except ValueError:
                continue
            if dt < today.replace(day=1) and row["status"] == "Unpaid":
                cur.execute("""
                    UPDATE fee_table SET status = 'Overdue'
                    WHERE fee_id = ?
                """, (row["fee_id"],))
