import functools
from flask import Blueprint, request, session, redirect, url_for, render_template, jsonify
import services.exercise_service as exercise
import services.module_service as module_service
import services.authentication_service as authentication

bp = Blueprint('student', __name__)


def student_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if 'student_pk' not in session:
            return redirect(url_for('student.index'))
        return f(*args, **kwargs)
    return wrapper


# Authentication routing

@bp.route('/')
def index():
    return render_template('login.html')


@bp.post('/login')
def login():
    class_id   = request.form.get('class_id', '').strip()
    student_id = request.form.get('student_id', '').strip()

    if not class_id or not student_id:
        return render_template('login.html', error='Vul beide velden in.')

    student = authentication.authenticate_student(student_id, class_id)
    if student is None:
        return render_template('login.html', error='Onbekende leerlingnummer of klas. Neem contact op met je docent.')

    session['student_pk'] = student.pk
    session['student_id'] = student.id
    session['class_id']   = student.class_id
    session['group']      = student.group_name
    return redirect(url_for('student.home'))


@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('student.index'))


# Home page routing

@bp.route('/home')
@student_required
def home():
    student_pk = session['student_pk']
    class_id   = session['class_id']

    modules  = module_service.get_visible_modules(class_id)
    progress = {p.module_id: p for p in module_service.get_all_module_progress(student_pk)}

    module_list = [
        {
            'module': m,
            'status': progress[m.id].status if m.id in progress else 'not_started',
        }
        for m in modules
    ]
    return render_template('home.html', modules=module_list)


# Exercise routing

@bp.route('/module/<module_id>')
@student_required
def module(module_id):
    student_pk = session['student_pk']
    class_id   = session['class_id']
    group      = session['group']

    visible_ids = {m.id for m in module_service.get_visible_modules(class_id)}
    if module_id not in visible_ids:
        return redirect(url_for('student.home'))

    mod      = module_service.load_module(module_id)
    items    = mod['items']
    progress = module_service.start_module(student_pk, module_id)

    if progress.item_index >= len(items):
        return redirect(url_for('student.home'))

    retry_n = session.get('item_retry', 0)
    item    = exercise.get_item(items, progress.item_index, session['student_id'], retry_n)

    crisis_phase = exercise.resolve_crisis_phase(student_pk, module_id, item, group)
    exercise.start_item_session(student_pk, module_id, item['id'], crisis_phase,
                                is_crisis=item.get('is_crisis', False), retry_n=retry_n)

    if crisis_phase == 'post_crisis':
        item = exercise.get_item(items, progress.item_index, session['student_id'] + 'rr', 0)

    session['module_id'] = module_id
    if 'parts' in item:
        session['current_steps'] = {str(i): part['sympy_str'] for i, part in enumerate(item['parts'])}
        session.pop('current_step', None)
        session.pop('parts_done', None)
    else:
        session['current_step'] = item['sympy_str']
        session.pop('current_steps', None)
        session.pop('parts_done', None)

    return render_template('exercise.html',
        item=item,
        item_num=progress.item_index + 1,
        total=len(items),
        module_id=module_id,
        crisis_phase=crisis_phase,
        post_crisis_explanation=exercise.get_post_crisis_explanation(item, crisis_phase),
        input_hint=exercise.get_input_hint(item),
    )


@bp.post('/check')
@student_required
def check():
    body       = request.get_json()
    step_input = body.get('step', '').strip()
    part_index = body.get('part_index')   # None for single-part items
    student_pk = session['student_pk']
    module_id  = session['module_id']
    group      = session['group']
    retry_n    = session.get('item_retry', 0)

    mod      = module_service.load_module(module_id)
    progress = exercise.get_progress(student_pk, module_id)
    item         = exercise.get_item(mod['items'], progress.item_index, session['student_id'], retry_n)
    crisis_phase = exercise.resolve_crisis_phase(student_pk, module_id, item, group)

    # Post-crisis items are regenerated with a different seed in the module route;
    # mirror that here so expected_answer and graph match what was shown.
    if crisis_phase == 'post_crisis':
        item = exercise.get_item(mod['items'], progress.item_index, session['student_id'] + 'rr', 0)

    # ── Multi-part item ────────────────────────────────────────────────────────
    if part_index is not None:
        part_index = int(part_index)
        sub_item   = item['parts'][part_index]
        prev_step  = session.get('current_steps', {})[str(part_index)]
        result     = exercise.check_step(sub_item, prev_step, step_input)

        if not result.is_correct:
            session['had_error'] = True

        item_session = exercise.record_step(
            student_pk, module_id, item['id'], crisis_phase,
            step_input, result.is_correct, result.error_id,
            mod.get('log_steps', False),
        )

        if result.is_intermediate:
            steps = dict(session.get('current_steps', {}))
            steps[str(part_index)] = step_input
            session['current_steps'] = steps

        if result.is_complete:
            parts_done = set(session.get('parts_done', []))
            parts_done.add(part_index)
            session['parts_done'] = list(parts_done)

            if len(parts_done) < len(item['parts']):
                return jsonify({'status': 'PART_COMPLETE', 'is_correct': True, 'message': ''})

            # All parts done
            outcome = exercise.handle_completion(
                student_pk, module_id, item, item_session,
                progress.item_index, len(mod['items']),
                group, crisis_phase,
                had_error=session.pop('had_error', False),
                retry_n=retry_n,
            )
            if outcome['action'] == 'retry':
                session['item_retry'] = outcome['retry_n']
                session['current_steps'] = {str(i): part['sympy_str']
                                            for i, part in enumerate(item['parts'])}
                session['parts_done'] = []
                return jsonify({'status': 'RETRY', 'is_correct': True,
                                'message': outcome['message']})
            session.pop('item_retry', None)

        return jsonify({
            'status': result.status,
            'is_correct': result.is_correct,
            'message': result.message,
        })

    # ── Single-part item ───────────────────────────────────────────────────────
    prev_step    = session['current_step']
    result       = exercise.check_step(item, prev_step, step_input)

    if not result.is_correct:
        session['had_error'] = True

    item_session = exercise.record_step(
        student_pk, module_id, item['id'], crisis_phase,
        step_input, result.is_correct, result.error_id,
        mod.get('log_steps', False),
    )

    if result.is_intermediate:
        session['current_step'] = step_input

    if result.is_complete:
        outcome = exercise.handle_completion(
            student_pk, module_id, item, item_session,
            progress.item_index, len(mod['items']),
            group, crisis_phase,
            had_error=session.pop('had_error', False),
            retry_n=retry_n,
        )
        if outcome['action'] == 'phase_complete':
            session['current_step'] = item['sympy_str']
            return jsonify({'status': 'PHASE_COMPLETE', 'is_correct': True,
                            'message': outcome['message']})
        if outcome['action'] == 'retry':
            session['item_retry'] = outcome['retry_n']
            session['current_step'] = outcome['reset_step']
            return jsonify({'status': 'RETRY', 'is_correct': True,
                            'message': outcome['message']})
        session.pop('item_retry', None)

    return jsonify({
        'status': result.status,
        'is_correct': result.is_correct,
        'message': result.message,
    })


@bp.route('/done')
def done():
    return render_template('done.html')
