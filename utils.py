import os
import time
from datetime import datetime
from threading import Thread
import requests
from flask import session, redirect, url_for, flash, current_app
from functools import wraps
from werkzeug.utils import secure_filename
from PIL import Image
import pytz
import logging

from extensions import db
from models import ActivityLog, SystemSetting

timezone = pytz.timezone('America/Sao_Paulo')
logger = logging.getLogger(__name__)

def abbreviate_name(name):
    if not name:
        return ""
    parts = name.strip().split()
    if len(parts) == 0:
        return ""
    return parts[0]

def format_date_filter(date_str):
    if not date_str:
        return ""
    try:
        # Tenta converter de YYYY-MM-DD para DD/MM/YYYY
        if '-' in date_str:
            parts = date_str.split('-')
            if len(parts) == 3:
                return f"{parts[2]}/{parts[1]}/{parts[0]}"
        return date_str
    except:
        return date_str


MAX_IMAGE_SIZE = 4 * 1024 * 1024  # 4MB

# === Constantes de Permissão ===
EDIT_ROLES = ['Master', 'Administrador', 'Técnico de Projetos', 'Técnico', 'Responsável Técnico']
FULL_EDIT_ROLES = ['Master'] # Administrador removido daqui
SUPER_ROLE = 'Master'

def log_activity(action, project_id=None):
    """Registra uma atividade no sistema."""
    user = session.get('user', 'Sistema')
    log = ActivityLog(user_name=user, action=action, project_id=project_id)
    db.session.add(log)
    # Commit opcional aqui, mas geralmente delegamos ao fluxo principal
    return log

def get_setting(key, default=None):
    try:
        setting = SystemSetting.query.filter_by(key=key).first()
        return setting.value if setting else default
    except:
        return default

def set_setting(key, value):
    try:
        setting = SystemSetting.query.filter_by(key=key).first()
        if not setting:
            setting = SystemSetting(key=key, value=value)
            db.session.add(setting)
        else:
            setting.value = value
        db.session.commit()
    except Exception as e:
        logger.error(f'Erro ao salvar configuração {key}: {e}')
        db.session.rollback()

def save_and_resize_image(file, project_id, photo_index):
    """Salva e redimensiona a imagem para otimizar espaço com validações extras."""
    if not file or file.filename == '':
        return None
    
    # Validação de tamanho (Item 6)
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    if file_size > MAX_IMAGE_SIZE:
        logger.warning(f'Imagem rejeitada: tamanho {file_size} bytes excede limite de {MAX_IMAGE_SIZE} bytes')
        return None

    # Nome único com timestamp para evitar cache e colisões (Item 6)
    timestamp = int(time.time())
    ext = "webp" # Mudamos para WebP por ser mais leve e moderno
    filename = secure_filename(f"proj_{project_id}_idx{photo_index}_{timestamp}.{ext}")
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    
    try:
        if not os.path.exists(current_app.config['UPLOAD_FOLDER']):
            os.makedirs(current_app.config['UPLOAD_FOLDER'])

        img = Image.open(file)
        # Converte para RGB se necessário
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
        # Redimensiona mantendo proporção (Máximo 800px para garantir < 100kb com boa visibilidade)
        img.thumbnail((800, 800), Image.Resampling.LANCZOS)
        
        # Salva em WebP com compressão progressiva para atingir < 100kb
        quality = 70
        img.save(filepath, "WEBP", quality=quality, method=6)
        
        # Se ainda for maior que 100kb, reduzimos a qualidade iterativamente
        # mas mantemos um limite mínimo para garantir visibilidade
        while os.path.getsize(filepath) > 100 * 1024 and quality > 20:
            quality -= 10
            img.save(filepath, "WEBP", quality=quality, method=6)
            
        return filename
    except Exception as e:
        logger.error(f'Erro ao processar imagem: {e}')
        return None

def send_telegram_notification(message, token=None, chat_id=None):
    if not token:
        token = get_setting('telegram_token') or os.environ.get('TELEGRAM_TOKEN')
    if not chat_id:
        chat_id = get_setting('telegram_chat_id') or os.environ.get('TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        return False
    
    # Limpeza do token
    token = token.strip()
    if 'api:' in token: token = token.split('api:')[-1].strip()
    if 't.me/' in token: token = token.split('/')[-1].strip()
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    # Configuração de proxy para PythonAnywhere (Contas Gratuitas)
    proxies = None
    if 'http_proxy' in os.environ or 'HTTP_PROXY' in os.environ:
        proxy_url = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
        proxies = {
            "http": proxy_url,
            "https": proxy_url,
        }
    elif 'PYTHONANYWHERE_DOMAIN' in os.environ:
        proxies = {
            "http": "http://proxy.server:3128",
            "https": "http://proxy.server:3128",
        }
    
    try:
        response = requests.post(url, json=payload, timeout=10, proxies=proxies)
        if response.status_code == 200:
            return True
        else:
            return False
    except Exception as e:
        return False

def send_telegram_notification_async(message):
    """Envia a notificação em uma thread separada para não travar o app."""
    # Capturamos as configurações ANTES de iniciar a thread para evitar perda de contexto do Flask
    token = get_setting('telegram_token') or os.environ.get('TELEGRAM_TOKEN')
    chat_id = get_setting('telegram_chat_id') or os.environ.get('TELEGRAM_CHAT_ID')
    Thread(target=send_telegram_notification, args=(message, token, chat_id), daemon=True).start()

def send_backup_to_telegram(file_path, token=None, chat_id=None):
    """Envia o arquivo de backup para o Telegram."""
    if not token:
        token = get_setting('telegram_token') or os.environ.get('TELEGRAM_TOKEN')
    if not chat_id:
        chat_id = get_setting('telegram_chat_id') or os.environ.get('TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        return False
    
    token = token.strip()
    if 'api:' in token: token = token.split('api:')[-1].strip()
    
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    
    proxies = None
    if 'http_proxy' in os.environ or 'HTTP_PROXY' in os.environ:
        proxy_url = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
        proxies = {"http": proxy_url, "https": proxy_url}
    
    try:
        with open(file_path, 'rb') as f:
            files = {'document': f}
            payload = {
                'chat_id': chat_id,
                'caption': f"📦 <b>Backup Semanal Automático</b>\n📅 Data: {datetime.now(timezone).strftime('%d/%m/%Y %H:%M')}\nSistema STMI" ,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, data=payload, files=files, timeout=30, proxies=proxies)
            return response.status_code == 200
    except Exception as e:
        logger.error(f'Erro ao enviar backup para Telegram: {e}')
        return False

# Decorator para verificar login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

# Decorator para Administradores (Restrito ao Master por solicitação do usuário)
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('auth.login'))
        if session.get('role') != SUPER_ROLE:
            flash('Acesso negado: Apenas o usuário MASTER tem permissão para acessar esta página.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# Decorator para múltiplos cargos
def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                return redirect(url_for('auth.login'))
            if session.get('role') not in roles:
                flash('Acesso negado: Você não tem permissão para esta ação.', 'danger')
                return redirect(url_for('main.dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
