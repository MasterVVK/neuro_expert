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
        this._errorCount = 0; // Счетчик ошибок
        this._maxErrorRetries = 5; // Максимальное количество повторных попыток при ошибках
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

        // Сбрасываем счетчик ошибок
        this._errorCount = 0;

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

        // Формируем URL для запроса статуса - НЕ ИЗМЕНЯЕМ URL
        const url = `${this.statusUrl}/${this.taskId}`;

        console.log(`Запрос статуса задачи: ${url}`);

        fetch(url)
            .then(response => {
                if (!response.ok) {
                    const errorMessage = `HTTP error! status: ${response.status} ${response.statusText}`;
                    console.error(errorMessage);
                    this._handleNetworkError(errorMessage);
                    return null;
                }
                return response.json();
            })
            .then(data => {
                if (data) {
                    // Сбрасываем счетчик ошибок при успешном ответе
                    this._errorCount = 0;
                    this._handleStatusUpdate(data);
                }
            })
            .catch(error => {
                console.error('Ошибка при проверке статуса задачи:', error);
                this._handleNetworkError(`Ошибка сети: ${error.message}`);
            });
    }

    /**
     * Обрабатывает ошибки сети
     *
     * @param {string} errorMessage - Сообщение об ошибке
     */
    _handleNetworkError(errorMessage) {
        this._errorCount++;
        console.warn(`Ошибка при запросе статуса (попытка ${this._errorCount}/${this._maxErrorRetries}): ${errorMessage}`);

        // Обновляем сообщение о статусе
        if (this.statusMessage) {
            this.statusMessage.textContent = `Ошибка связи... повторная попытка ${this._errorCount}/${this._maxErrorRetries}`;
        }

        // Если превышено максимальное число попыток, останавливаем отслеживание
        if (this._errorCount >= this._maxErrorRetries) {
            this._stopTracking();
            this.onError({
                message: `Не удалось получить статус задачи после ${this._maxErrorRetries} попыток. Попробуйте обновить страницу.`
            });
        }
    }

    /**
     * Обрабатывает обновление статуса задачи
     *
     * @param {Object} data - Данные о статусе задачи
     */
    _handleStatusUpdate(data) {
        // Выводим отладочную информацию
        console.log("Получен ответ о статусе:", data);

        // Обработка различных статусов задачи
        if (data.status === 'pending') {
            this._updateProgress(5, data.message || 'Задача ожидает выполнения...');
            this.updateStages('starting');
        } else if (data.status === 'progress') {
            this._updateProgress(data.progress || 0, data.message || 'Выполняется...');

            // Обновляем этап, если указан
            // Проверяем наличие информации об этапе в разных полях ответа
            const stageInfo = data.stage || data.substatus || data.status;
            if (stageInfo) {
                this.updateStages(stageInfo);
            }
        } else if (data.status === 'error') {
            this._stopTracking();
            this.onError(data);
        } else if (data.status === 'success') {
            // Устанавливаем финальный прогресс
            this._updateProgress(100, data.message || 'Задача успешно завершена');

            // Обновляем отображение этапов - показываем последний этап как завершенный
            if (this.stages && this.stages.length > 0) {
                // Используем последний этап в списке
                this.updateStages(this.stages[this.stages.length - 1]);
                // Дополнительно помечаем все этапы как завершенные
                this._markAllStagesCompleted();
            }

            // Останавливаем отслеживание и вызываем обработчик завершения
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

        console.log(`Обновление этапа: '${currentStage}'`);

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
    }

    /**
     * Обработчик по умолчанию для успешного завершения задачи
     */
    _defaultOnComplete(data) {
        // После небольшой задержки скрываем прогресс-контейнер
        setTimeout(() => {
            if (this.progressContainer) {
                this.progressContainer.style.display = 'none';
            }

            // Показываем контейнер с результатами
            if (this.resultsContainer) {
                this.resultsContainer.style.display = 'block';
            }
        }, 500); // Задержка в 500мс, чтобы пользователь увидел завершение всех этапов

        console.log('Задача успешно завершена:', data);
    }

    /**
     * Обработчик по умолчанию для ошибки задачи
     */
    _defaultOnError(data) {
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

        console.error('Ошибка выполнения задачи:', data.message);
    }
}