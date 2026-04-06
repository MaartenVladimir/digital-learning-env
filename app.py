import sys
import os
import functools

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'feedback-generator'))

from flask import Flask, render_template, request, session, redirect, url_for, jsonify
import json

from algebra_checker.goals.solve_equation import SolveEquationGoal
from algebra_checker.goals.solve_quadratic_equation import SolveQuadraticEquationGoal
from algebra_checker.goals.direct_answer import DirectAnswerGoal
from algebra_checker.generator import instantiate_item
from algebra_checker.validator import StepStatus
import db

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

ITEMS_DIR = os.path.join(os.path.dirname(__file__), 'items')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin')

GOALS = {
    'solve_equation': SolveEquationGoal,
    'solve_quadratic_equation': SolveQuadraticEquationGoal,
    'direct_answer': DirectAnswerGoal,
}


def load_module(module_id):
    path = os.path.join(ITEMS_DIR, f'{module_id}.json')
    with open(path) as f:
        return json.load(f)  # {'log_steps': bool, 'items': [...]}


def load_item(module_id, item_index, seed):
    return instantiate_item(load_module(module_id)['items'][item_index], seed)


def _crisis_phase_from_db(student_pk, module_id, item_id):
    """Restore crisis phase from any open item session (supports resume)."""
    for phase in ('post_crisis', 'crisis'):
        if db.get_active_item_session(student_pk, module_id, item_id, phase):
            return phase
    return None


def student_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if 'student_pk' not in session:
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return wrapper


def sync_modules():
    """Auto-register any JSON files found in /items/ that aren't in the DB yet."""
    for fname in os.listdir(ITEMS_DIR):
        if not fname.endswith('.json'):
            continue
        module_id = fname[:-5]
        path = os.path.join(ITEMS_DIR, fname)
        with open(path) as f:
            data = json.load(f)
        title = data.get('title', module_id)
        db.register_module(module_id, title)


@app.before_request
def setup():
    db.init_db()
    sync_modules()

# Student authentication 

@app.route('/')
def index():
    return render_template('login.html')


