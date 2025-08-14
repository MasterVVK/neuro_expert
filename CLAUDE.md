# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **neuro_expert** repository containing a document analysis and information extraction system. The project consists of two main components:

1. **Flask Web Application** (`ppee-flask/`) - Main web interface for document management, analysis, and user interaction
2. **Document Processing Scripts** (`arch/`, `data/scripts/`) - Standalone Python scripts for PDF processing and document analysis

## Common Development Commands

### Flask Application (ppee-flask/)
```bash
# Run the Flask application
cd ppee-flask
python wsgi.py

# Run Celery worker for background tasks
cd ppee-flask
python celery_worker.py

# Database migrations
cd ppee-flask
flask db migrate -m "Migration message"
flask db upgrade

# Initialize database
cd ppee-flask
python initialize_db.py
```

### Standalone Scripts
```bash
# Run PDF conversion script
cd arch
bash run_conversion.sh

# Activate virtual environment for scripts
source ./.venv/bin/activate
```

## Architecture Overview

### Flask Application Structure
- **Blueprints**: Modular application structure with separate modules for authentication, applications, checklists, LLM management, search, statistics, and users
- **Models**: SQLAlchemy models for User, Application, File, Checklist, ChecklistParameter, and ParameterResult
- **Services**: FastAPI client for external service communication
- **Tasks**: Celery background tasks for document indexing, LLM analysis, and search operations
- **Templates**: Jinja2 templates with custom filters for datetime formatting, pagination, and data presentation

### Key Components
- **Authentication System**: Flask-Login based user management with role-based access
- **Document Processing**: Integration with Docling for PDF-to-markdown conversion
- **Vector Search**: Qdrant integration for semantic document search
- **LLM Integration**: Ollama service integration for document analysis and information extraction
- **Background Processing**: Celery with Redis for asynchronous task execution

### External Dependencies
- **Database**: SQLite (development) / PostgreSQL (production)
- **Vector Database**: Qdrant for document embeddings and search
- **Message Broker**: Redis for Celery task queue
- **LLM Service**: Ollama for language model inference
- **FastAPI Service**: External service at http://localhost:8001 for document processing

## Configuration

The application uses environment-based configuration:
- Development: `DevelopmentConfig` (default)
- Testing: `TestingConfig` 
- Production: `ProductionConfig`

Key environment variables:
- `FLASK_CONFIG`: Configuration environment
- `DATABASE_URL`: Database connection string
- `QDRANT_HOST`, `QDRANT_PORT`: Vector database connection
- `OLLAMA_URL`: LLM service endpoint
- `FASTAPI_URL`: External processing service URL

## Database Migrations

The project uses Flask-Migrate for database schema management. Migration files are in `ppee-flask/migrations/versions/`. Always run migrations when database schema changes are detected.

## Development Notes

- The codebase uses Russian language for UI strings and comments
- Custom Jinja2 filters are registered for datetime formatting and data presentation
- Document chunking can use semantic splitting with GPU acceleration (configurable)
- Background tasks update progress through Celery state management
- The system supports hybrid search combining vector similarity and keyword matching