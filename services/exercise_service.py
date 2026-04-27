from dataclasses import dataclass
from algebra_checker.generator import instantiate_item
from algebra_checker.goals.solve_equation import SolveEquationGoal
from algebra_checker.goals.solve_quadratic_equation import SolveQuadraticEquationGoal
from algebra_checker.goals.direct_answer import DirectAnswerGoal
from algebra_checker.goals.simplify_expression import SimplifyExpressionGoal
from algebra_checker.validator import StepStatus

import db


@dataclass
class CheckResult:
    is_correct: bool
    is_complete: bool       # correct final step — advance or retry
    is_intermediate: bool   # correct but not final — update current step
    status: str             # status name for the JSON response
    message: str
    error_id: str | None    # passed through to record_step

# The Goals registered in the algebra_checker
GOALS = {
    'solve_equation': SolveEquationGoal,
    'solve_quadratic_equation': SolveQuadraticEquationGoal,
    'direct_answer': DirectAnswerGoal,
    'simplify_expression': SimplifyExpressionGoal,
}

def build_seed(student_id: str, retry_n: int) -> str:
    return student_id + (f'_r{retry_n}' if retry_n else '')

def get_item(items: list, index: int, student_id: str, retry_n: int) -> dict:
    return instantiate_item(items[index], build_seed(student_id, retry_n))

def resolve_crisis_phase(student_pk: int, module_id: str,
                          item: dict, group: str) -> str | None:
    for phase in ('post_crisis', 'crisis'):
        if db.get_active_item_session(student_pk, module_id, item['id'], phase):
            return phase
    if item.get('is_crisis') and group == 'treatment':
        return 'crisis'
    return None

def get_post_crisis_explanation(item: dict, crisis_phase: str | None) -> dict | None:
    if not (item.get('is_crisis') and crisis_phase == 'post_crisis'):
        return None
    post = item.get('post_crisis', {})
    return {
        'text': post.get('explanation', ''),
        'latex': ' '.join(post['explanation_latex']) if isinstance(post.get('explanation_latex'), list) else post.get('explanation_latex', ''),
    }

def get_progress(student_pk: int, module_id: str):
    return db.get_module_progress(student_pk, module_id)

def record_step(student_pk: int, module_id: str, item_id: str,
                crisis_phase, step_input: str, is_correct: bool,
                error_id, log_steps: bool):
    """Record a submitted step and return the active item session."""
    item_session = db.get_active_item_session(student_pk, module_id, item_id, crisis_phase)
    if item_session:
        db.record_attempt(item_session.id, step_input, is_correct, error_id, log_steps)
    return item_session

def start_item_session(student_pk: int, module_id: str, item_id: str,
                       crisis_phase, is_crisis: bool = False, retry_n: int = 0):
    return db.start_item_session(student_pk, module_id, item_id, crisis_phase,
                                 is_crisis=is_crisis, retry_n=retry_n)

def _hint_for_goal(goal_name: str) -> str | None:
    goal_class = GOALS.get(goal_name)
    return getattr(goal_class, 'input_hint', None) if goal_class else None

def get_input_hint(item: dict) -> str | list[str | None] | None:
    """
    Single-part: returns a hint string (or None).
    Multi-part:  returns a list with one hint per part (entry may be None).
    Item-level 'input_hint' overrides everything.
    """
    if 'input_hint' in item and not 'parts' in item:
        hint = item['input_hint']
        return ' '.join(hint) if isinstance(hint, list) else hint
    if 'parts' in item:
        hints = []
        for part in item['parts']:
            h = part.get('input_hint') or _hint_for_goal(part.get('goal', ''))
            hints.append(' '.join(h) if isinstance(h, list) else h)
        return hints
    return _hint_for_goal(item.get('goal', ''))

def check_step(item: dict, prev_step: str, step_input: str) -> CheckResult:
    goal = GOALS[item['goal']](item_context=item)
    raw = goal.check_step(prev_step, step_input)
    return CheckResult(
        is_correct=raw.is_correct,
        is_complete=raw.status == StepStatus.COMPLETE,
        is_intermediate=raw.is_correct and raw.status != StepStatus.COMPLETE,
        status=raw.status.name,
        message=raw.error_diagnosis or raw.strategy_message or raw.message,
        error_id=raw.error_id,
    )

def handle_completion(
    student_pk: int, module_id: str, item: dict,
    item_session, item_index: int, total: int,
    group: str, crisis_phase: str | None,
    had_error: bool, retry_n: int,
) -> dict:
    """
    Decides what happens after a correct final step.
    
    1. If its a pre-crisis -> Go to post-crisis (regenerate paramaters + add explanation)
    2. If its a post-crisis -> Advance to next question
    3. If student made a mistake during solving -> Retry question (regenerate paramters, no explanation)
    4. In all other cases -> Advance to next question
    """
    db.complete_item_session(item_session.id)

    if item.get('is_crisis') and group == 'treatment' and crisis_phase:
        if crisis_phase == 'crisis':
            db.start_item_session(student_pk, module_id, item['id'], 'post_crisis',
                                  is_crisis=item.get('is_crisis', False))
            return {'action': 'phase_complete',
                    'message': 'Goed gedaan! Lees de uitleg en probeer opnieuw.'}
        else:
            db.advance_module(student_pk, module_id, item_index + 1, total)
            return {'action': 'advance'}

    if had_error:
        return {'action': 'retry',
                'retry_n': retry_n + 1,
                'reset_step': item.get('sympy_str', ''),  # empty for multi-part items
                'message': 'Goed gedaan! Probeer de opgave nu opnieuw met andere getallen.'}

    db.advance_module(student_pk, module_id, item_index + 1, total)
    return {'action': 'advance'}