@app.route('/login', methods=['POST'])
def login():
    class_id = request.form.get('class_id', '').strip()
    student_id = request.form.get('student_id', '').strip()
    if not class_id or not student_id:
        return render_template('login.html', error='Vul beide velden in.')

    if db.get_klas(class_id) is None:
        return render_template('login.html', error='Onbekende klas.')

    student = db.get_student(student_id, class_id)
    if student is None:
        return render_template('login.html', error='Onbekend leerlingnummer. Neem contact op met je docent.')

    session['student_pk'] = student.pk
    session['student_id'] = student.id
    session['class_id'] = student.class_id
    session['group'] = student.group_name
    return redirect(url_for('home'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# Student home page routing

@app.route('/home')
@student_required
def home():
    student_pk = session['student_pk']
    class_id = session['class_id']

    modules = db.get_visible_modules(class_id)
    progress_by_module = {p.module_id: p for p in db.get_all_module_progress(student_pk)}

    module_list = [
        {
            'module': m,
            'status': progress_by_module[m.id].status if m.id in progress_by_module else 'not_started',
        }
        for m in modules
    ]
    return render_template('home.html', modules=module_list)


# Exercise routing

@app.route('/module/<module_id>')
@student_required
def module(module_id):
    student_pk = session['student_pk']
    class_id = session['class_id']
    group = session['group']

    if module_id not in {m.id for m in db.get_visible_modules(class_id)}:
        return redirect(url_for('home'))

    mod = load_module(module_id)
    items = mod['items']

    progress = db.start_module(student_pk, module_id)
    item_index = progress.item_index

    if item_index >= len(items):
        return redirect(url_for('home'))

    item = instantiate_item(items[item_index], session['student_id'])

    # Restore crisis phase from open sessions
    crisis_phase = _crisis_phase_from_db(student_pk, module_id, item['id'])

    if item.get('is_crisis') and group == 'treatment' and crisis_phase is None:
        crisis_phase = 'crisis'

    # Ensure an open session exists for the current item + phase
    db.start_item_session(student_pk, module_id, item['id'], crisis_phase)

    # post_crisis: different seed so the student gets new parameter values
    if crisis_phase == 'post_crisis':
        item = instantiate_item(items[item_index], session['student_id'] + 'rr')
    session['module_id'] = module_id
    session['current_step'] = item['sympy_str']

    post_crisis_explanation = None
    if item.get('is_crisis') and group == 'treatment' and crisis_phase == 'post_crisis':
        post = item.get('post_crisis', {})
        post_crisis_explanation = {
            'text': post.get('explanation', ''),
            'latex': post.get('explanation_latex', ''),
        }

    return render_template('exercise.html',
        item=item,
        item_num=item_index + 1,
        total=len(items),
        module_id=module_id,
        crisis_phase=crisis_phase,
        post_crisis_explanation=post_crisis_explanation,
    )


@app.route('/check', methods=['POST'])
@student_required
def check():
    data = request.get_json()
    step_input = data.get('step', '').strip()

    student_pk = session['student_pk']
    module_id = session.get('module_id', '')
    prev_step = session.get('current_step', '')
    group = session['group']

    mod = load_module(module_id)
    items = mod['items']
    log_steps = mod.get('log_steps', False)

    progress = db.get_module_progress(student_pk, module_id)
    item_index = progress.item_index
    item = instantiate_item(items[item_index], session['student_id'])

    crisis_phase = _crisis_phase_from_db(student_pk, module_id, item['id'])
    goal = GOALS[item['goal']](item_context=item)
    result = goal.check_step(prev_step, step_input)

    item_session = db.get_active_item_session(student_pk, module_id, item['id'], crisis_phase)
    if item_session:
        db.record_attempt(item_session.id, step_input, result.is_correct, result.error_id, log_steps)

    if result.is_correct and result.status != StepStatus.COMPLETE:
        session['current_step'] = step_input

    if result.status == StepStatus.COMPLETE:
        if item_session:
            db.complete_item_session(item_session.id)

        if item.get('is_crisis') and group == 'treatment' and crisis_phase:
            if crisis_phase == 'crisis':
                # Open the post_crisis session so it persists across reloads
                db.start_item_session(student_pk, module_id, item['id'], 'post_crisis')
                session['current_step'] = item['sympy_str']
                return jsonify({
                    'status': 'PHASE_COMPLETE',
                    'is_correct': True,
                    'message': 'Goed gedaan! Lees de uitleg en probeer opnieuw.',
                })
            else:
                db.advance_module(student_pk, module_id, item_index + 1, len(items))
        else:
            db.advance_module(student_pk, module_id, item_index + 1, len(items))

    return jsonify({
        'status': result.status.name,
        'is_correct': result.is_correct,
        'message': result.error_diagnosis or result.strategy_message or result.message,
    })


#Admin authentication

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html', error='Verkeerd wachtwoord.')
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('admin_login'))


# Admin dashboard

@app.route('/admin')
@admin_required
def admin_dashboard():
    return render_template('admin_dashboard.html',
        classes=db.get_all_classes(),
        all_modules=db.get_all_modules(),
    )


@app.route('/admin/class/create', methods=['POST'])
@admin_required
def admin_create_class():
    name = request.form.get('name', '').strip()
    if name and db.get_klas(name) is None:
        db.create_klas(name, name)
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/module/register', methods=['POST'])
@admin_required
def admin_register_module():
    module_id = request.form.get('module_id', '').strip()
    title = request.form.get('title', '').strip()
    if module_id and title:
        db.register_module(module_id, title)
    return redirect(url_for('admin_dashboard'))


# Admin class management

@app.route('/admin/class/<class_id>')
@admin_required
def admin_class(class_id):
    klas = db.get_klas(class_id)
    if not klas:
        return redirect(url_for('admin_dashboard'))

    class_modules = db.get_class_modules(class_id)
    assigned_ids = {m.id for m, _ in class_modules}
    unassigned = [m for m in db.get_all_modules() if m.id not in assigned_ids]

    return render_template('admin_class.html',
        klas=klas,
        students=db.get_students_in_class(class_id),
        class_modules=class_modules,
        unassigned_modules=unassigned,
    )


@app.route('/admin/class/<class_id>/student/create', methods=['POST'])
@admin_required
def admin_create_student(class_id):
    student_id = request.form.get('student_id', '').strip()
    group = request.form.get('group', 'control').strip()
    if student_id and db.get_student(student_id, class_id) is None:
        db.create_student(student_id, class_id, group)
    return redirect(url_for('admin_class', class_id=class_id))


@app.route('/admin/class/<class_id>/module/add', methods=['POST'])
@admin_required
def admin_add_module(class_id):
    module_id = request.form.get('module_id', '').strip()
    if module_id:
        db.add_module_to_class(class_id, module_id)
    return redirect(url_for('admin_class', class_id=class_id))


@app.route('/admin/class/<class_id>/module/<module_id>/toggle', methods=['POST'])
@admin_required
def admin_toggle_module(class_id, module_id):
    is_visible = request.form.get('is_visible') == '1'
    db.set_module_visibility(class_id, module_id, is_visible)
    return redirect(url_for('admin_class', class_id=class_id))


@app.route('/done')
def done():
    return render_template('done.html')


if __name__ == '__main__':
    app.run(debug=True)
