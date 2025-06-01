from app import db
from datetime import datetime
import os

# Связь между заявками и чек-листами
application_checklists = db.Table('application_checklists',
                                  db.Column('application_id', db.Integer, db.ForeignKey('applications.id'),
                                            primary_key=True),
                                  db.Column('checklist_id', db.Integer, db.ForeignKey('checklists.id'),
                                            primary_key=True)
                                  )


class Application(db.Model):
    """Модель заявки на анализ документа"""
    __tablename__ = 'applications'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(50), default='created')  # created, indexing, indexed, analyzing, analyzed, error
    status_message = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    task_id = db.Column(db.String(36), nullable=True)  # ID задачи Celery

    # Отношения
    user = db.relationship('User', backref=db.backref('applications', lazy='dynamic'))
    files = db.relationship('File', backref='application', lazy='dynamic', cascade='all, delete-orphan')
    parameter_results = db.relationship('ParameterResult', backref='application', lazy='dynamic',
                                        cascade='all, delete-orphan')
    checklists = db.relationship('Checklist', secondary=application_checklists,
                                 backref=db.backref('applications', lazy='dynamic'))

    def __repr__(self):
        return f'<Application {self.id}: {self.name}>'

    def get_status_display(self):
        """Возвращает отображаемое значение статуса"""
        status_map = {
            'created': 'Создана',
            'indexing': 'Индексация',
            'indexed': 'Проиндексирована',
            'analyzing': 'Анализ',
            'analyzed': 'Проанализирована',
            'error': 'Ошибка'
        }
        return status_map.get(self.status, self.status)

    def get_document_names_mapping(self):
        """Возвращает маппинг document_id -> original_filename"""
        mapping = {}
        for file in self.files:
            # Генерируем document_id так же, как при индексации
            doc_id = f"doc_{os.path.basename(file.file_path).replace(' ', '_').replace('.', '_')}"
            mapping[doc_id] = file.original_filename
        return mapping


class File(db.Model):
    """Модель файла, связанного с заявкой"""
    __tablename__ = 'files'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255))
    file_path = db.Column(db.String(512), nullable=False)
    file_size = db.Column(db.Integer)  # Размер в байтах
    file_type = db.Column(db.String(50))  # document, attachment
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Новые поля для отслеживания индексации
    indexing_status = db.Column(db.String(50), default='pending')  # pending, indexing, completed, error
    index_session_id = db.Column(db.String(36))  # UUID сессии индексации
    chunks_count = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text)
    indexing_started_at = db.Column(db.DateTime)
    indexing_completed_at = db.Column(db.DateTime)

    def __repr__(self):
        return f'<File {self.id}: {self.original_filename}>'