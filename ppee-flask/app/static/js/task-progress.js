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
        this.onProgress = options.onProgress || null;  // Новый обработчик прогресса
        this.checkInterval = options.checkInterval || 2000;
        this.maxAttempts = options.maxAttempts || 100;
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

        // Определяем состояние задачи и соответствующую обработку
        const isExplicitSuccess =
            data.status === 'success' ||
            data.state === 'SUCCESS' ||
            (data.progress === 100 && data.stage === 'complete');

        // Проверяем индикаторы ошибки
        const isError =
            data.status === 'error' ||
            data.state === 'FAILURE' ||
            (data.message && data.message.toLowerCase().includes('ошибка'));

        // Обработка различных статусов задачи
        if (isError) {
            // Случай ошибки
            this._stopTracking();
            this.onError(data);
        }
        else if (isExplicitSuccess) {
            // Явное указание на успешное завершение
            this._completeTask(data);
        }
        else if (data.status === 'pending') {
            // Задача в ожидании
            this._updateProgress(5, data.message || 'Задача ожидает выполнения...');
            this.updateStages('starting');
        }
        else if (data.status === 'progress') {
            // Задача выполняется, обновляем прогресс
            this._updateProgress(data.progress || 0, data.message || 'Выполняется...');

            // Обновляем этап, если указан
            const stageInfo = data.stage || data.substatus || data.status;
            if (stageInfo) {
                this.updateStages(stageInfo);
            }

            // Вызываем обработчик прогресса если он определен
            if (this.onProgress && typeof this.onProgress === 'function') {
                this.onProgress(data);
            }

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
        else {
            // Неизвестный статус, проверяем прогресс
            if (data.progress >= 100) {
                console.log("Задача завершена по прогрессу при неизвестном статусе");
                this._completeTask(data);
            } else {
                console.warn('Неизвестный статус задачи:', data.status);
                // Обновляем прогресс, если он указан
                if (data.progress) {
                    this._updateProgress(data.progress, data.message || 'Выполнение задачи...');
                }
            }
        }
    }

    /**
     * Принудительно завершает отслеживание задачи
     *
     * @param {string} message - Сообщение о причине завершения
     */
    _forceComplete(message) {
        console.warn(`Принудительное завершение отслеживания: ${message}`);

        // Останавливаем отслеживание
        this._stopTracking();

        // Показываем сообщение пользователю
        this.onError({
            status: 'error',
            message: message
        });

        // Перезагружаем страницу
        window.location.reload();
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
            // Используем последний этап в списке или явно указанный этап
            const finalStage = data.stage || 'complete';
            this.updateStages(finalStage);
            // Помечаем все этапы как завершенные
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
        // Ограничиваем прогресс до 99% перед явным завершением
        if (progress > 99 && this.checkIntervalId) {
            progress = 99;
        }

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

        console.log(`Обновление этапа: '${currentStage}'`);

        let reachedCurrentStage = false;
        let stageFound = false;

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

        // Если нужного этапа нет в списке, помечаем последний как активный
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

        // Если есть этап 'complete', делаем его активным
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

        // Скрываем прогресс-контейнер
        if (this.progressContainer) {
            this.progressContainer.style.display = 'none';
        }

        // Показываем контейнер с результатами
        if (this.resultsContainer) {
            this.resultsContainer.style.display = 'block';
        } else {
            // Если контейнера результатов нет, перезагружаем страницу
            console.log("Контейнер результатов не найден, перезагружаем страницу...");
            window.location.reload();
        }
    }

    /**
     * Обработчик по умолчанию для ошибки задачи
     */
    _defaultOnError(data) {
        console.error('Ошибка выполнения задачи:', data);

        // Сразу скрываем прогресс-контейнер в случае ошибки
        if (this.progressContainer) {
            this.progressContainer.style.display = 'none';
        }

        // Создаем и показываем сообщение об ошибке
        const errorContainer = document.createElement('div');
        errorContainer.className = 'error-container';
        errorContainer.innerHTML = `
            <div class="error-message">
                <h3>Ошибка при выполнении задачи</h3>
                <p>${data.message || 'Неизвестная ошибка'}</p>
                <button onclick="window.location.reload()" class="button">Обновить страницу</button>
            </div>
        `;

        // Добавляем контейнер после прогресс-контейнера
        if (this.progressContainer && this.progressContainer.parentNode) {
            this.progressContainer.parentNode.insertBefore(errorContainer, this.progressContainer.nextSibling);
        }
    }
}