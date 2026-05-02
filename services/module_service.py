import copy
import os
import json
import random
import db

ITEMS_DIR = os.path.join(os.path.dirname(__file__), '..', 'items')

def load_module(module_id: str, student_id: str | None = None) -> dict:
    if '_selftest_' in module_id:
        return _load_selftest_module(module_id, student_id)
    path = os.path.join(ITEMS_DIR, f'{module_id}.json')
    with open(path, encoding='utf-8') as f:
        return json.load(f)  # {'log_steps': bool, 'items': [...]}

def _load_selftest_module(selftest_id: str, student_id: str | None) -> dict:
    base_id, attempt_str = selftest_id.rsplit('_selftest_', 1)
    path = os.path.join(ITEMS_DIR, f'{base_id}.json')
    with open(path, encoding='utf-8') as f:
        base = json.load(f)
    items = copy.deepcopy(base['items'])
    if student_id:
        rng = random.Random(student_id + base_id)
        rng.shuffle(items)
    return {
        'title': base.get('title', base_id),
        'log_steps': base.get('log_steps', True),
        'selftest': True,
        'selftest_attempt': int(attempt_str),
        'items': items,
    }

def sync_modules() -> None:
    """Auto-register any JSON files in /items/ that aren't in the DB yet."""
    for fname in os.listdir(ITEMS_DIR):
        if not fname.endswith('.json'):
            continue
        module_id = fname[:-5]
        # Never register selftest variants, this is annoying the admin panel, but they are in the .db file
        if '_selftest_' in module_id:
            continue
        data = load_module(module_id)
        db.register_module(module_id, data.get('title', module_id))

def start_module(student_pk: int, module_id: str):
    return db.start_module(student_pk, module_id)

def get_visible_modules(class_id: str) -> list:
    return db.get_visible_modules(class_id)

def get_all_module_progress(student_pk: int) -> list:
    return db.get_all_module_progress(student_pk)
