import os
import logging
import shutil
from datetime import datetime
from sqlalchemy import text
from flask import current_app
from threading import Thread
from werkzeug.security import generate_password_hash

from extensions import db
from models import User, Project, Agenda, SystemSetting, ActivityLog
from utils import timezone, get_setting, set_setting, send_backup_to_telegram

logger = logging.getLogger(__name__)

def backup_db(app):
    basedir = app.config.get('BASE_DIR')
    db_path = os.path.join(basedir, 'database.db')
    if os.path.exists(db_path):
        backup_dir = os.path.join(basedir, 'backups')
        if not os.path.exists(backup_dir):
            try:
                os.makedirs(backup_dir)
            except OSError as e:
                logger.error(f'Erro ao criar diretório de backup: {e}')
                return

        timestamp = datetime.now(timezone).strftime('%Y-%m-%d_%H-%M-%S')
        backup_filename = f'database_backup_{timestamp}.db'
        backup_path = os.path.join(backup_dir, backup_filename)
        
        try:
            shutil.copy2(db_path, backup_path)
            
            # Cloud Backup Weekly (Telegram)
            with app.app_context():
                last_cloud_backup = get_setting('last_cloud_backup_date')
                today_str = datetime.now(timezone).strftime('%Y-%m-%d')
                
                should_send_cloud = False
                if not last_cloud_backup:
                    should_send_cloud = True
                else:
                    try:
                        last_date = datetime.strptime(last_cloud_backup, '%Y-%m-%d')
                        if (datetime.now(timezone).date() - last_date.date()).days >= 7:
                            should_send_cloud = True
                    except:
                        should_send_cloud = True
                
                if should_send_cloud:
                    token = get_setting('telegram_token') or os.environ.get('TELEGRAM_TOKEN')
                    chat_id = get_setting('telegram_chat_id') or os.environ.get('TELEGRAM_CHAT_ID')
                    
                    if token and chat_id:
                        def cloud_backup_task(t, c, current_app_obj, path, date_str):
                            with current_app_obj.app_context():
                                if send_backup_to_telegram(path, token=t, chat_id=c):
                                    set_setting('last_cloud_backup_date', date_str)
                                    logger.info("Backup semanal enviado com sucesso para o Telegram.")
                        
                        # Use the actual app object for the thread
                        Thread(target=cloud_backup_task, args=(token, chat_id, app, backup_path, today_str), daemon=True).start()
                    else:
                        logger.warning("Token ou ChatID do Telegram não configurados para backup automático.")

            # Clean up old backups (keep last 20 files)
            backups = sorted([os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.startswith('database_backup_')])
            if len(backups) > 20:
                for old_backup in backups[:-20]:
                    try:
                        os.remove(old_backup)
                    except OSError:
                        pass
                        
        except Exception as e:
            logger.error(f'Erro ao criar backup do banco: {e}')

