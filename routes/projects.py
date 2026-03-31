import os
import io
import csv
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app, jsonify

from extensions import db
from models import Project, User
from utils import (login_required, roles_required, EDIT_ROLES, FULL_EDIT_ROLES, SUPER_ROLE,
                   save_and_resize_image, log_activity, send_telegram_notification_async, timezone)

import logging
logger = logging.getLogger(__name__)

projects_bp = Blueprint('projects', __name__)

@projects_bp.route('/projects')
@login_required
def project_list():
    # Parâmetros de Filtro
    search_query = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '').strip()
    responsible_filter = request.args.get('responsible', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    sort_by = request.args.get('sort', 'date_desc')
    show_all = request.args.get('show_all')
    page = request.args.get('page', 1, type=int)

    query = Project.query

    # Filtro de Busca Textual
    if search_query:
        query = query.filter(
            db.or_(
                Project.address.ilike(f"%{search_query}%"),
                Project.designer.ilike(f"%{search_query}%"),
                Project.status.ilike(f"%{search_query}%"),
                Project.projectNumber.like(f"%{search_query}%"),
                Project.osNumber.like(f"%{search_query}%")
            )
        )

    # Filtro por Status
    if status_filter:
        query = query.filter(Project.status == status_filter)

    # Filtro por Responsável
    if responsible_filter:
        query = query.filter(
            db.or_(
                Project.designer == responsible_filter,
                Project.h_responsible == responsible_filter,
                Project.v_responsible == responsible_filter,
                Project.d_responsible == responsible_filter,
                Project.s_responsible == responsible_filter
            )
        )

    # Filtro por Datas
    if start_date:
        query = query.filter(Project.date >= start_date)
    if end_date:
        query = query.filter(Project.date <= end_date)

    # Lógica de Visibilidade Padrão (se não houver filtros ativos e não for 'show_all')
    is_filtering = any([search_query, status_filter, responsible_filter, start_date, end_date])
    
    if not show_all and not is_filtering:
        # Padrão: Urgente, Em Andamento ou Concluído nos últimos 30 dias
        thirty_days_ago = (datetime.now(timezone) - timedelta(days=30)).strftime('%Y-%m-%d')
        query = query.filter(
            db.or_(
                Project.status.in_(['Em Andamento', 'Urgente', 'Em Desenvolvimento']),
                Project.date >= thirty_days_ago
            )
        )

    # Ordenação
    if sort_by == 'date_asc':
        query = query.order_by(Project.date.asc(), Project.id.asc())
    elif sort_by == 'prog_desc':
        query = query.order_by(Project.progress.desc())
    elif sort_by == 'prog_asc':
        query = query.order_by(Project.progress.asc())
    else: # date_desc
        query = query.order_by(Project.date.desc(), Project.id.desc())

    # Paginador (15 itens por página, a menos que seja show_all)
    if not show_all:
        pagination = query.paginate(page=page, per_page=15, error_out=False)
        projects = pagination.items
    else:
        pagination = None
        projects = query.all()

    can_edit = session.get('role') in EDIT_ROLES
    team_members = User.query.filter_by(active=True).order_by(User.name).all()
    
    return render_template('project_list.html', 
                           projects=projects, 
                           search_query=search_query, 
                           status_filter=status_filter,
                           responsible_filter=responsible_filter,
                           start_date=start_date,
                           end_date=end_date,
                           sort_by=sort_by,
                           show_all=show_all,
                           pagination=pagination,
                           can_edit=can_edit,
                           team_members=team_members)

@projects_bp.route('/projects/export-csv')
@login_required
def export_csv():
    """Exporta os projetos filtrados para CSV, respeitando filtros ativos."""
    search_query = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '').strip()
    responsible_filter = request.args.get('responsible', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    query = Project.query

    if search_query:
        query = query.filter(
            db.or_(
                Project.address.ilike(f"%{search_query}%"),
                Project.designer.ilike(f"%{search_query}%"),
                Project.status.ilike(f"%{search_query}%"),
                Project.projectNumber.like(f"%{search_query}%"),
                Project.osNumber.like(f"%{search_query}%")
            )
        )
    if status_filter:
        query = query.filter(Project.status == status_filter)
    if responsible_filter:
        query = query.filter(
            db.or_(
                Project.designer == responsible_filter,
                Project.h_responsible == responsible_filter,
                Project.v_responsible == responsible_filter,
                Project.d_responsible == responsible_filter,
                Project.s_responsible == responsible_filter
            )
        )
    if start_date:
        query = query.filter(Project.date >= start_date)
    if end_date:
        query = query.filter(Project.date <= end_date)

    projects = query.order_by(Project.date.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    
    # Cabeçalho
    writer.writerow([
        'Projeto', 'OS', 'Endereço', 'Nº', 'Bairro', 'Status', 'Progresso %',
        'Projetista', 'Data Registro', 'Data OS',
        'H. Início', 'H. Fim', 'H. Responsável', 'H. Progresso',
        'V. Início', 'V. Fim', 'V. Responsável', 'V. Progresso',
        'D. Início', 'D. Fim', 'D. Responsável', 'D. Progresso',
        'S. Início', 'S. Fim', 'S. Responsável', 'S. Progresso',
        'Observações', 'Data Conclusão'
    ])
    
    for p in projects:
        writer.writerow([
            p.projectNumber or '', p.osNumber or '', p.address or '',
            p.address_number or '', p.neighborhood or '', p.status or '', p.progress or 0,
            p.designer or '', p.date or '', p.osDate or '',
            p.h_start_date or '', p.h_end_date or '', p.h_responsible or '', p.h_progress or 0,
            p.v_start_date or '', p.v_end_date or '', p.v_responsible or '', p.v_progress or 0,
            p.d_start_date or '', p.d_end_date or '', p.d_responsible or '', p.d_progress or 0,
            p.s_start_date or '', p.s_end_date or '', p.s_responsible or '', p.s_progress or 0,
            p.observations or '', p.completion_date or ''
        ])
    
    output.seek(0)
    # BOM para Excel reconhecer UTF-8 corretamente
    bom = '\ufeff'
    timestamp = datetime.now(timezone).strftime('%Y-%m-%d')
    
    from flask import Response
    return Response(
        bom + output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename=projetos_stmi_{timestamp}.csv'}
    )



@projects_bp.route('/project/<int:project_id>', methods=['GET', 'POST'])
@projects_bp.route('/project/new', methods=['GET', 'POST'])
@login_required
def project_form(project_id=None):
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    
    project = None
    if project_id:
        project = Project.query.get_or_404(project_id)
        
    # Check permissions
    # Regra: Se o projeto está "Finalizado", apenas usuários Master podem editar.
    # O user Master tem permissão total e ignora restrições.
    user_role = session.get('role')
    is_master = user_role == SUPER_ROLE
    is_finalized = project and project.status == 'Finalizado'
    
    if is_finalized and not is_master:
        can_edit = False
    else:
        # Permissões normais para projetos não finalizados
        can_edit = user_role in FULL_EDIT_ROLES
        
    # Get active team members (from User table) for autocomplete
    team_members = User.query.filter_by(active=True).order_by(User.name).all()
    today = datetime.now(timezone).strftime('%Y-%m-%d')
    
    # Lógica para sugerir número se for novo
    suggested_number = ""
    if not project:
        year = datetime.now(timezone).year
        pattern = f"%/{year}"
        last_p = Project.query.filter(Project.projectNumber.like(pattern)).order_by(Project.id.desc()).first()
        if last_p:
            try:
                num = int(last_p.projectNumber.split('/')[0])
                suggested_number = f"{num + 1}/{year}"
            except: suggested_number = f"1/{year}"
        else: suggested_number = f"1/{year}"

    if request.method == 'POST':
        if not can_edit:
            return render_template('project_form.html', project=project, can_edit=can_edit, error="Você não tem permissão para editar projetos.", team_members=team_members)
            
        try:
            if not project:
                project = Project()
                project.date = today # Data de registro automática para novo serviço
                db.session.add(project)
                db.session.flush() # Gera o ID para as fotos
            
            manual_id = request.form.get('project_id_manual')
            if manual_id:
                project.projectNumber = manual_id
            elif not project.projectNumber:
                project.projectNumber = suggested_number
            
            def get_safe_int(val):
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return 0
            
            old_status = project.status if project and project.id else None
            form_status = request.form.get('status', 'Em Andamento')
            
            # BLOQUEIO: Se finalizado, ninguém muda o status (exceto Master)
            if old_status == 'Finalizado' and form_status != 'Finalizado' and not is_master:
                flash("Apenas usuários Master podem alterar o status de um projeto 'Finalizado'.", "danger")
                return redirect(url_for('projects.project_list'))

            project.status = form_status

            for i in range(1, 4):
                if request.form.get(f'photo{i}_delete') == 'true':
                    old_filename = getattr(project, f'photo{i}')
                    if old_filename:
                        try:
                            old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], old_filename)
                            if os.path.exists(old_path):
                                os.remove(old_path)
                        except Exception as e:
                            logger.warning(f'Erro ao deletar arquivo físico: {e}')
                    
                    setattr(project, f'photo{i}', '')

            for i in range(1, 4):
                file_key = f'photo{i}_upload'
                if file_key in request.files:
                    file = request.files[file_key]
                    if file.filename != '':
                        new_filename = save_and_resize_image(file, project.id, i)
                        if new_filename:
                            setattr(project, f'photo{i}', new_filename)

            if 'osNumber' in request.form:
                new_os = request.form.get('osNumber') or ''
                # BLOQUEIO: Se já impresso, ninguém desvincula (exceto Master)
                if project.is_printed and not new_os and project.osNumber and not is_master:
                    flash("Esta OS já foi impressa e não pode ser desvinculada (Apenas Master).", "danger")
                else:
                    project.osNumber = new_os

            if 'address' in request.form:
                project.address = request.form.get('address') or ''
            if 'address_number' in request.form:
                project.address_number = request.form.get('address_number') or ''
            if 'neighborhood' in request.form:
                project.neighborhood = request.form.get('neighborhood') or ''
            if 'designer' in request.form:
                project.designer = request.form.get('designer') or ''
            if 'date' in request.form:
                project.date = request.form.get('date') or ''
            if 'osDate' in request.form:
                project.osDate = request.form.get('osDate') or ''
            
            project.has_horizontal = 'has_horizontal' in request.form
            project.has_vertical = 'has_vertical' in request.form
            project.has_devices = 'has_devices' in request.form
            project.has_semaforico = 'has_semaforico' in request.form
            
            # Validação: Responsável obrigatório se tiver data inicial
            def validate_service(prefix, name):
                start_date = request.form.get(f'{prefix}_start_date')
                responsible = request.form.get(f'{prefix}_responsible')
                if start_date and not responsible:
                    raise Exception(f"O responsável pelo serviço '{name}' é obrigatório ao informar a data inicial.")

            validate_service('h', 'Sinalização Horizontal')
            validate_service('v', 'Sinalização Vertical')
            validate_service('d', 'Dispositivos Auxiliares')
            validate_service('s', 'Sinalização Semafórica')

            # Captura estados originais do banco para identificar o que já estava "Travado"
            original_end_dates = {}
            if project.id:
                original_end_dates = {
                    'h': project.h_end_date or '',
                    'v': project.v_end_date or '',
                    'd': project.d_end_date or '',
                    's': project.s_end_date or ''
                }

            def update_service_fields(prefix):
                new_end_date = request.form.get(f'{prefix}_end_date') or ''
                old_db_date = original_end_dates.get(prefix, '')
                
                # Regra de Travamento:
                # Se já tinha data final no banco E o usuário está mantendo uma data final (não limpou),
                # e não é master, ignoramos as outras alterações daquela aba.
                if old_db_date and new_end_date and not is_master:
                    return 
                
                # Caso contrário (Master, serviço aberto, ou usuário LIMPANDO a data para editar):
                # Atualiza tudo normalmente.
                setattr(project, f'{prefix}_start_date', request.form.get(f'{prefix}_start_date') or '')
                setattr(project, f'{prefix}_end_date', new_end_date)
                setattr(project, f'{prefix}_responsible', request.form.get(f'{prefix}_responsible') or '')
                setattr(project, f'{prefix}_progress', get_safe_int(request.form.get(f'{prefix}_progress')))

            update_service_fields('h')
            update_service_fields('v')
            update_service_fields('d')
            update_service_fields('s')
            
            project.observations = request.form.get('observations') or ''

            active_progresses = []
            if project.has_horizontal: active_progresses.append(project.h_progress)
            if project.has_vertical: active_progresses.append(project.v_progress)
            if project.has_devices: active_progresses.append(project.d_progress)
            
            if active_progresses:
                project.progress = get_safe_int(sum(active_progresses) / len(active_progresses))
            else:
                project.progress = 0

            auto_finish = request.form.get('auto_finish') == 'on'
            if old_status != 'Finalizado': 
                if project.progress >= 100 and auto_finish:
                    project.status = 'Concluído'
                    project.completion_date = today
                else: 
                    if project.status == 'Concluído' and old_status != 'Concluído':
                         project.completion_date = today 
                    elif project.status in ['Em Andamento', 'Em Espera', 'Urgente', 'Em Desenvolvimento']:
                         project.completion_date = None
            
            db.session.add(project)
            
            if not old_status:
                log_activity(f"Cadastrou o projeto OS {project.osNumber}", project.id)
            elif old_status != project.status:
                log_activity(f"Alterou status da OS {project.osNumber} para {project.status}", project.id)
            else:
                log_activity(f"Atualizou dados da OS {project.osNumber}", project.id)

            db.session.commit()
            
            final_status = project.status

            if old_status and old_status != final_status:
                proj_num = project.projectNumber or "N/A"
                msg = f"🔔 <b>Status Alterado</b>\n\n" \
                      f"<b>Projeto:</b> {proj_num}\n" \
                      f"<b>OS:</b> {project.osNumber}\n" \
                      f"<b>Endereço:</b> {project.address}\n" \
                      f"<b>De:</b> {old_status}\n" \
                      f"<b>Para:</b> {final_status}"
                send_telegram_notification_async(msg)
                flash(f'Projeto salvo! Status atualizado para "{final_status}".', 'success')

            elif not old_status:
                proj_num = project.projectNumber or "N/A"
                msg = f"🆕 <b>Novo Projeto Cadastrado</b>\n\n" \
                      f"<b>Projeto:</b> {proj_num}\n" \
                      f"<b>OS:</b> {project.osNumber}\n" \
                      f"<b>Endereço:</b> {project.address}\n" \
                      f"<b>Status Inicial:</b> {final_status}"
                send_telegram_notification_async(msg)
                flash(f'Novo projeto cadastrado e notificado no Telegram.', 'success')
            else:
                flash('Projeto salvo com sucesso!', 'success')

            return redirect(url_for('projects.project_list'))
        except Exception as e:
            db.session.rollback()
            logger.error(f'Erro ao salvar projeto: {e}')
            return render_template('project_form.html', project=project, error=str(e), team_members=team_members)
        
    return render_template('project_form.html', project=project, can_edit=can_edit, team_members=team_members, suggested_number=suggested_number)

