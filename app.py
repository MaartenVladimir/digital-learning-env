import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'feedback-generator'))

from flask import Flask
import db
import services.module_service as module_service


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    with app.app_context():
        db.init_db()
        module_service.sync_modules()

    from blueprints.student import bp as student_bp
    from blueprints.admin import bp as admin_bp
    app.register_blueprint(student_bp)
    app.register_blueprint(admin_bp)

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
