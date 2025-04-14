// Базовые JavaScript функции
document.addEventListener('DOMContentLoaded', function() {
    console.log('PPEE Analyzer web application initialized');
});

// Функция для обновления статуса индексации
function updateIndexingStatus(applicationId) {
    fetch(`/applications/${applicationId}/status`)
        .then(response => response.json())
        .then(data => {
            // Проверяем, изменился ли статус с indexing на другой
            if (data.status !== 'indexing') {
                // Статус изменился - перезагружаем страницу
                window.location.reload();
                return;
            }

            // Обновляем прогресс-бар
            const progressBar = document.getElementById('indexing-progress');
            if (progressBar && data.progress !== null) {
                progressBar.style.width = `${data.progress}%`;
                progressBar.setAttribute('aria-valuenow', data.progress);
            }

            // Обновляем сообщение о статусе
            const statusMessage = document.getElementById('status-message');
            if (statusMessage && data.message) {
                statusMessage.textContent = data.message;
            }

            // Обновляем визуальное отображение этапов
            if (data.stage) {
                updateStages(data.stage);
            }
        })
        .catch(error => console.error('Ошибка при обновлении статуса:', error));
}

// Функция для обновления отображения этапов
function updateStages(stage) {
    const stages = ['prepare', 'convert', 'split', 'index', 'complete'];
    let reachedCurrentStage = false;

    stages.forEach(s => {
        const stageElement = document.getElementById(`stage-${s}`);
        if (stageElement) {
            if (s === stage) {
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
        }
    });
}

// Инициализация обновления статуса при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    // Проверяем, есть ли на странице контейнер индексации
    const progressContainer = document.querySelector('.indexing-progress-container');
    if (progressContainer) {
        // Получаем ID приложения из URL
        const pathParts = window.location.pathname.split('/');
        const applicationIndex = pathParts.indexOf('applications') + 1;
        if (applicationIndex > 0 && applicationIndex < pathParts.length) {
            const applicationId = pathParts[applicationIndex];

            // Запускаем периодическое обновление статуса каждые 2 секунды
            setInterval(() => updateIndexingStatus(applicationId), 2000);

            // Инициализируем первоначальное состояние
            updateStages('prepare');
        }
    }
});