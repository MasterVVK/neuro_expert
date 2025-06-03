/**
 * Модуль для отслеживания прогресса выполнения асинхронных задач и
 * обновления интерфейса пользователя.
 */
class TaskProgressTracker {
    /**
     * Инициализация трекера прогресса задачи
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
        this.onProgress = options.onProgress || null;
        this.checkInterval = options.checkInterval || 2000;
        this.maxAttempts = options.maxAttempts || 100;
        this.stages = options.stages || [];
        this.checkIntervalId = null;
        this.taskId = null;
        this.lastProgress = -1; // Для отслеживания изменений прогресса
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
        this._updateProgress(0, 'Запуск задачи...');

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
        if (!this.taskId || !this.checkIntervalId) {
            return;
        }

        // Формируем URL для запроса статуса
        const url = `${this.statusUrl}/${this.taskId}`;

        console.log(`Запрос статуса задачи: ${url}`);

        fetch(url)
            .then(response => {
                if (!response.ok) {
                    console.error(`HTTP error! status: ${response.status} ${response.statusText}`);
                    return null;
                }
                return response.json();
            })
            .then(data => {
                if (data) {
                    this._handleStatusUpdate(data);
                }
            })
            .catch(error => {
                console.error('Ошибка при проверке статуса задачи:', error);
                if (this.statusMessage) {
                    this.statusMessage.textContent = `Ошибка связи... повторная попытка`;
                }
            });
    }

    /**
     * Обрабатывает обновление статуса задачи
     *
     * @param {Object} data - Данные о статусе задачи
     */
    _handleStatusUpdate(data) {
        // Выводим отладочную информацию
        console.log("Получен ответ о статусе:", data);

        // ВАЖНО: Всегда обновляем прогресс, если он есть в данных
        if (typeof data.progress === 'number') {
            const progress = Math.min(100, Math.max(0, data.progress)); // Ограничиваем от 0 до 100

            // Обновляем прогресс только если он изменился
            if (progress !== this.lastProgress) {
                console.log(`Обновление прогресса: ${this.lastProgress}% -> ${progress}%`);
                this.lastProgress = progress;
                this._updateProgress(progress, data.message || 'Выполнение...');
            }
        }

        // Обновляем этап, если указан
        const stageInfo = data.stage || data.substatus || data.status;
        if (stageInfo && stageInfo !== 'pending') {
            this.updateStages(stageInfo);
        }

        // Вызываем пользовательский обработчик прогресса
        if (this.onProgress && typeof this.onProgress === 'function') {
            this.onProgress(data);
        }

        // Определяем состояние задачи
        const isExplicitSuccess =
            data.status === 'success' ||
            data.state === 'SUCCESS' ||
            (data.progress === 100 && data.stage === 'complete');

        const isError =
            data.status === 'error' ||
            data.state === 'FAILURE' ||
            data.status === 'cancelled' ||
            (data.message && data.message.toLowerCase().includes('ошибка'));

        // Обработка различных статусов
        if (isError) {
            this._stopTracking();
            this.onError(data);
        }
        else if (isExplicitSuccess) {
            this._completeTask(data);
        }
        else if (data.status === 'pending') {
            // Задача в ожидании
            this._updateProgress(5, data.message || 'Задача ожидает выполнения...');
            this.updateStages('starting');
        }
        else if (data.status === 'progress' || data.status === 'PROGRESS') {
            // Задача выполняется - прогресс уже обновлен выше

            // Проверяем, не завершена ли задача по прогрессу
            if (data.progress >= 100) {
                console.log("Задача завершена по прогрессу: 100%");
                this._completeTask(data);
            }
        }
        else if (data.application_status === 'indexed' || data.application_status === 'analyzed') {
            // Статус заявки изменился на завершенный
            console.log(`Задача завершена по статусу заявки: ${data.application_status}`);
            this._completeTask({
                status: 'success',
                progress: 100,
                message: `Задача успешно завершена (${data.application_status})`,
                stage: 'complete'
            });
        }
    }

    /**
     * Завершает задачу успешно
     *
     * @param {Object} data - Данные о результатах задачи
     */
    _completeTask(data) {
        console.log("Завершение задачи:", data);

        // Устанавливаем финальный прогресс
        this._updateProgress(100, data.message || 'Задача успешно завершена');

        // Обновляем отображение этапов
        if (this.stages && this.stages.length > 0) {
            const finalStage = data.stage || 'complete';
            this.updateStages(finalStage);
            this._markAllStagesCompleted();
        }

        // Останавливаем отслеживание
        this._stopTracking();

        // Вызываем обработчик завершения
        this.onComplete(data);
    }

