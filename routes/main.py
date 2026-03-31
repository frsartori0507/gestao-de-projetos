import os
import hashlib
import time
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, current_app

from extensions import db
from models import Project, Agenda, ActivityLog
from utils import login_required, timezone

import logging
logger = logging.getLogger(__name__)

main_bp = Blueprint('main', __name__)

@main_bp.route('/dashboard')
@login_required
def dashboard():
    today_dt = datetime.now(timezone)
    today_str = today_dt.strftime('%Y-%m-%d')
    seven_days_later = (today_dt + timedelta(days=7)).strftime('%Y-%m-%d')
    
    # 1. Estatísticas Gerais
    stats = {
        'total': Project.query.count(),
        'urgent': Project.query.filter_by(status='Urgente').count(),
        'in_progress': Project.query.filter_by(status='Em Andamento').count(),
        'waiting': Project.query.filter_by(status='Em Espera').count(),
        'completed': Project.query.filter_by(status='Concluído').count(),
        'finalized': Project.query.filter_by(status='Finalizado').count(),
        'developing': Project.query.filter_by(status='Em Desenvolvimento').count()
    }
    
    # 2. Projetos do Usuário Logado
    user_name = session.get('user', '')
    user_projects_count = Project.query.filter(
        db.or_(
            Project.designer == user_name,
            Project.h_responsible == user_name,
            Project.v_responsible == user_name,
            Project.d_responsible == user_name,
            Project.s_responsible == user_name
        )
    ).count()

    # 3. Alertas de Atraso ou Vencimento
    upcoming_deadlines = Project.query.filter(
        Project.status.in_(['Em Andamento', 'Urgente']),
        db.or_(
            db.and_(Project.h_end_date.isnot(None), Project.h_end_date != '', Project.h_end_date <= seven_days_later, Project.h_end_date >= today_str),
            db.and_(Project.v_end_date.isnot(None), Project.v_end_date != '', Project.v_end_date <= seven_days_later, Project.v_end_date >= today_str),
            db.and_(Project.d_end_date.isnot(None), Project.d_end_date != '', Project.d_end_date <= seven_days_later, Project.d_end_date >= today_str),
            db.and_(Project.s_end_date.isnot(None), Project.s_end_date != '', Project.s_end_date <= seven_days_later, Project.s_end_date >= today_str)
        )
    ).limit(5).all()

    # 4. Atividades Recentes
    recent_activities = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(5).all()
    
    # 5. Agenda do Dia
    todays_agenda = Agenda.query.filter_by(date=today_str).all()
    
    return render_template('dashboard.html', 
                           stats=stats,
                           total_projects=stats['total'],
                           urgent_count=stats['urgent'],
                           in_progress_count=stats['in_progress'],
                           waiting_count=stats['waiting'],
                           completed_count=stats['completed'],
                           finalized_count=stats['finalized'],
                           developing_count=stats['developing'],
                           user_projects_count=user_projects_count,
                           upcoming_deadlines=upcoming_deadlines,
                           recent_activities=recent_activities,
                           todays_agenda=todays_agenda,
                           user_name=user_name)

@main_bp.route('/agenda')
@login_required
def agenda():
    thirty_days_ago = (datetime.now(timezone) - timedelta(days=30)).strftime('%Y-%m-%d')
    events = Agenda.query.filter(Agenda.date >= thirty_days_ago).all()
    
    agenda_items = []
    for e in events:
        agenda_items.append({
            'id': e.id,
            'type': 'agenda',
            'date': e.date,
            'time': e.time,
            'title': e.title,
            'subtitle': e.category,
            'status': 'Agendado',
            'icon': 'event'
        })
        
    agenda_items.sort(key=lambda x: (x['date'], x['time'] or ''))
    
    return render_template('agenda.html', agenda_items=agenda_items)

@main_bp.route('/agenda/add', methods=['POST'])
@login_required
def add_agenda():
    title = request.form.get('title')
    date = request.form.get('date')
    time = request.form.get('time')
    category = request.form.get('category')
    
    if title and date:
        new_entry = Agenda(title=title, date=date, time=time, category=category)
        db.session.add(new_entry)
        db.session.commit()
        
    return redirect(url_for('main.agenda'))

