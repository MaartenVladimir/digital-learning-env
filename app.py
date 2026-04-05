import sys
import os

# Import algebra_checker from the sibling repo
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
app.secret_key = 'dev-secret-key-change-in-production'

ITEMS_DIR = os.path.join(os.path.dirname(__file__), 'items')

GOALS = {
    'solve_equation': SolveEquationGoal,
    'solve_quadratic_equation': SolveQuadraticEquationGoal,
    'direct_answer': DirectAnswerGoal,
}


def load_module(module_id):
    path = os.path.join(ITEMS_DIR, f'{module_id}.json')
    with open(path) as f:
        return json.load(f)


def load_item(module_id, item_index, student_id):
    """Load and instantiate a single item for a specific student."""
    item = load_module(module_id)[item_index]
    return instantiate_item(item, student_id)


@app.before_request
def setup():
    db.init_db()


@app.route('/')
def index():
    return render_template('login.html')


@app.route('/login', methods=['POST'])
def login():
    student_id = request.form.get('student_id', '').strip()
    group = request.form.get('group', 'control')
    if not student_id:
        return redirect(url_for('index'))

    db.register_student(student_id, group)
    session['student_id'] = student_id
    session['group'] = group
    session['item_index'] = 0
    session['crisis_phase'] = None
    return redirect(url_for('module', module_id='d1'))


def _crisis_render_item(item, crisis_phase):
    """
    Return (render_item, post_crisis_explanation) for the current crisis phase.
    phase = crisis -> Students are now in a crisis and get no explenation 
    phase = post_crisis -> Students are now in a post crisis and get explenation
    """
    if crisis_phase == "crisis":
        return item, None
    if crisis_phase == 'post_crisis':
        post = item['post_crisis']
        explanation = {
            'text': post.get('explanation', ''),
            'latex': post.get('explanation_latex', ''),
        }
        return item, explanation
    # 'crisis' phase: show the crisis item itself
    return item, None


@app.route('/module/<module_id>')
def module(module_id):
    if 'student_id' not in session:
        return redirect(url_for('index'))

    items = load_module(module_id)
    item_index = session.get('item_index', 0)

    if item_index >= len(items):
        return redirect(url_for('done'))

    item = instantiate_item(items[item_index], session['student_id'])
    if session.get('crisis_phase') == 'post_crisis':
        # Generate different paramters for the post-crisis retry
        item = instantiate_item(items[item_index], session['student_id'] + 'rr')
    session['module_id'] = module_id

    group = session.get('group', 'control')
    crisis_phase = session.get('crisis_phase')

    # Treatment group entering a crisis item for the first time
    if item.get('is_crisis') and group == 'treatment' and crisis_phase is None:
        session['crisis_phase'] = 'crisis'
        crisis_phase = 'crisis'

    post_crisis_explanation = None
    if item.get('is_crisis') and group == 'treatment' and crisis_phase:
        render_item, post_crisis_explanation = _crisis_render_item(item, crisis_phase)
    else:
        render_item = item

    session['current_step'] = render_item['sympy_str']

    return render_template('exercise.html',
        item=render_item,
        item_num=item_index + 1,
        total=len(items),
        module_id=module_id,
        crisis_phase=crisis_phase,
        post_crisis_explanation=post_crisis_explanation,
    )


@app.route('/check', methods=['POST'])
def check():
    if 'student_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    data = request.get_json()
    step_input = data.get('step', '').strip()

    module_id = session.get('module_id', 'd1')
    item_index = session.get('item_index', 0)
    prev_step = session.get('current_step', '')

    item = load_item(module_id, item_index, session['student_id'])

    goal = GOALS[item['goal']](item_context=item)
    print(step_input)
    result = goal.check_step(prev_step, step_input)

    group = session.get('group', 'control')
    crisis_phase = session.get('crisis_phase')

    db.log_attempt(
        student_id=session['student_id'],
        item_id=item['id'],
        step_input=step_input,
        is_correct=result.is_correct,
        error_id=result.error_id,
        module_id=module_id,
        is_crisis=item.get('is_crisis', False),
        crisis_phase=crisis_phase,
    )

    if result.is_correct and result.status != StepStatus.COMPLETE:
        session['current_step'] = step_input

    if result.status == StepStatus.COMPLETE:
        if item.get('is_crisis') and group == 'treatment' and crisis_phase:
            if crisis_phase == 'crisis':
                session['crisis_phase'] = 'post_crisis'
                session['current_step'] = item['sympy_str']
                return jsonify({
                    'status': 'PHASE_COMPLETE',
                    'is_correct': True,
                    'message': 'Goed gedaan! Lees de uitleg en probeer opnieuw.',
                })
            else:
                session['crisis_phase'] = None
                session['item_index'] = item_index + 1
        else:
            session['item_index'] = item_index + 1

    return jsonify({
        'status': result.status.name,
        'is_correct': result.is_correct,
        'message': result.error_diagnosis or result.strategy_message or result.message,
    })


@app.route('/done')
def done():
    return render_template('done.html')


if __name__ == '__main__':
    app.run(debug=True)
