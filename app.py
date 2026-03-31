import os
import sys
import webbrowser
import secrets
import logging
from threading import Timer
from flask import Flask, session, abort, request
from dotenv import load_dotenv
import pytz

# Configuração de Logging inicial
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Configuração do timezone para Brasília
timezone = pytz.timezone('America/Sao_Paulo')
load_dotenv()

def _get_or_create_secret_key():
    """
    Garante que a SECRET_KEY seja persistente entre restarts.
    Se não estiver definida no .env, gera uma nova e salva automaticamente.
    """
    key = os.environ.get('SECRET_KEY')
    if key:
        return key
    
    # Gera uma nova chave forte
    new_key = secrets.token_hex(32)
    
    # Persiste no arquivo .env para os próximos restarts
    env_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '.env')
    try:
        with open(env_path, 'a', encoding='utf-8') as f:
            f.write(f'\nSECRET_KEY={new_key}\n')
        os.environ['SECRET_KEY'] = new_key
        logger.info('SECRET_KEY gerada e salva em .env para persistência de sessão.')
    except Exception as e:
        logger.warning(f'Não foi possível salvar SECRET_KEY no .env: {e}')
    
    return new_key

def create_app():
    if getattr(sys, 'frozen', False):
        # Configuração para quando rodar via executável (PyInstaller)
        template_folder = os.path.join(sys._MEIPASS, 'templates')
        static_folder = os.path.join(sys._MEIPASS, 'static')
        app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
        basedir = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'STMI_Gestao')
        if not os.path.exists(basedir):
            os.makedirs(basedir)
    else:
        app = Flask(__name__)
        basedir = os.path.abspath(os.path.dirname(__file__))

    # Configurações
    app.secret_key = _get_or_create_secret_key()
    
    db_url = os.environ.get('DATABASE_URL')
    if db_url and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url or ('sqlite:///' + os.path.join(basedir, 'database.db'))
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads', 'projects')
    if not os.path.exists(UPLOAD_FOLDER):
        try:
            os.makedirs(UPLOAD_FOLDER)
        except Exception as e:
            logger.warning(f'Não foi possível criar diretório de uploads: {e}')
    
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024
    app.config['BASE_DIR'] = basedir

    # Inicializar Extensões
    from extensions import db
    db.init_app(app)

    # Registrar Blueprints
    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.projects import projects_bp
    from routes.main import main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(main_bp)

    # Contexto Jinja (CSRF e Filtros)
    from utils import format_date_filter, abbreviate_name

    def generate_csrf_token():
        if '_csrf_token' not in session:
            session['_csrf_token'] = secrets.token_hex(32)
        return session['_csrf_token']

    app.jinja_env.globals['csrf_token'] = generate_csrf_token
    app.jinja_env.filters['format_date'] = format_date_filter
    app.jinja_env.filters['abbreviate_name'] = abbreviate_name

    @app.before_request
    def csrf_protect():
        if request.method == "POST":
            # Ignorar rota de update_os_quick (preserva compatibilidade legada)
            if request.endpoint == 'projects.update_os_quick':
                return
                
            token = session.get('_csrf_token', None)
            if not token or token != request.form.get('_csrf_token'):
                logger.warning(f"Tentativa falha de CSRF no endpoint {request.endpoint}")
                abort(403, 'Falha de validação CSRF. Por favor, recarregue a página e tente novamente.')

    # Inicialização do Banco
    from db_setup import init_db
    init_db(app)

    return app

app = create_app()

if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        def open_browser():
            webbrowser.open_new("http://127.0.0.1:5000")
        Timer(1.5, open_browser).start()
        app.run(debug=False)
    else:
        port = int(os.environ.get('PORT', 5000))
        host = os.environ.get('HOST', '127.0.0.1')
        app.run(host=host, port=port, debug=os.environ.get('FLASK_DEBUG', 'True').lower() == 'true')
