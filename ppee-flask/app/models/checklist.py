from app import db
from datetime import datetime


class Checklist(db.Model):
    """Модель чек-листа для анализа документов"""
    __tablename__ = 'checklists'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    description = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # Владелец чек-листа
    is_public = db.Column(db.Boolean, nullable=False, default=False)  # Общий доступ
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Отношения
    user = db.relationship('User', backref=db.backref('checklists', lazy='dynamic'))
    parameters = db.relationship('ChecklistParameter', backref='checklist', lazy='dynamic',
                                 cascade='all, delete-orphan', order_by='ChecklistParameter.order_index')

    def __repr__(self):
        return f'<Checklist {self.id}: {self.name}>'

    def get_next_order_index(self):
        """Возвращает следующий доступный order_index для нового параметра"""
        # Используем прямой запрос к БД для получения максимального order_index
        from sqlalchemy import func
        max_index = db.session.query(func.max(ChecklistParameter.order_index)).filter(
            ChecklistParameter.checklist_id == self.id
        ).scalar()

        # Если параметров нет, max_index будет None
        if max_index is None:
            return 0

        return max_index + 1


class ChecklistParameter(db.Model):
    """Модель параметра чек-листа"""
    __tablename__ = 'checklist_parameters'

    id = db.Column(db.Integer, primary_key=True)
    checklist_id = db.Column(db.Integer, db.ForeignKey('checklists.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    search_query = db.Column(db.String(255), nullable=False)
    # Если не заполнен, используется search_query
    llm_query = db.Column(db.String(255), nullable=True)

    # Порядок отображения параметра
    order_index = db.Column(db.Integer, nullable=False, default=0)

    # Настройки поиска
    use_reranker = db.Column(db.Boolean, default=False)
    search_limit = db.Column(db.Integer, default=3)
    rerank_limit = db.Column(db.Integer, default=10)  # Количество документов для ре-ранкинга

    # НОВОЕ ПОЛЕ: Использовать полный перебор чанков при неудаче
    use_full_scan = db.Column(db.Boolean, default=False)

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

    def get_llm_query(self):
        """Возвращает запрос для использования в LLM (llm_query если задан, иначе search_query)"""
        return self.llm_query or self.search_query


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