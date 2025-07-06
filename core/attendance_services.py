import threading
import cv2
import numpy as np
import face_recognition
import time
import queue
import pickle
import logging

from utils import with_sql_cursor, VectorStore
from pathlib import Path
from config import Config
from datetime import datetime, timedelta
from core.student_services import get_student

logger = logging.getLogger("attendance")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s"
))
logger.addHandler(handler)

_mode_q = queue.Queue()

_camera       = None
_camera_lock  = threading.Lock()
_camera_running = False

vector_store = VectorStore(Path(Config.VECTOR_STORE_FILE))

def mark_absentees_before_attendance() -> None:
    """Mark everyone absent at start if not already in DB."""
    today = datetime.now().strftime('%d-%m-%Y')
    with with_sql_cursor() as (_, cur):
        for (sid,) in cur.execute("SELECT stud_id FROM student_table"):
            exists = cur.execute(
                "SELECT 1 FROM attendance_table WHERE stud_id=? AND date_full=?",
                (sid, today)
            ).fetchone()
            if not exists:
                cur.execute(
                    "INSERT INTO attendance_table(stud_id,date_full,status) VALUES(?,?,?)",
                    (sid, today, 'Absent')
                )
                logger.debug(f"Marked {sid} as Absent for {today}")


def is_already_present(sid: str) -> bool:
    today = datetime.now().strftime('%d-%m-%Y')
    with with_sql_cursor() as (_, cur):
        row = cur.execute(
            "SELECT status FROM attendance_table WHERE stud_id=? AND date_full=?",
            (sid, today)
        ).fetchone()
    present = bool(row and row[0] == 'Present')
    logger.debug(f"is_already_present({sid}) → {present}")
    return present


def is_departure_time(sid: str) -> bool:
    now = datetime.now()
    today = now.strftime('%d-%m-%Y')
    with with_sql_cursor() as (_, cur):
        row = cur.execute(
            "SELECT arrival_time FROM attendance_table "
            "WHERE stud_id=? AND date_full=? AND status='Present'",
            (sid, today)
        ).fetchone()
    if not row or not row[0]:
        return False
    arr = datetime.strptime(row[0], '%I:%M:%S %p')
    arr = arr.replace(year=now.year, month=now.month, day=now.day)
    dep = (now - arr) > timedelta(minutes=Config.DEPARTURE_MINUTES)
    logger.debug(f"is_departure_time({sid}) → {dep}")
    return dep


def MarkAttendance(sid: str) -> None:
    """Flip Absent→Present or record departure_time."""
    now = datetime.now()
    today = now.strftime('%d-%m-%Y')
    tstr  = now.strftime('%I:%M:%S %p')
    with with_sql_cursor() as (_, cur):
        row = cur.execute(
            "SELECT status FROM attendance_table WHERE stud_id=? AND date_full=?",
            (sid, today)
        ).fetchone()
        if row:
            if row[0] != 'Present':
                cur.execute(
                    "UPDATE attendance_table "
                    "SET status='Present', arrival_time=? "
                    "WHERE stud_id=? AND date_full=?",
                    (tstr, sid, today)
                )
                logger.info(f"{sid} ARRIVED at {tstr}")
            elif is_departure_time(sid):
                cur.execute(
                    "UPDATE attendance_table "
                    "SET departure_time=? "
                    "WHERE stud_id=? AND date_full=?",
                    (tstr, sid, today)
                )
                logger.info(f"{sid} DEPARTED at {tstr}")
        else:
            cur.execute(
                "INSERT INTO attendance_table"
                "(stud_id,date_full,arrival_time,status) VALUES(?,?,?,?)",
                (sid, today, tstr, 'Present')
            )
            logger.info(f"{sid} FIRST‐TIME ARRIVAL at {tstr}")


def process_frame_events(frame, known_encs, stud_IDs):
    """
    Returns (sid, event) where event ∈ {'new','departure','repeat'} or (None,None).
    """
    small = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
    rgb   = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    faces = face_recognition.face_locations(rgb)
    encs  = face_recognition.face_encodings(rgb, faces)
    logger.debug(f"Detected {len(faces)} face(s) in frame")
    for enc in encs:
        dists = face_recognition.face_distance(known_encs, enc)
        ix    = int(np.argmin(dists))
        best  = dists[ix]
        logger.debug(f"Best match dist={best:.3f} for ID={stud_IDs[ix]}")
        if best > Config.FACE_MATCH_THRESHOLD:
            logger.debug("No match below threshold")
            continue
        sid = stud_IDs[ix]
        if not is_already_present(sid):
            return sid, 'new'
        if is_departure_time(sid):
            return sid, 'departure'
        return sid, 'repeat'
    return None, None


