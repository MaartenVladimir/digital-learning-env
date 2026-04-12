import os
import json
import db

ITEMS_DIR = os.path.join(os.path.dirname(__file__), '..', 'items')

def load_module(module_id: str) -> dict:
    path = os.path.join(ITEMS_DIR, f'{module_id}.json')
    with open(path, encoding='utf-8') as f:
        return json.load(f)  # {'log_steps': bool, 'items': [...]}

def sync_modules() -> None:
    """Auto-register any JSON files in /items/ that aren't in the DB yet."""
    for fname in os.listdir(ITEMS_DIR):
        if not fname.endswith('.json'):
            continue
        module_id = fname[:-5]
        data = load_module(module_id)
        db.register_module(module_id, data.get('title', module_id))

def start_module(student_pk: int, module_id: str):
    return db.start_module(student_pk, module_id)

def get_visible_modules(class_id: str) -> list:
    return db.get_visible_modules(class_id)

def get_all_module_progress(student_pk: int) -> list:
    return db.get_all_module_progress(student_pk)