    /**
     * Обновляет отображение прогресса
     *
     * @param {number} progress - Процент выполнения (0-100)
     * @param {string} message - Сообщение о текущем статусе
     */
    _updateProgress(progress, message) {
        // Убеждаемся, что прогресс в допустимых пределах
        progress = Math.min(100, Math.max(0, progress));

        console.log(`_updateProgress вызван: ${progress}%, сообщение: "${message}"`);

        if (this.progressBar) {
            // Обновляем ширину прогресс-бара
            this.progressBar.style.width = `${progress}%`;
            this.progressBar.setAttribute('aria-valuenow', progress);

            // Добавляем текст прогресса внутрь бара, если его нет
            if (progress > 0 && !this.progressBar.textContent) {
                this.progressBar.textContent = `${progress}%`;
            } else if (progress > 0) {
                this.progressBar.textContent = `${progress}%`;
            }

            console.log(`Прогресс-бар обновлен до ${progress}%`);
        } else {
            console.warn('Элемент прогресс-бара не найден!');
        }

        if (this.statusMessage && message) {
            this.statusMessage.textContent = message;
            console.log(`Сообщение статуса обновлено: "${message}"`);
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
        if (!this.stages || this.stages.length === 0) {
            return;
        }

        console.log(`Обновление этапа: '${currentStage}'`);

        let reachedCurrentStage = false;
        let stageFound = false;

        this.stages.forEach(stage => {
            const stageElement = document.getElementById(`${this.stagePrefix}${stage}`);

            if (!stageElement || stageElement.style.display === 'none') {
                return;
            }

            if (stage === currentStage) {
                stageElement.classList.add('active');
                stageElement.classList.remove('completed');
                reachedCurrentStage = true;
                stageFound = true;
                console.log(`- Этап '${stage}' помечен как активный`);
            } else if (!reachedCurrentStage) {
                stageElement.classList.remove('active');
                stageElement.classList.add('completed');
                console.log(`- Этап '${stage}' помечен как завершенный`);
            } else {
                stageElement.classList.remove('active');
                stageElement.classList.remove('completed');
                console.log(`- Этап '${stage}' помечен как ожидающий`);
            }
        });

        if (!stageFound && this.stages.length > 0 && currentStage === 'complete') {
            const lastStage = this.stages[this.stages.length - 1];
            const lastStageElement = document.getElementById(`${this.stagePrefix}${lastStage}`);

            if (lastStageElement) {
                lastStageElement.classList.add('active');
                console.log(`- Этап 'complete' не найден, помечаем последний этап '${lastStage}' как активный`);
            }
        }
    }

    /**
     * Пометка всех этапов как завершенных
     */
    _markAllStagesCompleted() {
        if (!this.stages || this.stages.length === 0) {
            return;
        }

        console.log('Пометка всех этапов как завершенных');

        this.stages.forEach(stage => {
            const stageElement = document.getElementById(`${this.stagePrefix}${stage}`);
            if (stageElement && stageElement.style.display !== 'none') {
                stageElement.classList.remove('active');
                stageElement.classList.add('completed');
                console.log(`- Этап '${stage}' помечен как завершенный`);
            }
        });

        const completeStage = document.getElementById(`${this.stagePrefix}complete`);
        if (completeStage && completeStage.style.display !== 'none') {
            completeStage.classList.remove('completed');
            completeStage.classList.add('active');
            console.log(`- Этап 'complete' помечен как активный`);
        }
    }

    /**
     * Обработчик по умолчанию для успешного завершения задачи
     */
    _defaultOnComplete(data) {
        console.log('Задача успешно завершена:', data);

        if (this.progressContainer) {
            this.progressContainer.style.display = 'none';
        }

        if (this.resultsContainer) {
            this.resultsContainer.style.display = 'block';
        } else {
            console.log("Контейнер результатов не найден, перезагружаем страницу...");
            window.location.reload();
        }
    }

    /**
     * Обработчик по умолчанию для ошибки задачи
     */
    _defaultOnError(data) {
        console.error('Ошибка выполнения задачи:', data);

        if (this.progressContainer) {
            this.progressContainer.style.display = 'none';
        }

        const errorContainer = document.createElement('div');
        errorContainer.className = 'error-container';
        errorContainer.innerHTML = `
            <div class="error-message">
                <h3>Ошибка при выполнении задачи</h3>
                <p>${data.message || 'Неизвестная ошибка'}</p>
                <button onclick="window.location.reload()" class="button">Обновить страницу</button>
            </div>
        `;

        if (this.progressContainer && this.progressContainer.parentNode) {
            this.progressContainer.parentNode.insertBefore(errorContainer, this.progressContainer.nextSibling);
        }
    }
}