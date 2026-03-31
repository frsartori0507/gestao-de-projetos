from extensions import db
from datetime import datetime
import pytz

timezone = pytz.timezone('America/Sao_Paulo')

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=True)
    role = db.Column(db.String(50), nullable=False)
    active = db.Column(db.Boolean, default=True)

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    projectNumber = db.Column(db.String(50), nullable=True)
    osNumber = db.Column(db.String(50), nullable=True)
    title = db.Column(db.String(100), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(50), nullable=False)
    progress = db.Column(db.Integer, default=0)
    designer = db.Column(db.String(100), nullable=True)
    tech_responsible = db.Column(db.String(100), nullable=True)
    date = db.Column(db.String(20), nullable=True)
    osDate = db.Column(db.String(20), nullable=True)
    
    # Novos Campos
    doc_type = db.Column(db.String(50), nullable=True)
    doc_number = db.Column(db.String(50), nullable=True)
    doc_year = db.Column(db.String(10), nullable=True)
    address_number = db.Column(db.String(20), nullable=True)
    neighborhood = db.Column(db.String(100), nullable=True)
    
    # Scope
    has_horizontal = db.Column(db.Boolean, default=True)
    has_vertical = db.Column(db.Boolean, default=True)
    has_devices = db.Column(db.Boolean, default=True)
    has_semaforico = db.Column(db.Boolean, default=False)
    
    # Horizontal Signaling
    h_start_date = db.Column(db.String(20), nullable=True)
    h_end_date = db.Column(db.String(20), nullable=True)
    h_responsible = db.Column(db.String(100), nullable=True)
    h_progress = db.Column(db.Integer, default=0)
    
    # Vertical Signaling
    v_start_date = db.Column(db.String(20), nullable=True)
    v_end_date = db.Column(db.String(20), nullable=True)
    v_responsible = db.Column(db.String(100), nullable=True)
    v_progress = db.Column(db.Integer, default=0)
    
    # Devices
    d_start_date = db.Column(db.String(20), nullable=True)
    d_end_date = db.Column(db.String(20), nullable=True)
    d_responsible = db.Column(db.String(100), nullable=True)
    d_progress = db.Column(db.Integer, default=0)
    
    # Semaphoric Signaling
    s_start_date = db.Column(db.String(20), nullable=True)
    s_end_date = db.Column(db.String(20), nullable=True)
    s_responsible = db.Column(db.String(100), nullable=True)
    s_progress = db.Column(db.Integer, default=0)
    
    observations = db.Column(db.Text, nullable=True)
    completion_date = db.Column(db.String(20), nullable=True)
    
    # Fotos (Anexos)
    photo1 = db.Column(db.String(255), nullable=True)
    photo2 = db.Column(db.String(255), nullable=True)
    photo3 = db.Column(db.String(255), nullable=True)
    is_printed = db.Column(db.Boolean, default=False)

    @property
    def parsed_date(self):
        if not self.date: return None
        try: return datetime.strptime(self.date[:10], '%Y-%m-%d')
        except: return None

    @property
    def days_open(self):
        if not self.parsed_date: return 0
        now = datetime.now(timezone).replace(tzinfo=None) # Ensure same type for subtraction
        return (now - self.parsed_date).days

class Agenda(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    time = db.Column(db.String(10), nullable=True)
    category = db.Column(db.String(50), default='Geral')

class SystemSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(500), nullable=True)

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(100), nullable=False)
    action = db.Column(db.String(200), nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone).replace(tzinfo=None))
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
