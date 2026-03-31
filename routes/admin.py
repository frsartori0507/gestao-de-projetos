import os
import shutil
import requests
import sys
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from werkzeug.security import generate_password_hash

from extensions import db
from models import User, ActivityLog
from utils import admin_required, login_required, get_setting, set_setting, send_backup_to_telegram, log_activity, timezone, SUPER_ROLE

admin_bp = Blueprint('admin', __name__)

import logging
logger = logging.getLogger(__name__)

def get_basedir():
    if getattr(sys, 'frozen', False):
        return os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'STMI_Gestao')
    return current_app.root_path

@admin_bp.route('/users')
@admin_required
def user_management():
    users = User.query.all()
    return render_template('user_management.html', users=users)

@admin_bp.route('/users/add', methods=['POST'])
@admin_required
def add_user():
    try:
        name = request.form.get('name')
        
        if User.query.filter_by(name=name).first():
            flash(f'Erro: O usuário "{name}" já existe.', 'danger')
            return redirect(url_for('admin.user_management'))
            
        role = request.form.get('role')
        
        # BLOQUEIO: Apenas Master pode criar outro Master
        if role == SUPER_ROLE and session.get('role') != SUPER_ROLE:
            flash(f'Erro: Apenas usuários {SUPER_ROLE} podem criar novos usuários com este perfil.', 'danger')
            return redirect(url_for('admin.user_management'))

        password = request.form.get('password')
        hashed_password = generate_password_hash(password) if password else None
        active = 'active' in request.form
        
        new_user = User(name=name, role=role, password=hashed_password, active=active)
        db.session.add(new_user)
        db.session.commit()
        flash('Usuário adicionado com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f'Erro ao adicionar usuário: {e}')
        
    return redirect(url_for('admin.user_management'))


@admin_bp.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        try:
            new_role = request.form.get('role')
            
            # BLOQUEIO: Apenas Master pode promover alguém a Master ou editar um Master
            current_user_role = session.get('role')
            if (new_role == SUPER_ROLE or user.role == SUPER_ROLE) and current_user_role != SUPER_ROLE:
                flash(f'Erro: Apenas usuários {SUPER_ROLE} podem gerenciar perfis deste nível.', 'danger')
                return redirect(url_for('admin.user_management'))

            user.name = request.form.get('name')
            user.role = new_role
            if request.form.get('password'):
                user.password = generate_password_hash(request.form.get('password'))
            user.active = 'active' in request.form
            db.session.commit()
            flash('Usuário atualizado com sucesso!', 'success')
            return redirect(url_for('admin.user_management'))
        except Exception as e:
            db.session.rollback()
            logger.error(f'Erro ao atualizar usuário: {e}')
            
    return render_template('user_edit.html', user=user)

@admin_bp.route('/users/delete/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    try:
        user = User.query.get_or_404(user_id)
        
        # BLOQUEIO: Apenas Master pode deletar outro Master
        if user.role == SUPER_ROLE and session.get('role') != SUPER_ROLE:
            flash(f'Erro: Apenas usuários {SUPER_ROLE} podem remover perfis deste nível.', 'danger')
            return redirect(url_for('admin.user_management'))

        db.session.delete(user)
        db.session.commit()
        flash('Usuário removido com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f'Erro ao deletar usuário: {e}')
    return redirect(url_for('admin.user_management'))

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user = User.query.filter_by(name=session['user']).first()
    
    if request.method == 'POST':
        # Senha
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if new_password and new_password == confirm_password:
            user.password = generate_password_hash(new_password)
            db.session.commit()
            flash('Senha atualizada com sucesso!', 'success')
        elif new_password and new_password != confirm_password:
            flash('Erro: As senhas não conferem.', 'danger')

        # Telegram Settings (Apenas Master)
        if session.get('role') == SUPER_ROLE:
            telegram_token = request.form.get('telegram_token')
            telegram_chat_id = request.form.get('telegram_chat_id')
            
            if telegram_token is not None:
                set_setting('telegram_token', telegram_token)
            if telegram_chat_id is not None:
                set_setting('telegram_chat_id', telegram_chat_id)
            
            # Tenta enviar uma mensagem de teste
            if telegram_token and telegram_chat_id:
                test_msg = "✅ <b>Configuração de Notificação Ativada!</b>\n\nEste é um teste para confirmar que o sistema STMI agora pode enviar mensagens para este chat."
                
                # Para o teste, queremos ver o erro se falhar
                token_clean = telegram_token.strip()
                if 'api:' in token_clean: token_clean = token_clean.split('api:')[-1].strip()
                if 't.me/' in token_clean: token_clean = token_clean.split('/')[-1].strip()
                
                url = f"https://api.telegram.org/bot{token_clean}/sendMessage"
                try:
                    resp = requests.post(url, json={"chat_id": telegram_chat_id, "text": test_msg, "parse_mode": "HTML"}, timeout=5)
                    if resp.status_code == 200:
                        flash('Configurações salvas e mensagem de teste enviada com sucesso!', 'success')
                    else:
                        error_detail = resp.json().get('description', 'Erro desconhecido')
                        flash(f'Erro no Telegram: {error_detail}. Verifique se o Bot existe e se você já enviou /start para ele.', 'danger')
                except Exception as e:
                    flash(f'Erro de conexão: {str(e)}', 'danger')
            else:
                flash('Configurações de notificação atualizadas!', 'success')
            
        return redirect(url_for('admin.settings'))
        
    tel_token = get_setting('telegram_token', '')
    tel_chat_id = get_setting('telegram_chat_id', '')
    
    # Info do último backup
    last_cloud_backup = get_setting('last_cloud_backup_date', '')
    backup_dir = os.path.join(get_basedir(), 'backups')
    last_local_backup = None
    backup_count = 0
    if os.path.exists(backup_dir):
        backups = sorted([f for f in os.listdir(backup_dir) if f.startswith('database_backup_')], reverse=True)
        backup_count = len(backups)
        if backups:
            try:
                ts_str = backups[0].replace('database_backup_', '').replace('.db', '')
                backup_dt = datetime.strptime(ts_str, '%Y-%m-%d_%H-%M-%S')
                last_local_backup = backup_dt.strftime('%d/%m/%Y às %H:%M:%S')
            except (ValueError, IndexError):
                last_local_backup = backups[0]
        
    return render_template('settings.html', user=user, tel_token=tel_token, tel_chat_id=tel_chat_id,
                           last_cloud_backup=last_cloud_backup, last_local_backup=last_local_backup,
                           backup_count=backup_count)

@admin_bp.route('/backup-now', methods=['POST'])
@admin_required
def backup_now():
    try:
        db_path = os.path.join(get_basedir(), 'database.db')
        if not os.path.exists(db_path):
            flash('Erro: Banco de dados não encontrado.', 'danger')
            return redirect(url_for('admin.settings'))
        
        backup_dir = os.path.join(get_basedir(), 'backups')
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        timestamp = datetime.now(timezone).strftime('%Y-%m-%d_%H-%M-%S')
        backup_filename = f'database_backup_{timestamp}.db'
        backup_path = os.path.join(backup_dir, backup_filename)
        
        shutil.copy2(db_path, backup_path)
        
        # Envia para Telegram se solicitado
        send_to_telegram = request.form.get('send_telegram') == '1'
        if send_to_telegram:
            today_str = datetime.now(timezone).strftime('%Y-%m-%d')
            
            # Tentativa de envio SÍNCRONO para dar feedback real ao usuário
            if send_backup_to_telegram(backup_path):
                set_setting('last_cloud_backup_date', today_str)
                flash('✅ Backup criado e enviado para o Telegram com sucesso!', 'success')
            else:
                flash('⚠️ Backup local criado, mas FALHOU ao enviar para o Telegram. Verifique se o Token e Chat ID estão corretos em Configurações.', 'warning')
        else:
            flash('✅ Backup local criado com sucesso!', 'success')
        
        log_activity('Realizou backup manual do banco de dados')
        
        # Limpeza de backups antigos (mantém últimos 20)
        backups = sorted([os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.startswith('database_backup_')])
        if len(backups) > 20:
            for old_backup in backups[:-20]:
                try:
                    os.remove(old_backup)
                except OSError:
                    pass
                    
    except Exception as e:
        logger.error(f'Erro ao criar backup manual: {e}')
        flash(f'Erro ao criar backup: {str(e)}', 'danger')
    
    return redirect(url_for('admin.settings'))


@admin_bp.route('/activity_log')
@login_required
def activity_log_view():
    page = request.args.get('page', 1, type=int)
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).paginate(page=page, per_page=50)
    return render_template('activity_log.html', logs=logs)
