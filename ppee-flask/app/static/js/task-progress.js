/**
 * Класс для отслеживания прогресса выполнения асинхронных задач
 */
class TaskProgressTracker {
    constructor(options) {
        this.statusUrl = options.statusUrl;
        this.progressBarId = options.progressBarId;
        this.statusMessageId = options.statusMessageId;
        this.progressContainerId = options.progressContainerId;
        this.resultsContainerId = options.resultsContainerId;
        this.onComplete = options.onComplete || this._defaultOnComplete.bind(this);
        this.onError = options.onError || this._defaultOnError.bind(this);
        this.onProgress = options.onProgress || null;
        this.checkInterval = options.checkInterval || 2000;
        this.maxAttempts = options.maxAttempts || 100;
        this.checkIntervalId = null;
        this.taskId = null;
        this.lastProgress = -1;
    }

    _getElements() {
        this.progressBar = document.getElementById(this.progressBarId);
        this.statusMessage = document.getElementById(this.statusMessageId);
        this.progressContainer = document.getElementById(this.progressContainerId);
        this.resultsContainer = document.getElementById(this.resultsContainerId);
    }

    startTracking(taskId) {
        this._getElements();
        this.taskId = taskId;
        console.log(`Начато отслеживание задачи с ID: ${taskId}`);

        if (this.checkIntervalId) {
            clearInterval(this.checkIntervalId);
        }

        if (this.progressContainer) {
            this.progressContainer.style.display = 'block';
        }
        if (this.resultsContainer) {
            this.resultsContainer.style.display = 'none';
        }

        this._updateProgress(0, 'Запуск задачи...');

        this.checkIntervalId = setInterval(() => this.checkStatus(), this.checkInterval);
        this.checkStatus();
    }

    checkStatus() {
        if (!this.taskId || !this.checkIntervalId) {
            return;
        }

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

    _handleStatusUpdate(data) {
        console.log("Получен ответ о статусе:", data);

        if (typeof data.progress === 'number') {
            const progress = Math.min(100, Math.max(0, data.progress));
            if (progress !== this.lastProgress) {
                console.log(`Обновление прогресса: ${this.lastProgress}% -> ${progress}%`);
                this.lastProgress = progress;
                this._updateProgress(progress, data.message || 'Выполнение...');
            }
        }

        if (this.onProgress && typeof this.onProgress === 'function') {
            this.onProgress(data);
        }

        const isExplicitSuccess =
            data.status === 'success' ||
            data.state === 'SUCCESS' ||
            (data.progress === 100 && data.stage === 'complete');

        const isError =
            data.status === 'error' ||
            data.state === 'FAILURE' ||
            data.status === 'cancelled' ||
            (data.message && data.message.toLowerCase().includes('ошибка'));

        if (isError) {
            this._stopTracking();
            this.onError(data);
        }
        else if (isExplicitSuccess) {
            this._completeTask(data);
        }
        else if (data.status === 'pending') {
            this._updateProgress(5, data.message || 'Задача ожидает выполнения...');
        }
        else if (data.status === 'progress' || data.status === 'PROGRESS') {
            if (data.progress >= 100) {
                console.log("Задача завершена по прогрессу: 100%");
                this._completeTask(data);
            }
        }
        else if (data.application_status === 'indexed' || data.application_status === 'analyzed') {
            console.log(`Задача завершена по статусу заявки: ${data.application_status}`);
            this._completeTask({
                status: 'success',
                progress: 100,
                message: `Задача успешно завершена (${data.application_status})`,
                stage: 'complete'
            });
        }
    }

    _completeTask(data) {
        console.log("Завершение задачи:", data);
        this._updateProgress(100, data.message || 'Задача успешно завершена');
        this._stopTracking();
        this.onComplete(data);
    }

    _updateProgress(progress, message) {
        progress = Math.min(100, Math.max(0, progress));
        console.log(`_updateProgress вызван: ${progress}%, сообщение: "${message}"`);

        if (this.progressBar) {
            this.progressBar.style.width = `${progress}%`;
            this.progressBar.setAttribute('aria-valuenow', progress);
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
            if (message.includes('<span')) {
                this.statusMessage.innerHTML = message;
            } else {
                this.statusMessage.textContent = message;
            }
            console.log(`Сообщение статуса обновлено: "${message}"`);
        }
    }

    _stopTracking() {
        if (this.checkIntervalId) {
            clearInterval(this.checkIntervalId);
            this.checkIntervalId = null;
        }
    }

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