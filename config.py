from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    MAX_IMAGE_DIMENSION: int = int(os.getenv("MAX_IMAGE_DIMENSION", 800))
    FACE_DETECTION_MODEL: str = os.getenv("FACE_DETECTION_MODEL", "hog")
    NUM_ENCODING_JITTERS: int = int(os.getenv("NUM_ENCODING_JITTERS", 1))
    VECTOR_STORE_NAME: str = os.getenv("VECTOR_STORE", "vector_store")
    STUD_IMAGES_FOLDER_NAME: str = os.getenv("STUD_IMAGES_FOLDER_NAME", "student_images")

    DEPARTURE_MINUTES = 2
    FRAME_WIDTH, FRAME_HEIGHT = 640, 480
    FACE_MATCH_THRESHOLD = 0.60
    MODE_DISPLAY_DURATION= 10

    STORAGE_PATH: Path = Path(os.getenv("STORAGE_PATH", "./data"))
    DB_NAME: str = os.getenv("DB_NAME", "STEP_SCHOOL_DB")
    MARK_LEFT_DB_NAME = os.getenv("MARK_LEFT_DB_NAME", "LEFT_STEP_SCHOOL_DB")
    DB: Path = STORAGE_PATH / f"{DB_NAME}.sqlite3"
    LEFT_DB:Path = STORAGE_PATH / f"{MARK_LEFT_DB_NAME}.sqlite3"
    VECTOR_STORE_FILE: Path = STORAGE_PATH / f"{VECTOR_STORE_NAME}.pkl"
    STUD_IMAGES_FILE: Path = STORAGE_PATH / STUD_IMAGES_FOLDER_NAME

