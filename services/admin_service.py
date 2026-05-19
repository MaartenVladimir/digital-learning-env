import os
import json
import db

ITEMS_DIR = os.path.join(os.path.dirname(__file__), '..', 'items')


def _get_item_count(module_id: str) -> int:
    path = os.path.join(ITEMS_DIR, f'{module_id}.json')
    try:
        with open(path, encoding='utf-8') as f:
            return len(json.load(f).get('items', []))
    except (FileNotFoundError, json.JSONDecodeError):
        return 0


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


def get_student_progress_overview(class_id: str) -> dict | None:
    klas = db.get_klas(class_id)
    if not klas:
        return None

    students = db.get_students_in_class(class_id)
    class_modules_data = db.get_class_modules(class_id)
    modules = [m for m, _ in class_modules_data]

    module_item_counts = {m.id: _get_item_count(m.id) for m in modules}

    completion_by = {
        (r['student_pk'], r['module_id']): r['completed_count']
        for r in db.get_class_item_completion(class_id)
    }
    progress_by = {
        (r['student_pk'], r['module_id']): r['status']
        for r in db.get_class_module_progress(class_id)
    }

    student_data = []
    for s in students:
        module_info = {}
        for m in modules:
            total = module_item_counts[m.id]
            status = progress_by.get((s.pk, m.id), 'not_started')
            completed = completion_by.get((s.pk, m.id), 0)

            selftests = []
            n = 1
            while True:
                st_id = f'{m.id}_selftest_{n}'
                st_status = progress_by.get((s.pk, st_id))
                if st_status is None:
                    break
                selftests.append({
                    'attempt': n,
                    'status': st_status,
                    'completed': completion_by.get((s.pk, st_id), 0),
                    'total': total,
                })
                n += 1

            module_info[m.id] = {
                'status': status,
                'completed': completed,
                'total': total,
                'selftests': selftests,
            }

        student_data.append({
            'id': s.id,
            'group_name': s.group_name,
            'modules': module_info,
        })

    return {'klas': klas, 'modules': modules, 'students': student_data}


def get_session_data(module_id: str) -> list[dict]:
    sessions = db.get_sessions(module_id) if module_id else []
    for s in sessions:
        s['steps'] = db.get_steps(s['id'])
    return sessions
