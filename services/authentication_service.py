import db
from db import Student

def authenticate_student(student_id: str, class_id: str) -> Student:
    if db.get_klas(class_id) is None:
        return None
    return db.get_student(student_id, class_id)