@projects_bp.route('/project/<int:project_id>/print_os')
@login_required
def print_os(project_id):
    project = Project.query.get_or_404(project_id)
    # Marca como impresso para travar desvinculação
    if not project.is_printed:
        project.is_printed = True
        db.session.commit()
        
    today = datetime.now(timezone).strftime('%d/%m/%Y')
    return render_template('project_os_print.html', project=project, today=today, auto_print=True)

@projects_bp.route('/project/<int:project_id>/update_os_quick', methods=['POST'])
@login_required
def update_os_quick(project_id):
    project = Project.query.get_or_404(project_id)
    try:
        data = request.json
        new_os = data.get('os_number') or ''
        
        is_master = session.get('role') == SUPER_ROLE
        
        # BLOQUEIO: Se finalizado, ninguém muda nada (exceto Master)
        if project.status == 'Finalizado' and not is_master:
            return jsonify({"success": False, "message": "Apenas usuários Master podem editar projetos 'Finalizado'."}), 403

        if project.is_printed and not new_os and project.osNumber and not is_master:
            return jsonify({"success": False, "message": "Esta OS já foi impressa e não pode ser desvinculada."}), 403

        project.osNumber = new_os
        project.osDate = data.get('os_date') or ''
        db.session.commit()
        return jsonify({"success": True, "message": "OS atualizada no banco!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 400

@projects_bp.route('/project/cad', methods=['GET', 'POST'])
@projects_bp.route('/project/cad/<int:project_id>', methods=['GET', 'POST'])
@roles_required('Master', 'Administrador', 'Técnico de Projetos', 'Técnico', 'Responsável Técnico')
def project_cad(project_id=None):
    project = None
    if project_id:
        project = Project.query.get_or_404(project_id)

    def get_next_available_number(field):
        year = datetime.now(timezone).year
        pattern = f"%/{year}"
        last_project = Project.query.filter(
            getattr(Project, field).like(pattern),
            getattr(Project, field).isnot(None)
        ).order_by(db.desc(Project.id)).first()
        
        if last_project:
            last_number = getattr(last_project, field)
            try:
                num_part = int(last_number.split('/')[0])
                return f"{num_part + 1}/{year}"
            except (ValueError, IndexError):
                return f"1/{year}"
        return f"1/{year}"

    team_members = User.query.filter_by(active=True).order_by(User.name).all()
    today = datetime.now(timezone).strftime('%Y-%m-%d')
    next_project_number = get_next_available_number('projectNumber')
    next_os_number = get_next_available_number('osNumber')
    
    # Permissão de edição
    user_role = session.get('role')
    is_master = user_role == SUPER_ROLE
    is_finalized = project and project.status == 'Finalizado'
    
    if is_finalized and not is_master:
        can_edit = False
    else:
        # Apenas Master e Técnico de Projetos podem editar dados cadastrais
        can_edit = user_role in [SUPER_ROLE, 'Técnico de Projetos']

    if request.method == 'POST':
        try:
            is_new = False
            if not project:
                project = Project()
                is_new = True
                project.progress = 0
                project.h_progress = 0
                project.v_progress = 0
                project.d_progress = 0
                project.s_progress = 0
                project.h_responsible = ""
                project.v_responsible = ""
                project.d_responsible = ""
                project.s_responsible = ""
            
            manual_project_id = request.form.get('project_id_manual')
            if is_new:
                project.projectNumber = manual_project_id if manual_project_id else next_project_number
            else:
                project.projectNumber = manual_project_id

            project.address = request.form.get('address') or ''
            project.address_number = request.form.get('address_number') or ''
            project.neighborhood = request.form.get('neighborhood') or ''
            
            project.doc_type = request.form.get('doc_type') or ''
            project.doc_number = request.form.get('doc_number') or ''
            project.doc_year = request.form.get('doc_year') or ''

            user_role = session.get('role')
            is_master = user_role == SUPER_ROLE
            
            # BLOQUEIO: Se finalizado, ninguém muda nada (exceto Master)
            if not can_edit and is_finalized:
                flash("Apenas usuários Master podem editar projetos 'Finalizado'.", "danger")
                return redirect(url_for('projects.project_list'))

            if 'open_os' in request.form:
                new_os = request.form.get('os_number') or next_os_number
                # Se desvinculando (campo vazio enviado?)
                # Na verdade esse form radio 'open_os' geralmente é pra ABRIR.
                project.osNumber = new_os
                project.osDate = request.form.get('os_date') or today
            elif is_new:
                project.osNumber = ""
            elif not is_new and project.is_printed and project.osNumber and not is_master:
                # Se não veio 'open_os' mas já existia e estava impresso, e não é master
                # Aqui precisamos ser cuidadosos: se o form não enviou 'open_os', ele quer fechar/desvincular?
                flash("Esta OS já foi impressa e não pode ser desvinculada (Apenas Master).", "danger")
                # Mantém a OS anterior
            else:
                # Pode desvincular se não estiver impresso ou for master
                if not is_new and not ('open_os' in request.form):
                     project.osNumber = ""
            
            project.designer = request.form.get('designer') or ''
            
            project.date = request.form.get('date') or today
            project.status = request.form.get('status', 'Em Espera')
            project.observations = request.form.get('observations') or ''

            project.has_horizontal = 'has_horizontal' in request.form
            project.has_vertical = 'has_vertical' in request.form
            project.has_devices = 'has_devices' in request.form
            project.has_semaforico = 'has_semaforico' in request.form

            if is_new:
                db.session.add(project)
                db.session.flush()
                log_activity(f"Cadastrou o novo projeto {project.projectNumber}", project.id)
            else:
                log_activity(f"Editou os dados do projeto {project.projectNumber}", project.id)
            
            db.session.commit()

            if is_new:
                proj_num = project.projectNumber or "N/A"
                os_num = f" | OS: {project.osNumber}" if project.osNumber else ""
                msg = f"🆕 <b>Novo Projeto Cadastrado</b>\n\n" \
                      f"<b>Projeto:</b> {proj_num}{os_num}\n" \
                      f"<b>Endereço:</b> {project.address}\n" \
                      f"<b>Status:</b> {project.status}"
                send_telegram_notification_async(msg)

            flash(f'Projeto {project.projectNumber} salvo com sucesso!', 'success')
            return redirect(url_for('projects.project_list'))

        except Exception as e:
            db.session.rollback()
            logger.error(f'Erro no cadastro de projeto: {e}')
            return render_template('project_cad.html', error=str(e), team_members=team_members, today=today, 
                                   next_project_number=next_project_number, next_os_number=next_os_number, project=project)

    return render_template('project_cad.html', team_members=team_members, today=today, 
                           next_project_number=next_project_number, next_os_number=next_os_number, 
                           project=project, can_edit=can_edit)
