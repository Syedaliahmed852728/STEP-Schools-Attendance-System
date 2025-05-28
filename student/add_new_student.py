from utils import with_sql_cursor

def add_new_student(
    stud_id: str,
    stud_name: str,
    session: str,
    section: str | None,
    stud_class: str,
    parent_name: str,
    parent_cnic: str,
    parent_contact: str,
    img_path: str = None,
):
    if section:
        class_id= f"{stud_class}-{section}-{session}"
    else:
        class_id= f"{stud_class}-{session}"

    select_student_q= "SELECT stud_id FROM student_table WHERE stud_id = ?"
    select_student_params= (stud_id,)

    select_class_q= "SELECT class_id FROM class_table WHERE class_id = ?"
    select_class_params= (class_id,)

    insert_class_q= """
        INSERT INTO class_table
          (class_id, class_name, session, section)
        VALUES (?, ?, ?, ?)
    """
    insert_class_params= (class_id, stud_class, session, section)

    select_parent_q= "SELECT parent_id FROM parent_table WHERE parent_id = ?"
    select_parent_params= (parent_cnic,)

    insert_parent_q= """
        INSERT INTO parent_table
          (parent_id, parent_name, parent_contact_number)
        VALUES (?, ?, ?)
    """
    insert_parent_params= (parent_cnic, parent_name, parent_contact)

    insert_student_q= """
        INSERT INTO student_table
          (stud_id, stud_name, stud_section, class_id, parent_id)
        VALUES (?, ?, ?, ?, ?)
    """
    insert_student_params= (stud_id, stud_name, section, class_id, parent_cnic)

    # Now open the cursor and execute in order
    with with_sql_cursor() as (conn, cursor):
        cursor.execute(select_student_q, select_student_params)
        if cursor.fetchone():
            raise ValueError(f"Student '{stud_id}' already exists.")

        cursor.execute(select_class_q, select_class_params)
        if not cursor.fetchone():
            cursor.execute(insert_class_q, insert_class_params)

        cursor.execute(select_parent_q, select_parent_params)
        if not cursor.fetchone():
            cursor.execute(insert_parent_q, insert_parent_params)

        cursor.execute(insert_student_q, insert_student_params)