def _attendance_capture_loop():
    global _camera, _camera_running
    logger.info("Starting attendance capture loop")
    mark_absentees_before_attendance()

    # Load encodings
    store     = vector_store.all()
    stud_IDs  = list(store.keys())
    known_encs= [np.array(v) for v in store.values()]
    logger.info(f"Loaded {len(stud_IDs)} encodings")

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  Config.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.FRAME_HEIGHT)
    time.sleep(2)

    current_mode = 0
    mode_time    = None
    mode1_base = cv2.imread(str(Path("static/web_images/mode1.png")))
    while True:
        with _camera_lock:
            if not _camera_running:
                break

        success, frame = cap.read()
        if not success:
            continue

        sid, event = process_frame_events(frame, known_encs, stud_IDs)
        now = time.time()

        if sid and event == 'new':
            # 1) Mark attendance
            MarkAttendance(sid)

            # 2) Fetch student info + headshot
            info = get_student(student_id=sid)
            headshot = None
            for ext in ('.jpg','.jpeg','.png'):
                p = Path(Config.STUD_IMAGES_FILE) / f"{sid}{ext}"
                if p.exists():
                    headshot = cv2.imread(str(p))
                    break

            # 3) Compose the dynamic mode1 panel
            panel = mode1_base.copy()

            # — top‑center headshot: width -5px, height -10px, moved down +10px
            base_w, base_h = 220, 240
            pw = base_w      # 195px wide
            ph = base_h - 10     # 190px tall
            x_photo = (panel.shape[1] - pw) // 2
            y_photo = 60 + 65    # originally 60 + 50; now +10 more =110 → 120 total
            if headshot is not None:
                face = cv2.resize(headshot, (pw, ph))
                panel[y_photo:y_photo+ph, x_photo:x_photo+pw] = face

            # — top‑left total attendance: smaller text, moved down +15px
            total = info["total_attendance"]
            cv2.putText(
                panel,
                str(total),
                (55, 75),                    # 40→55
                cv2.FONT_HERSHEY_DUPLEX,
                1.0,                         # reduced from 1.2 → 1.0
                (255,255,255),
                1
            )

            # — remove literal “ID:”/“Major:” but still draw their VALUES
            cv2.putText(
                panel,
                info['stud_id'],
                (panel.shape[1]//2 - 15, 455),
                cv2.FONT_HERSHEY_DUPLEX,
                1.0,
                (255,255,255),
                1
            )
            cv2.putText(
                panel,
                info['stud_class_name'],
                (panel.shape[1]//2 - 15, 510),
                cv2.FONT_HERSHEY_DUPLEX,
                1.0,
                (255,255,255),
                1
            )

            # 4) Save dynamic panel
            tmp = Path("static/web_images/mode1_temp.png")
            cv2.imwrite(str(tmp), panel)

            # 5) Queue it
            _mode_q.put("mode1_temp")
            current_mode, mode_time = 1, now

            # 6) Hold for duration
            time.sleep(Config.MODE_DISPLAY_DURATION)

            # 7) Reset
            _mode_q.put("mode0")
            current_mode, mode_time = 0, None
            continue



        elif sid and event == 'departure':
            logger.debug(f"Event DEPARTURE for {sid}")
            # 1) Mark attendance
            MarkAttendance(sid)

            # 2) Fetch student info + headshot
            info = get_student(student_id=sid)
            headshot = None
            for ext in ('.jpg','.jpeg','.png'):
                p = Path(Config.STUD_IMAGES_FILE) / f"{sid}{ext}"
                if p.exists():
                    headshot = cv2.imread(str(p))
                    break

            # 3) Compose the dynamic mode1 panel
            panel = mode1_base.copy()

            # — top‑center headshot: width -5px, height -10px, moved down +10px
            base_w, base_h = 220, 240
            pw = base_w      # 195px wide
            ph = base_h - 10     # 190px tall
            x_photo = (panel.shape[1] - pw) // 2
            y_photo = 60 + 65    # originally 60 + 50; now +10 more =110 → 120 total
            if headshot is not None:
                face = cv2.resize(headshot, (pw, ph))
                panel[y_photo:y_photo+ph, x_photo:x_photo+pw] = face

            # — top‑left total attendance: smaller text, moved down +15px
            total = info["total_attendance"]
            cv2.putText(
                panel,
                str(total),
                (55, 75),                    # 40→55
                cv2.FONT_HERSHEY_DUPLEX,
                1.0,                         # reduced from 1.2 → 1.0
                (255,255,255),
                1
            )

            box_w = pw + 30                     # 20px wider than the headshot
            box_h = int(0.6 * ph) - 15          # 10px shorter than 60% of headshot height
            x_box = x_photo - 15               # shift left 10px so box stays centered around headshot
            y_box = y_photo + ph + 45           # 10px more below than before (was +10, now +20)

            cv2.rectangle(
                panel,
                (x_box, y_box),
                (x_box + box_w, y_box + box_h),
                (139, 0, 0),                    # dark‑blue in BGR
                cv2.FILLED
            )

            # — put centered “GOODBYE” text inside that box
            text = "GOODBYE"
            font = cv2.FONT_HERSHEY_DUPLEX
            font_scale = 1.0
            thickness = 2

            # measure text size so we can center it
            (text_w, text_h), baseline = cv2.getTextSize(text, font, font_scale, thickness)
            x_text = x_box + (box_w - text_w) // 2
            y_text = y_box + (box_h + text_h) // 2

            cv2.putText(
                panel,
                text,
                (x_text, y_text),
                font,
                font_scale,
                (255, 255, 255),               # white text
                thickness
            )

            # 4) Save dynamic panel
            tmp = Path("static/web_images/mode1_temp.png")
            cv2.imwrite(str(tmp), panel)

            # 5) Queue it
            _mode_q.put("mode1_temp")
            current_mode, mode_time = 1, now

            # 6) Hold for duration
            time.sleep(Config.MODE_DISPLAY_DURATION)

            # 7) Reset
            _mode_q.put("mode0")
            current_mode, mode_time = 0, None
            continue

        elif sid and event == 'repeat':
            logger.debug(f"Event REPEAT for {sid}")
            _mode_q.put('mode3')
            current_mode, mode_time = 3, now

        # reset after display duration
        if current_mode in (1, 3, 4) and mode_time and now - mode_time > Config.MODE_DISPLAY_DURATION:
            _mode_q.put('mode0')
            current_mode, mode_time = 0, None

        # update camera buffer
        with _camera_lock:
            _camera = frame.copy()

    cap.release()
    with _camera_lock:
        _camera_running = False
    logger.info("Stopped attendance capture loop")


def start_attendance_loop() -> bool:
    global _camera_running
    with _camera_lock:
        if _camera_running:
            logger.warning("Attendance loop already running")
            return False
        _camera_running = True
    threading.Thread(target=_attendance_capture_loop, daemon=True).start()
    return True


def marking_off_to_classes_where_all_students_are_absent(class_id: str):
    """
    If all students in class_id are marked 'Absent' today, mark them 'Off'.
    Does not stop the camera loop.
    """
    today = datetime.now().strftime("%d-%m-%Y")
    with with_sql_cursor() as (_, cur):
        # Total students in class
        cur.execute("SELECT COUNT(*) FROM student_table WHERE class_id = ?", (class_id,))
        total_students = cur.fetchone()[0]

        # Count absent students today
        cur.execute(
            """
            SELECT COUNT(*)
              FROM attendance_table a
              JOIN student_table s USING(stud_id)
             WHERE s.class_id = ?
               AND a.date_full = ?
               AND a.status = 'Absent'
            """, (class_id, today)
        )
        absent_count = cur.fetchone()[0]

        if total_students > 0 and absent_count == total_students:
            logger.info(f"All {total_students} students in class {class_id} are Absent on {today}; marking Off.")
            cur.execute(
                """
                UPDATE attendance_table
                   SET status = 'Off', arrival_time = NULL, departure_time = NULL
                 WHERE stud_id IN (
                     SELECT stud_id FROM student_table WHERE class_id = ?
                 )
                   AND date_full = ?
                   AND status = 'Absent'
                """, (class_id, today)
            )


def stop_attendance_loop() -> bool:
    """
    Apply attendance-off marking for any class where all students are Absent today,
    then stop the camera loop.
    """
    # 1) Process each class
    with with_sql_cursor() as (_, cur):
        cur.execute("SELECT class_id FROM class_table")
        class_ids = [row[0] for row in cur.fetchall()]

    for cid in class_ids:
        marking_off_to_classes_where_all_students_are_absent(cid)

    # 2) Stop the camera loop
    with _camera_lock:
        global _camera_running
        if not _camera_running:
            logger.warning("Attendance loop not running")
            return False
        _camera_running = False

    logger.info("Attendance loop stopped for all classes.")
    return True


def generate_mjpeg_frame():
    """Yield MJPEG frames from the latest camera image."""
    while True:
        with _camera_lock:
            frame = _camera.copy() if _camera is not None else None

        if frame is None:
            # blank if nothing yet
            blank = np.ones((Config.FRAME_HEIGHT, Config.FRAME_WIDTH, 3), dtype=np.uint8)*255
            frame = blank

        ret, buf = cv2.imencode('.jpg', frame)
        if not ret:
            continue
        jpg = buf.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpg + b'\r\n')


def generate_mode_events():
    """SSE generator streaming 'mode0'/'mode1'/'mode3'."""
    logger.info("Mode-feed client connected")
    while True:
        mode = _mode_q.get()
        logger.debug(f"Streaming mode event: {mode}")
        yield f"data: {mode}\n\n"
