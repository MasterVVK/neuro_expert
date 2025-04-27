/**
 * Модуль для отслеживания прогресса выполнения асинхронных задач и
 * обновления интерфейса пользователя.
 */
class TaskProgressTracker {
    /**
     * Инициализация трекера прогресса задачи
     *
     * @param {Object} options - Настройки трекера прогресса
     * @param {string} options.statusUrl - URL для проверки статуса задачи
     * @param {string} options.progressBarId - ID элемента прогресс-бара
     * @param {string} options.statusMessageId - ID элемента для отображения статусного сообщения
     * @param {string} options.progressContainerId - ID контейнера с прогрессом (для скрытия/показа)
     * @param {string} options.resultsContainerId - ID контейнера с результатами (для скрытия/показа)
     * @param {string} options.stagePrefix - Префикс ID элементов этапов (например, 'stage-')
     * @param {Function} options.onComplete - Функция, вызываемая при успешном завершении
     * @param {Function} options.onError - Функция, вызываемая при ошибке
     * @param {number} options.checkInterval - Интервал проверки в мс (по умолчанию 2000)
     */
    constructor(options) {
        this.statusUrl = options.statusUrl;
        this.progressBarId = options.progressBarId;
        this.statusMessageId = options.statusMessageId;
        this.progressContainerId = options.progressContainerId;
        this.resultsContainerId = options.resultsContainerId;
        this.stagePrefix = options.stagePrefix || 'stage-';
        this.onComplete = options.onComplete || this._defaultOnComplete.bind(this);
        this.onError = options.onError || this._defaultOnError.bind(this);
        this.checkInterval = options.checkInterval || 2000;
        this.stages = options.stages || [];
        this.checkIntervalId = null;
        this.taskId = null;
    }

    /**
     * Получает элементы DOM
     */
    _getElements() {
        this.progressBar = document.getElementById(this.progressBarId);
        this.statusMessage = document.getElementById(this.statusMessageId);
        this.progressContainer = document.getElementById(this.progressContainerId);
        this.resultsContainer = document.getElementById(this.resultsContainerId);
    }

    /**
     * Начинает отслеживание задачи
     *
     * @param {string} taskId - Идентификатор задачи
     */
    startTracking(taskId) {
        this._getElements();
        this.taskId = taskId;
        console.log(`Начато отслеживание задачи с ID: ${taskId}`);

        // Очищаем предыдущий интервал, если он был
        if (this.checkIntervalId) {
            clearInterval(this.checkIntervalId);
        }

        // Показываем прогресс-бар, скрываем результаты
        if (this.progressContainer) {
            this.progressContainer.style.display = 'block';
        }
        if (this.resultsContainer) {
            this.resultsContainer.style.display = 'none';
        }

        // Устанавливаем начальный прогресс
        if (this.progressBar) {
            this.progressBar.style.width = '0%';
            this.progressBar.setAttribute('aria-valuenow', 0);
        }
        if (this.statusMessage) {
            this.statusMessage.textContent = 'Запуск задачи...';
        }

        // Устанавливаем начальные состояния этапов
        this.updateStages('starting');

        // Начинаем периодическую проверку статуса
        this.checkIntervalId = setInterval(() => this.checkStatus(), this.checkInterval);

        // Сразу проверяем статус первый раз
        this.checkStatus();
    }

    /**
     * Проверяет статус выполнения задачи
     */
    checkStatus() {
        if (!this.taskId) {
            console.error('Отсутствует идентификатор задачи');
            return;
        }

        // Формируем правильный URL для запроса
        let url;

        // Если URL заканчивается на слеш, просто добавляем ID задачи
        if (this.statusUrl.endsWith('/')) {
            url = `${this.statusUrl}${this.taskId}`;
        } else {
            // Иначе добавляем слеш и ID задачи
            url = `${this.statusUrl}/${this.taskId}`;
        }

        console.log(`Запрос статуса задачи: ${url}`);

        fetch(url)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                console.log("Получен ответ о статусе:", data);
                this._handleStatusUpdate(data);
            })
            .catch(error => {
                console.error('Ошибка при проверке статуса задачи:', error);
                this._stopTracking();
                this.onError({ message: 'Ошибка сети при проверке статуса задачи' });
            });
    }

    /**
     * Обрабатывает обновление статуса задачи
     *
     * @param {Object} data - Данные о статусе задачи
     */
    _handleStatusUpdate(data) {
        // Обработка различных статусов задачи
        if (data.status === 'pending') {
            this._updateProgress(5, data.message || 'Задача ожидает выполнения...');
            this.updateStages('starting');
        } else if (data.status === 'progress') {
            this._updateProgress(data.progress || 0, data.message || 'Выполняется...');

            // Обновляем этап, если указан
            if (data.stage || data.substatus) {
                this.updateStages(data.stage || data.substatus);
            }
        } else if (data.status === 'error') {
            this._stopTracking();
            this.onError(data);
        } else if (data.status === 'success') {
            this._stopTracking();
            this.onComplete(data);
        } else {
            // Неизвестный статус
            console.warn('Неизвестный статус задачи:', data.status);
        }
    }

    /**
     * Обновляет отображение прогресса
     *
     * @param {number} progress - Процент выполнения (0-100)
     * @param {string} message - Сообщение о текущем статусе
     */
    _updateProgress(progress, message) {
        if (this.progressBar) {
            this.progressBar.style.width = `${progress}%`;
            this.progressBar.setAttribute('aria-valuenow', progress);
        }

        if (this.statusMessage && message) {
            this.statusMessage.textContent = message;
        }
    }

    /**
     * Останавливает отслеживание
     */
    _stopTracking() {
        if (this.checkIntervalId) {
            clearInterval(this.checkIntervalId);
            this.checkIntervalId = null;
        }
    }

    /**
     * Обновляет визуальное отображение этапов
     *
     * @param {string} currentStage - Текущий этап
     */
    updateStages(currentStage) {
        // Если этапы не определены, пропускаем
        if (!this.stages || this.stages.length === 0) {
            return;
        }

        let reachedCurrentStage = false;

        this.stages.forEach(stage => {
            const stageElement = document.getElementById(`${this.stagePrefix}${stage}`);

            // Пропускаем, если элемент не существует или скрыт
            if (!stageElement || stageElement.style.display === 'none') {
                return;
            }

            if (stage === currentStage) {
                stageElement.classList.add('active');
                stageElement.classList.remove('completed');
                reachedCurrentStage = true;
            } else if (!reachedCurrentStage) {
                stageElement.classList.remove('active');
                stageElement.classList.add('completed');
            } else {
                stageElement.classList.remove('active');
                stageElement.classList.remove('completed');
            }
        });
    }

    /**
     * Обработчик по умолчанию для успешного завершения задачи
     */
    _defaultOnComplete(data) {
        if (this.progressContainer) {
            this.progressContainer.style.display = 'none';
        }

        if (this.resultsContainer) {
            this.resultsContainer.style.display = 'block';
        }

        console.log('Задача успешно завершена:', data);
    }

    /**
     * Обработчик по умолчанию для ошибки задачи
     */
    _defaultOnError(data) {
        if (this.progressContainer) {
            this.progressContainer.style.display = 'none';
        }

        if (this.resultsContainer) {
            this.resultsContainer.style.display = 'block';
        }

        const errorMessage = data.message || 'Произошла ошибка при выполнении задачи';

        if (this.resultsContainer) {
            this.resultsContainer.innerHTML = `<div class="error-message">${errorMessage}</div>`;
        }

        console.error('Ошибка выполнения задачи:', errorMessage);
    }
}