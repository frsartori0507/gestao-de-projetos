from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
from extensions import db
from models import User

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/')
def login():
    if 'user' in session:
        return redirect(url_for('main.dashboard'))
    return render_template('login.html')

@auth_bp.route('/login', methods=['POST'])
def do_login():
    username_input = request.form.get('username', '').strip()
    password = request.form.get('password')
    
    if not username_input:
        flash('Por favor, informe o nome.', 'warning')
        return redirect(url_for('auth.login'))

    # Busca todos os usuários que coincidem com o primeiro nome ou nome completo
    potential_users = User.query.filter(
        db.or_(
            User.name.ilike(username_input),
            User.name.ilike(f"{username_input} %")
        )
    ).all()
    
    authenticated_user = None
    
    for user in potential_users:
        # Só permite login se usuário estiver ativo E possuir uma senha cadastrada
        if not user.active or not user.password:
            continue
            
        # Verifica a senha usando hash seguro (bcrypt/scrypt via werkzeug)
        if check_password_hash(user.password, password):
            authenticated_user = user
            break
            
    if authenticated_user:
        session['user'] = authenticated_user.name
        session['role'] = authenticated_user.role
        return redirect(url_for('main.dashboard'))
    
    # Mensagem de erro genérica para segurança
    flash('Usuário ou senha incorreta ou sem permissão de acesso.', 'danger')
    return redirect(url_for('auth.login'))

@auth_bp.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('auth.login'))
