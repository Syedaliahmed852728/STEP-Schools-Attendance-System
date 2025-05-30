import os
import pickle
from pathlib import Path
import logging
from dotenv import load_dotenv
import cv2
import face_recognition
from utils import with_sql_cursor

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()

class Config:
    MAX_IMAGE_DIMENSION: int = int(os.getenv("MAX_IMAGE_DIMENSION", 800))
    FACE_DETECTION_MODEL: str = os.getenv("FACE_DETECTION_MODEL", "hog")
    NUM_ENCODING_JITTERS: int = int(os.getenv("NUM_ENCODING_JITTERS", 1))
    VECTOR_STORE_NAME: str = os.getenv("VECTOR_STORE", "vector_store")
    DB_PATH: Path = Path(os.getenv("DB_PATH", "./data"))
    THUMBNAIL_DIR: Path = DB_PATH / "stud_face_images"

# Ensure data folders exist
Config.DB_PATH.mkdir(parents=True, exist_ok=True)
Config.THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

VECTOR_STORE_FILE: Path = Config.DB_PATH / f"{Config.VECTOR_STORE_NAME}.pkl"

class VectorStore:
    def __init__(self, path: Path):
        self.path = path
        self._store = None

    def load(self) -> dict:
        if self._store is None:
            if self.path.exists():
                with open(self.path, 'rb') as f:
                    self._store = pickle.load(f)
                    logger.info(f"Loaded vector store with {len(self._store)} entries.")
            else:
                self._store = {}
                logger.info("Initialized empty vector store.")
        return self._store

    def add(self, stud_id: str, encoding: list[float]) -> None:
        store = self.load()
        store[stud_id] = encoding
        with open(self.path, 'wb') as f:
            pickle.dump(store, f)
        logger.info(f"Saved encoding for ID {stud_id}.")

    def all(self) -> dict:
        return self.load()

vector_store = VectorStore(VECTOR_STORE_FILE)


def process_image(filepath: Path) -> tuple[list[float], tuple[int,int,int,int]] | None:
    """
    Detects the largest face, returns its encoding and face box.
    Returns (encoding_list, (top,right,bottom,left)) or None.
    """
    image = cv2.imread(str(filepath))
    if image is None:
        logger.warning(f"Cannot read image: {filepath}")
        return None

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    scale = Config.MAX_IMAGE_DIMENSION / max(h, w)
    if scale < 1:
        rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        logger.debug(f"Resized {filepath.name} to {rgb.shape[1]}x{rgb.shape[0]}")

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


def save_thumbnail(filepath: Path, face_box: tuple[int,int,int,int], stud_id: str) -> Path:
    """
    Crops the face from the image and saves a thumbnail under THUMBNAIL_DIR.
    Returns the thumbnail path.
    """
    image = cv2.imread(str(filepath))
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    top, right, bottom, left = face_box
    face_img = rgb[top:bottom, left:right]
    thumbnail_path = Config.THUMBNAIL_DIR / f"{stud_id}.jpg"
    bgr_face = cv2.cvtColor(face_img, cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(thumbnail_path), bgr_face)
    logger.info(f"Saved thumbnail for {stud_id} at {thumbnail_path}")
    return thumbnail_path


def add_new_student(
    stud_id: str,
    stud_name: str,
    session: str,
    section: str | None,
    stud_class: str,
    parent_name: str,
    parent_cnic: str,
    parent_contact: str,
    img_path: str | None = None,
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
            "INSERT INTO student_table (stud_id, stud_name, stud_section, class_id, parent_id) VALUES (?, ?, ?, ?, ?)",
            (stud_id, stud_name, section, class_id, parent_cnic)
        )
        logger.info(f"Inserted student {stud_id} into database.")

    if img_path:
        filepath = Path(img_path)
        result = process_image(filepath)
        if result:
            encoding, face_box = result
            vector_store.add(stud_id, encoding)
            save_thumbnail(filepath, face_box, stud_id)
        else:
            logger.error(f"Failed to process image for {stud_id}.")


def get_img_from_embeddings(stud_id: str) -> Path | None:
    thumbnail_path = Config.THUMBNAIL_DIR / f"{stud_id}.jpg"
    if thumbnail_path.exists():
        return thumbnail_path
    logger.warning(f"Thumbnail for ID {stud_id} not found.")
    return None

def load_all_encodings() -> dict[str, list[float]]:
    return vector_store.all()
