from app import db
from datetime import datetime


class Checklist(db.Model):
    """Модель чек-листа для проверки документов"""
    __tablename__ = 'checklists'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Отношения
    parameters = db.relationship('ChecklistParameter', backref='checklist', lazy='dynamic',
                                 cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Checklist {self.id}: {self.name}>'


class ChecklistParameter(db.Model):
    """Модель параметра чек-листа"""
    __tablename__ = 'checklist_parameters'

    id = db.Column(db.Integer, primary_key=True)
    checklist_id = db.Column(db.Integer, db.ForeignKey('checklists.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    search_query = db.Column(db.String(255), nullable=False)

    # Настройки поиска
    use_reranker = db.Column(db.Boolean, default=False)
    search_limit = db.Column(db.Integer, default=3)
    rerank_limit = db.Column(db.Integer, default=10)  # Количество документов для ре-ранкинга

    # LLM конфигурация
    llm_model = db.Column(db.String(100), nullable=False)
    llm_prompt_template = db.Column(db.Text, nullable=False)
    llm_temperature = db.Column(db.Float, default=0.1)
    llm_max_tokens = db.Column(db.Integer, default=1000)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Отношения
    results = db.relationship('ParameterResult', backref='parameter', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<ChecklistParameter {self.id}: {self.name}>'


class ParameterResult(db.Model):
    """Модель результата по параметру чек-листа"""
    __tablename__ = 'parameter_results'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    parameter_id = db.Column(db.Integer, db.ForeignKey('checklist_parameters.id'), nullable=False)
    value = db.Column(db.Text)
    confidence = db.Column(db.Float)
    search_results = db.Column(db.JSON)
    llm_request = db.Column(db.JSON)  # Новое поле для хранения запроса к LLM
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<ParameterResult {self.id}: {self.value[:20]}>'