def init_db(app):
    with app.app_context():
        db.create_all()
        
        # Realiza o backup (semanal) ao iniciar o sistema
        try:
            backup_db(app)
        except Exception as e:
            logger.error(f"Erro ao disparar backup no startup: {e}")

        # === Migração Automática ===
        migration_columns = [
            ('observations', 'TEXT'),
            ('completion_date', 'VARCHAR(20)'),
            ('has_horizontal', 'BOOLEAN DEFAULT 1'),
            ('has_vertical', 'BOOLEAN DEFAULT 1'),
            ('has_devices', 'BOOLEAN DEFAULT 1'),
            ('has_semaforico', 'BOOLEAN DEFAULT 0'),
            ('h_progress', 'INTEGER DEFAULT 0'),
            ('v_progress', 'INTEGER DEFAULT 0'),
            ('d_progress', 'INTEGER DEFAULT 0'),
            ('s_progress', 'INTEGER DEFAULT 0'),
            ('doc_type', 'VARCHAR(50)'),
            ('doc_number', 'VARCHAR(50)'),
            ('doc_year', 'VARCHAR(10)'),
            ('address_number', 'VARCHAR(20)'),
            ('neighborhood', 'VARCHAR(100)'),
            ('h_start_date', 'VARCHAR(20)'),
            ('h_end_date', 'VARCHAR(20)'),
            ('h_responsible', 'VARCHAR(100)'),
            ('v_start_date', 'VARCHAR(20)'),
            ('v_end_date', 'VARCHAR(20)'),
            ('v_responsible', 'VARCHAR(100)'),
            ('d_start_date', 'VARCHAR(20)'),
            ('d_end_date', 'VARCHAR(20)'),
            ('d_responsible', 'VARCHAR(100)'),
            ('s_start_date', 'VARCHAR(20)'),
            ('s_end_date', 'VARCHAR(20)'),
            ('s_responsible', 'VARCHAR(100)'),
            ('tech_responsible', 'VARCHAR(100)'),
            ('photo1', 'VARCHAR(255)'),
            ('photo2', 'VARCHAR(255)'),
            ('photo3', 'VARCHAR(255)'),
            ('is_printed', 'BOOLEAN DEFAULT 0'),
        ]
        
        for col_name, col_type in migration_columns:
            try:
                with db.engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE project ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
            except Exception:
                pass 
        
        # Migração de dados e unificação de usuários (mesma lógica do app.py)
        try:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    UPDATE project 
                    SET completion_date = COALESCE(
                        CASE 
                            WHEN h_end_date > COALESCE(v_end_date, '') AND h_end_date > COALESCE(d_end_date, '') THEN h_end_date
                            WHEN v_end_date > COALESCE(d_end_date, '') THEN v_end_date
                            ELSE COALESCE(d_end_date, date) 
                        END, 
                        date
                    ) WHERE (status = 'Concluído' OR status = 'Finalizado') AND (completion_date IS NULL OR completion_date = '')
                """))
                conn.execute(text("""UPDATE project SET date = substr(date, 7, 4) || '-' || substr(date, 4, 2) || '-' || substr(date, 1, 2) WHERE date LIKE '__/__/____'"""))
                conn.commit()
        except Exception as e:
            logger.warning(f'Erro na migração de datas: {e}')
        
        try:
            with db.engine.connect() as conn:
                conn.execute(text("""UPDATE project SET h_progress = progress WHERE (h_progress = 0 OR h_progress IS NULL) AND progress > 0"""))
                conn.commit()
        except Exception: pass

        try:
            with db.engine.connect() as conn:
                text_fields = ['osNumber', 'address', 'neighborhood', 'address_number', 'designer', 'projectNumber', 'doc_number', 'doc_type', 'observations']
                for field in text_fields:
                    conn.execute(text(f"UPDATE project SET {field} = '' WHERE {field} IS NULL OR UPPER({field}) = 'NONE' OR {field} = 'None'"))
                conn.commit()
        except Exception: pass

        try:
            with db.engine.connect() as conn:
                result = conn.execute(text("SELECT name, role, active FROM team_member"))
                for row in result:
                    name, role, active = row
                    exists = db.session.execute(text("SELECT id FROM user WHERE name = :name"), {"name": name}).fetchone()
                    if not exists:
                        db.session.execute(
                            text("INSERT INTO user (name, role, active) VALUES (:name, :role, :active)"),
                            {"name": name, "role": role or "Técnico", "active": active}
                        )
                db.session.commit()
        except Exception: pass

        if User.query.count() == 0:
            admin_password = os.environ.get('DEFAULT_ADMIN_PASSWORD', 'admin')
            admin_user = User(
                name='admin', 
                role='Master', 
                active=True, 
                password=generate_password_hash(admin_password)
            )
            db.session.add(admin_user)
            db.session.commit()

        # Garantir que o usuário principal seja Master
        fabio_user = User.query.filter_by(name='FABIO ROGERIO SARTORI').first()
        if fabio_user and fabio_user.role != 'Master':
            fabio_user.role = 'Master'
            db.session.commit()
            logger.info("Usuário FABIO ROGERIO SARTORI promovido a Master.")
