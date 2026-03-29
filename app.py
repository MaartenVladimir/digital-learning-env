import sys
import os

# Import algebra_checker from the sibling repo
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'feedback-generator'))

from flask import Flask, render_template, request, session, redirect, url_for, jsonify
import json

from algebra_checker.goals.solve_equation import SolveEquationGoal
from algebra_checker.validator import StepStatus
import db

app = Flask(__name__)
app.secret_key = 'dev-secret-key-change-in-production'

ITEMS_DIR = os.path.join(os.path.dirname(__file__), 'items')

GOALS = {
    'solve_equation': SolveEquationGoal,
}


def load_module(module_id):
    path = os.path.join(ITEMS_DIR, f'{module_id}.json')
    with open(path) as f:
        return json.load(f)


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
    return redirect(url_for('module', module_id='d1'))


@app.route('/module/<module_id>')
def module(module_id):
    if 'student_id' not in session:
        return redirect(url_for('index'))

    items = load_module(module_id)
    item_index = session.get('item_index', 0)

    if item_index >= len(items):
        return redirect(url_for('done'))

    item = items[item_index]
    session['module_id'] = module_id
    session['current_step'] = item['sympy_str']

    return render_template('exercise.html',
        item=item,
        item_num=item_index + 1,
        total=len(items),
        module_id=module_id,
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

    items = load_module(module_id)
    item = items[item_index]

    goal = GOALS[item['goal']]()
    result = goal.check_step(prev_step, step_input)

    db.log_attempt(
        student_id=session['student_id'],
        item_id=item['id'],
        step_input=step_input,
        is_correct=result.is_correct,
        error_id=result.error_id,
        module_id=module_id,
        is_crisis=item.get('is_crisis', False),
    )

    if result.is_correct and result.status != StepStatus.COMPLETE:
        session['current_step'] = step_input

    if result.status == StepStatus.COMPLETE:
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
