import os
from flask import Flask, render_template, request, redirect, url_for, flash, abort, Response, stream_with_context
from utils import with_sql_cursor
from datetime import date
from core.student_services import add_the_new_student, get_student,prepare_student_index_data, update_the_student, permanent_delete_student, mark_left_student
from core.fee_services import (
    get_fee_records_by_student,
    add_fee_record,
    update_fee_record,
    delete_fee_record,
    sync_fee_records_for_student,
    prepare_fee_management_data,
)
from werkzeug.utils import secure_filename
from config import Config
import logging
from pathlib import Path
import cv2
import threading
from core.attendance_services import (
    start_attendance_loop,
    stop_attendance_loop,
    generate_mjpeg_frame,
    generate_mode_events,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = 'replace-with-a-secure-random-key'
app.config['STUD_IMAGES_FILE'] = str(Config.STUD_IMAGES_FILE)

@app.route("/")
def home():
    return render_template('index.html')


@app.route("/students/add", methods=('GET', 'POST'))
def add_student():
    if request.method == 'POST':
        # Extract fields from form (names must match template)
        stud_id = request.form.get('id', '').strip()
        stud_name = request.form.get('name', '').strip()
        session = request.form.get('session', '').strip()
        stud_class = request.form.get('class', '').strip()
        section = request.form.get('section', '').strip() or None
        parent_name = request.form.get('parent_name', '').strip()
        parent_cnic = request.form.get('parent_cnic', '').strip()
        parent_contact = request.form.get('parent_number', '').strip()

        img_path: Path | None = None

        # Ensure base images directory exists
        images_base: Path = Path(Config.STUD_IMAGES_FILE)
        try:
            images_base.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create images directory: {e}")

    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            # Secure the filename and extract its extension
            filename = secure_filename(file.filename)
            _, ext = os.path.splitext(filename)  # e.g. ".png" or ".jpg"
            ext = ext.lower()

            # Build the target path: <STUD_IMAGES_FILE>/<stud_id><ext>
            target_path = images_base / f"{stud_id}{ext}"

            if target_path.exists():
                # Already have an image with this name/extension:
                img_path = target_path
            else:
                # First‐time upload: save the file
                try:
                    file.save(str(target_path))
                    img_path = target_path
                except Exception as e:
                    flash(f"Failed to save uploaded image: {e}", 'warning')
                    img_path = None

        try:
            add_the_new_student(
                stud_id=stud_id,
                stud_name=stud_name,
                session=session,
                section=section,
                stud_class=stud_class,
                parent_name=parent_name,
                parent_cnic=parent_cnic,
                parent_contact=parent_contact,
                img_path=img_path
            )
            flash("Student added successfully.", 'success')
        except ValueError as ve:
            flash(str(ve), 'warning')
        except Exception as e:
            logger.exception("Unexpected error adding student")
            flash(f"Error adding student: {e}", 'danger')

    return render_template('student/add_new_student.html')


@app.route("/students", methods=["GET"])
def student_index():
    data = prepare_student_index_data(with_sql_cursor, request.args)
    return render_template(
        "student/student_index.html",
        **data
    )


@app.route("/students/<student_id>")
def view_student_details(student_id):
    from core.student_services import get_student
    student_detail = get_student(student_id=student_id)
    return render_template('student/view_student_details.html', student=student_detail)


@app.route('/students/update', methods=["GET"])
def Search_update_student():
    data = prepare_student_index_data(with_sql_cursor, request.args)
    return render_template(
        "student/Search_update_student.html",
        **data
    )


@app.route("/students/update_student/<student_id>", methods=('GET', 'POST'))
def update_student(student_id):
    if request.method == 'POST':
        # Extract fields from form (names must match template)
        stud_id = student_id
        stud_name = request.form.get('name', '').strip()
        session = request.form.get('session', '').strip()
        stud_class = request.form.get('class', '').strip()
        section = request.form.get('section', '').strip() or None
        parent_name = request.form.get('parent_name', '').strip()
        parent_cnic = request.form.get('parent_cnic', '').strip()
        parent_contact = request.form.get('parent_number', '').strip()

        img_path: Path | None = None

        # Ensure base images directory exists
        images_base: Path = Path(Config.STUD_IMAGES_FILE)
        try:
            images_base.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create images directory: {e}")

    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            # Secure the filename and get its extension
            filename = secure_filename(file.filename)
            _, ext = os.path.splitext(filename)  # e.g. ".png", ".jpg", etc.
            ext = ext.lower()

            # Build the new target path: <STUD_IMAGES_FILE>/<stud_id><ext>
            images_base: Path = Path(Config.STUD_IMAGES_FILE)
            target_path = images_base / f"{stud_id}{ext}"

            # (Optional) Remove any old image for this student with a different ext
            for old in images_base.glob(f"{stud_id}.*"):
                if old != target_path:
                    try:
                        old.unlink()
                    except Exception as e:
                        logger.warning(f"Could not remove old image {old}: {e}")

            # Save (this will overwrite if the same filename already exists)
            try:
                file.save(str(target_path))
                img_path = target_path
            except Exception as e:
                flash(f"Failed to save uploaded image: {e}", 'warning')
                img_path = None

        try:
            update_the_student(
                stud_id=stud_id,
                stud_name=stud_name,
                session=session,
                section=section,
                stud_class=stud_class,
                parent_name=parent_name,
                parent_cnic=parent_cnic,
                parent_contact=parent_contact,
                img_path=img_path
            )
            flash("Student added successfully.", 'success')
        except ValueError as ve:
            flash(str(ve), 'warning')
        except Exception as e:
            logger.exception("Unexpected error adding student")
            flash(f"Error adding student: {e}", 'danger')


    from core.student_services import get_student
    student_detail = get_student(student_id=student_id)

    return render_template('student/update_student.html', student=student_detail)


@app.route("/students/delete", defaults={"student_id": None}, methods=["GET","POST"])
@app.route("/students/delete/<student_id>",           methods=["GET","POST"])
def delete_student(student_id):
    if request.method == "POST" and student_id:
        action = request.form.get("action")
        try:
            if action == "delete":
                permanent_delete_student(stud_id=student_id)
                flash("Student permanently deleted.", "success")

            elif action == "left":
                mark_left_student(stud_id=student_id)
                flash("Student marked as left and moved to archive.", "success")

            else:
                flash("Unknown action.", "warning")

        except ValueError as ve:
            flash(str(ve), "warning")
        except Exception as e:
            logger.exception("Unexpected error processing student delete/left")
            flash(f"Error deleting student: {e}", "danger")

        return redirect(url_for("delete_student", student_id=student_id))

    data = prepare_student_index_data(with_sql_cursor, request.args)
    return render_template("student/delete_student.html", **data)


@app.route("/fee_management", methods=["GET"])
def fee_management():
    data = prepare_fee_management_data(with_sql_cursor, request.args)
    return render_template("fee/fee_management.html", **data)


@app.route("/fees/<stud_id>")
def edit_fee(stud_id):
    sync_fee_records_for_student(stud_id, date.today())
    return render_template(
        "fee/edit_fee.html",
        stud_id=stud_id,
        student=get_student(student_id=stud_id),
        records=get_fee_records_by_student(stud_id),
        current_date=date.today().isoformat()
    )

@app.route("/fees/<stud_id>/add", methods=["POST"])
def fee_add(stud_id):
    fee_id     = request.form["fee_id"].strip()
    challan_no = request.form["challan_no"].strip()
    paid_date  = request.form["paid_date"].strip() or None
    amount     = request.form["amount"].strip()
    status     = request.form["status"].strip() or "Unpaid"
    month_name = (date.fromisoformat(paid_date).strftime("%B %Y")
                  if paid_date else date.today().strftime("%B %Y"))

    add_fee_record(stud_id, fee_id, challan_no, paid_date, month_name, status, amount)
    return redirect(url_for("edit_fee", stud_id=stud_id))


@app.route("/fees/update/<fee_id>", methods=["POST"])
def fee_update(fee_id):
    stud_id    = request.args.get("stud_id")
    challan_no = request.form.get("challan_no")
    paid_date  = request.form.get("paid_date")
    amount     = request.form.get("amount")
    # always mark Paid when manually updating
    update_fee_record(fee_id, challan_no=challan_no, paid_date=paid_date, amount=amount, status="Paid")
    return redirect(url_for("edit_fee", stud_id=stud_id))


@app.route("/fees/delete/<fee_id>", methods=["POST"])
def fee_delete(fee_id):
    if not delete_fee_record(fee_id):
        abort(404)
    return ("", 204)



@app.route("/attendance")
def attendance():
    return render_template("attendance/attendance_index.html")

@app.route("/attendance/start")
def attendance_start():
    started = start_attendance_loop()
    return ("Attendance started" if started else "Already running"), 200

@app.route("/attendance/stop")
def attendance_stop():
    stopped = stop_attendance_loop()
    return ("Attendance stopped" if stopped else "Not running"), 200

@app.route("/attendance/video_feed")
def video_feed():
    return Response(
        generate_mjpeg_frame(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route("/attendance/mode_feed")
def mode_feed():
    return Response(
        stream_with_context(generate_mode_events()),
        mimetype='text/event-stream'
    )



if __name__ == '__main__':
    app.run(debug=True)