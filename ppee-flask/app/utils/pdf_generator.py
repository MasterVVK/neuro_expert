import os
import tempfile
from datetime import datetime
from flask import render_template, make_response
from weasyprint import HTML, CSS
import logging

logger = logging.getLogger(__name__)


def generate_pdf_report(application, checklist_results, doc_names_mapping):
    """
    Генерирует PDF отчет для результатов анализа заявки

    Args:
        application: Объект заявки
        checklist_results: Словарь с результатами по чек-листам
        doc_names_mapping: Маппинг document_id -> имя файла

    Returns:
        bytes: PDF файл в виде байтов
    """
    try:
        # Рендерим HTML шаблон для PDF
        html_content = render_template(
            'applications/results_pdf.html',
            application=application,
            checklist_results=checklist_results,
            doc_names_mapping=doc_names_mapping,
            generation_date=datetime.now()
        )

        # CSS для PDF (можно вынести в отдельный файл)
        pdf_css = CSS(string='''
            @page {
                size: A4;
                margin: 2cm;
                @bottom-right {
                    content: "Страница " counter(page) " из " counter(pages);
                }
            }

            body {
                font-family: Arial, sans-serif;
                font-size: 12pt;
                line-height: 1.6;
                color: #333;
            }

            h1 {
                font-size: 20pt;
                margin-bottom: 20px;
                color: #2c3e50;
            }

            h2 {
                font-size: 16pt;
                margin-top: 30px;
                margin-bottom: 15px;
                color: #34495e;
                page-break-after: avoid;
            }

            h3 {
                font-size: 14pt;
                margin-top: 20px;
                margin-bottom: 10px;
                color: #34495e;
                page-break-after: avoid;
            }

            table {
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 20px;
                page-break-inside: avoid;
            }

            th, td {
                border: 1px solid #ddd;
                padding: 8px;
                text-align: left;
            }

            th {
                background-color: #f5f5f5;
                font-weight: bold;
            }

            tr:nth-child(even) {
                background-color: #f9f9f9;
            }

            .header-info {
                background-color: #f8f9fa;
                padding: 15px;
                border-radius: 5px;
                margin-bottom: 20px;
            }

            .info-row {
                display: flex;
                margin-bottom: 5px;
            }

            .info-label {
                font-weight: bold;
                width: 200px;
            }

            .info-value {
                flex: 1;
            }

            .not-found-value {
                color: #d9534f;
                font-weight: 500;
            }

            .source-info {
                font-size: 10pt;
                color: #666;
            }

            .footer {
                margin-top: 50px;
                padding-top: 20px;
                border-top: 1px solid #ddd;
                font-size: 10pt;
                color: #666;
                text-align: center;
            }

            .page-break {
                page-break-after: always;
            }

            .parameter-section {
                margin-bottom: 30px;
            }

            .no-results {
                color: #666;
                font-style: italic;
            }
        ''')

        # Генерируем PDF
        pdf_file = HTML(string=html_content).write_pdf(stylesheets=[pdf_css])

        return pdf_file

    except Exception as e:
        logger.error(f"Ошибка при генерации PDF: {str(e)}")
        raise


def create_pdf_response(pdf_bytes, filename):
    """
    Создает Flask response для отправки PDF файла

    Args:
        pdf_bytes: PDF файл в виде байтов
        filename: Имя файла для скачивания

    Returns:
        Flask Response объект
    """
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response