import db


def get_dashboard_data() -> dict:
    return {
        'classes': db.get_all_classes(),
        'all_modules': db.get_all_modules(),
    }


def create_class(name: str) -> None:
    if name and db.get_klas(name) is None:
        db.create_klas(name, name)


def register_module(module_id: str, title: str) -> None:
    if module_id and title:
        db.register_module(module_id, title)


def get_class_data(class_id: str) -> dict | None:
    klas = db.get_klas(class_id)
    if not klas:
        return None
    class_modules = db.get_class_modules(class_id)
    assigned_ids  = {m.id for m, _ in class_modules}
    unassigned    = [m for m in db.get_all_modules() if m.id not in assigned_ids]
    return {
        'klas': klas,
        'students': db.get_students_in_class(class_id),
        'class_modules': class_modules,
        'unassigned_modules': unassigned,
    }


def create_student(student_id: str, class_id: str, group: str) -> None:
    if student_id and db.get_student(student_id, class_id) is None:
        db.create_student(student_id, class_id, group)


def add_module_to_class(class_id: str, module_id: str) -> None:
    if module_id:
        db.add_module_to_class(class_id, module_id)


def set_module_visibility(class_id: str, module_id: str, is_visible: bool) -> None:
    db.set_module_visibility(class_id, module_id, is_visible)


def get_session_data(module_id: str) -> list[dict]:
    sessions = db.get_sessions(module_id) if module_id else []
    for s in sessions:
        s['steps'] = db.get_steps(s['id'])
    return sessions
