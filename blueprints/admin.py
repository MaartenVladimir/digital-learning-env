import os
import functools
import services.admin_service as admin_service
from flask import Blueprint, render_template, request, session, redirect, url_for

bp = Blueprint('admin', __name__, url_prefix='/admin')

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin')


def admin_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return wrapper


# Authentication routing 

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['is_admin'] = True
            return redirect(url_for('admin.dashboard'))
        return render_template('admin_login.html', error='Verkeerd wachtwoord.')
    return render_template('admin_login.html')


@bp.route('/logout')
def logout():
    session.pop('is_admin', None)
    return redirect(url_for('admin.login'))


# Dashboard routing

@bp.route('/')
@admin_required
def dashboard():
    data = admin_service.get_dashboard_data()
    return render_template('admin_dashboard.html', **data)


@bp.post('/class/create')
@admin_required
def create_class():
    admin_service.create_class(request.form.get('name', '').strip())
    return redirect(url_for('admin.dashboard'))


@bp.post('/module/register')
@admin_required
def register_module():
    admin_service.register_module(
        request.form.get('module_id', '').strip(),
        request.form.get('title', '').strip(),
    )
    return redirect(url_for('admin.dashboard'))


# Clas management routing

@bp.route('/class/<class_id>')
@admin_required
def klas(class_id):
    data = admin_service.get_class_data(class_id)
    if not data:
        return redirect(url_for('admin.dashboard'))
    return render_template('admin_class.html', **data)


@bp.post('/class/<class_id>/student/create')
@admin_required
def create_student(class_id):
    admin_service.create_student(
        request.form.get('student_id', '').strip(),
        class_id,
        request.form.get('group', 'control').strip(),
    )
    return redirect(url_for('admin.klas', class_id=class_id))


@bp.post('/class/<class_id>/module/add')
@admin_required
def add_module(class_id):
    admin_service.add_module_to_class(class_id, request.form.get('module_id', '').strip())
    return redirect(url_for('admin.klas', class_id=class_id))


@bp.post('/class/<class_id>/module/<module_id>/toggle')
@admin_required
def toggle_module(class_id, module_id):
    admin_service.set_module_visibility(class_id, module_id,
                                        request.form.get('is_visible') == '1')
    return redirect(url_for('admin.klas', class_id=class_id))


# Data inspection routing

@bp.route('/data')
@admin_required
def data():
    all_modules = admin_service.get_dashboard_data()['all_modules']
    module_id   = request.args.get('module_id', all_modules[0].id if all_modules else '')
    return render_template('admin_data.html',
        modules=all_modules,
        selected=module_id,
        sessions=admin_service.get_session_data(module_id),
    )