@main_bp.route('/agenda/delete/<int:id>', methods=['POST'])
@login_required
def delete_agenda(id):
    try:
        entry = Agenda.query.get_or_404(id)
        db.session.delete(entry)
        db.session.commit()
    except Exception as e:
        logger.error(f'Erro ao deletar evento: {e}')
    return redirect(url_for('main.agenda'))

@main_bp.route('/report')
@login_required
def report():
    selected_month = request.args.get('month')
    selected_statuses = request.args.getlist('status')
    search_query = request.args.get('search', '').strip()
    
    query = Project.query
    
    if selected_month:
        query = query.filter(Project.date.like(f"{selected_month}%"))
        
    if search_query:
        query = query.filter(
            db.or_(
                Project.address.ilike(f"%{search_query}%"),
                Project.designer.ilike(f"%{search_query}%"),
                Project.projectNumber.like(f"%{search_query}%"),
                Project.osNumber.like(f"%{search_query}%")
            )
        )
        
    projects = query.all()

    stats_projects_by_status = {
        'Urgente': [p for p in projects if p.status == 'Urgente'],
        'Em Andamento': [p for p in projects if p.status == 'Em Andamento'],
        'Em Espera': [p for p in projects if p.status == 'Em Espera'],
        'Concluído': [p for p in projects if p.status == 'Concluído'],
        'Finalizado': [p for p in projects if p.status == 'Finalizado'],
        'Em Desenvolvimento': [p for p in projects if p.status == 'Em Desenvolvimento']
    }

    if selected_statuses:
        filtered_projects = [p for p in projects if p.status in selected_statuses]
    else:
        filtered_projects = projects

    projects_by_status = {
        'Urgente': [p for p in filtered_projects if p.status == 'Urgente'],
        'Em Andamento': [p for p in filtered_projects if p.status == 'Em Andamento'],
        'Em Espera': [p for p in filtered_projects if p.status == 'Em Espera'],
        'Concluído': [p for p in filtered_projects if p.status == 'Concluído'],
        'Finalizado': [p for p in filtered_projects if p.status == 'Finalizado'],
        'Em Desenvolvimento': [p for p in filtered_projects if p.status == 'Em Desenvolvimento']
    }
    
    active_statuses = [s for s in ['Urgente', 'Em Andamento', 'Em Desenvolvimento', 'Em Espera', 'Concluído', 'Finalizado'] if projects_by_status[s]]
    
    total = len(projects)
    concluded = len(stats_projects_by_status['Concluído'])
    finalized = len(stats_projects_by_status['Finalizado'])
    in_progress = len(stats_projects_by_status['Em Andamento'])
    urgent = len(stats_projects_by_status['Urgente'])
    waiting = len(stats_projects_by_status['Em Espera'])

    report_id = hashlib.md5(f"{session.get('user')}{time.time()}".encode()).hexdigest()[:8].upper()

    months_br = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", 
                 "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    month_name = None
    if selected_month:
        try:
            parts = selected_month.split('-')
            if len(parts) >= 2:
                month_idx = int(parts[1]) - 1
                if 0 <= month_idx < 12:
                    month_name = f"{months_br[month_idx]} de {parts[0]}"
                else:
                    month_name = selected_month
            else:
                month_name = selected_month
        except (IndexError, ValueError):
            month_name = selected_month

    return render_template('report.html', 
                           projects_by_status=projects_by_status,
                           active_statuses=active_statuses,
                           user_name=session.get('user', 'Administrador'),
                           stats={
                               'total': total, 
                               'concluded': concluded, 
                               'finalized': finalized,
                               'in_progress': in_progress, 
                               'urgent': urgent,
                               'waiting': waiting,
                               'developing': len(stats_projects_by_status['Em Desenvolvimento'])
                           },
                           generation_date=datetime.now(timezone),
                           selected_month=selected_month,
                           selected_statuses=selected_statuses,
                           search_query=search_query,
                           month_name=month_name,
                           report_id=report_id)
