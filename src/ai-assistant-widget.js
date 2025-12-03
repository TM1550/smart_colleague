class AIAssistantWidget {
    constructor(config = {}) {
        this.config = {
            apiUrl: config.apiUrl || 'http://localhost:5000',
            position: config.position || 'bottom-right',
            brandColor: config.brandColor || '#6366f1',
            accentColor: config.accentColor || '#8b5cf6',
            widgetWidth: config.widgetWidth || 'min(90vw, 1200px)',
            widgetHeight: config.widgetHeight || 'min(85vh, 800px)',
            mobileBreakpoint: config.mobileBreakpoint || 768,
            animationDuration: config.animationDuration || 300,
            ...config
        };

        this.state = {
            isVisible: false,
            availableTasks: [],
            isListening: false,
            chatMessages: [],
            currentChatMessage: '',
            activeTab: 'tasks',
            isWaitingForResponse: false,
            isMinimized: false,
            hasUnreadMessages: false
        };
        
        this.init();
    }

    async init() {
        this.createWidget();
        this.applyGlobalStyles();
        await this.initializeWidget();
        await this.loadPopularInstructions();
        this.attachEventListeners();
        
        this.addWelcomeMessage();
    }

    applyGlobalStyles() {
        const styles = document.createElement('style');
        styles.textContent = `
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
            
            .ai-assistant-widget {
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                --primary: ${this.config.brandColor};
                --primary-dark: ${this.darkenColor(this.config.brandColor, 20)};
                --primary-light: ${this.lightenColor(this.config.brandColor, 95)};
                --accent: ${this.config.accentColor};
                --surface: #ffffff;
                --background: #f8fafc;
                --text-primary: #1e293b;
                --text-secondary: #64748b;
                --border: #e2e8f0;
                --shadow-sm: 0 1px 3px rgba(0,0,0,0.12);
                --shadow-md: 0 4px 12px rgba(0,0,0,0.1);
                --shadow-lg: 0 10px 40px rgba(0,0,0,0.15);
                --radius-sm: 8px;
                --radius-md: 12px;
                --radius-lg: 16px;
                --radius-xl: 24px;
                --transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            }

            .ai-assistant-btn {
                position: fixed;
                bottom: 24px;
                right: 24px;
                width: 60px;
                height: 60px;
                border-radius: 50%;
                background: linear-gradient(135deg, var(--primary), var(--accent));
                color: white;
                border: none;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 24px;
                box-shadow: var(--shadow-lg);
                z-index: 10000;
                transition: var(--transition);
                transform-origin: center;
                overflow: hidden;
            }

            .ai-assistant-btn:hover {
                transform: scale(1.05) rotate(5deg);
                box-shadow: 0 15px 50px rgba(99, 102, 241, 0.4);
            }

            .ai-assistant-btn::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: linear-gradient(135deg, transparent, rgba(255,255,255,0.2));
                opacity: 0;
                transition: opacity 0.3s ease;
            }

            .ai-assistant-btn:hover::before {
                opacity: 1;
            }

            .ai-assistant-btn .notification-badge {
                position: absolute;
                top: -4px;
                right: -4px;
                background: #ef4444;
                color: white;
                font-size: 12px;
                font-weight: 600;
                width: 20px;
                height: 20px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                animation: pulse 2s infinite;
            }

            @keyframes pulse {
                0%, 100% { transform: scale(1); }
                50% { transform: scale(1.1); }
            }

            .ai-assistant-panel {
                position: fixed;
                bottom: 100px;
                right: 24px;
                width: ${this.config.widgetWidth};
                height: ${this.config.widgetHeight};
                border-radius: var(--radius-xl);
                box-shadow: var(--shadow-lg);
                z-index: 9999;
                display: flex;
                flex-direction: column;
                overflow: hidden;
                transform: translateY(20px);
                opacity: 0;
                visibility: hidden;
                transition: opacity ${this.config.animationDuration}ms ease,
                            transform ${this.config.animationDuration}ms ease,
                            visibility ${this.config.animationDuration}ms ease;
                border: 1px solid var(--border);
            }

            .ai-assistant-panel.visible {
                transform: translateY(0);
                opacity: 1;
                visibility: visible;
                background: rgba(255,255,255,0.2);
            }

            .ai-assistant-panel.minimized {
                height: 64px;
                overflow: hidden;
            }

            .ai-assistant-header {
                padding: 20px 24px;
                background: rgba(255,255,255);
                color: white;
                display: flex;
                align-items: center;
                justify-content: space-between;
                flex-shrink: 0;
            }

            .ai-assistant-header h3 {
                margin: 0;
                font-size: 18px;
                font-weight: 600;
                display: flex;
                align-items: center;
                gap: 10px;
            }

            .ai-assistant-header h3::before {
                content: '🤖';
                font-size: 20px;
            }

            .ai-assistant-actions {
                display: flex;
                gap: 8px;
                align-items: center;
            }

            .ai-action-btn {
                background: rgba(255,255,255);
                border: none;
                width: 36px;
                height: 36px;
                border-radius: 50%;
                color: white;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: var(--transition);
                font-size: 16px;
            }

            .ai-action-btn:hover {
                background: rgba(255,255,255,0.3);
                transform: rotate(90deg);
            }

            .ai-tabs {
                display: flex;
                background: rgba(255,255,255);
                border-radius: var(--radius-lg);
                flex-shrink: 0;
            }

            .ai-tab-btn {
                flex: 1;
                padding: 12px 16px;
                border: none;
                background: transparent;
                color: var(--text-secondary);
                font-size: 14px;
                font-weight: 500;
                cursor: pointer;
                border-radius: var(--radius-md);
                transition: var(--transition);
                display: flex;
                align-items: center;
                justify-content: center;
            }

            .ai-tab-btn.active {
                background: var(--surface);
                color: var(--primary);
                box-shadow: var(--shadow-sm);
            }

            .ai-tab-btn:hover:not(.active) {
                color: var(--text-primary);
            }

            .ai-tab-content {
                flex: 1;
                overflow: hidden;
                position: relative;
                background: rgba(255, 255, 255);
            }

            .ai-tab-pane {
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                padding: 24px;
                overflow-y: auto;
                display: none;
                opacity: 0;
                transition: opacity ${this.config.animationDuration}ms ease;
                
            }

            .ai-tab-pane.active {
                display: block;
                opacity: 1;
            }

            /* Tasks Tab Styles */
            .ai-search-box {
                position: relative;
                margin-bottom: 24px;
            }

            .ai-search-input {
                width: 100%;
                padding: 14px 20px 14px 48px;
                border: 2px solid var(--border);
                border-radius: var(--radius-lg);
                font-size: 14px;
                transition: var(--transition);
                background: var(--surface);
                color: var(--text-primary);
            }

            .ai-search-input:focus {
                outline: none;
                border-color: var(--primary);
                box-shadow: 0 0 0 3px var(--primary-light);
            }

            .ai-search-icon {
                position: absolute;
                left: 16px;
                top: 50%;
                transform: translateY(-50%);
                color: var(--text-secondary);
                font-size: 18px;
            }

            .ai-voice-btn {
                width: 100%;
                padding: 16px;
                background: linear-gradient(135deg, var(--primary), var(--accent));
                color: white;
                border: none;
                border-radius: var(--radius-lg);
                font-size: 15px;
                font-weight: 500;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 10px;
                margin-bottom: 24px;
                transition: var(--transition);
            }

            .ai-voice-btn:hover {
                transform: translateY(-2px);
                box-shadow: var(--shadow-md);
            }

            .ai-voice-btn.listening {
                background: linear-gradient(135deg, #ef4444, #dc2626);
                animation: pulse 1.5s infinite;
            }

            .ai-section {
                margin-bottom: 32px;
            }

            .ai-section-title {
                font-size: 15px;
                font-weight: 600;
                color: var(--text-primary);
                margin: 0 0 16px 0;
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .ai-tasks-grid {
                display: grid;
                gap: 12px;
            }

            .ai-task-card {
                padding: 16px;
                background: var(--surface);
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                cursor: pointer;
                transition: var(--transition);
                display: flex;
                align-items: flex-start;
                gap: 12px;
            }

            .ai-task-card:hover {
                transform: translateY(-2px);
                border-color: var(--primary);
                box-shadow: var(--shadow-md);
            }

            .ai-task-icon {
                width: 40px;
                height: 40px;
                border-radius: var(--radius-md);
                background: var(--primary-light);
                color: var(--primary);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 20px;
                flex-shrink: 0;
            }

            .ai-task-content {
                flex: 1;
            }

            .ai-task-title {
                font-weight: 600;
                color: var(--text-primary);
                margin-bottom: 4px;
                font-size: 14px;
            }

            .ai-task-desc {
                font-size: 13px;
                color: var(--text-secondary);
                line-height: 1.5;
            }

            /* Chat Tab Styles */
            .ai-chat-messages {
                height: calc(100% - 80px);
                overflow-y: auto;
                padding: 16px;
                scroll-behavior: smooth;
            }

            .ai-chat-messages::-webkit-scrollbar {
                width: 6px;
            }

            .ai-chat-messages::-webkit-scrollbar-track {
                background: var(--background);
                border-radius: 3px;
            }

            .ai-chat-messages::-webkit-scrollbar-thumb {
                background: var(--border);
                border-radius: 3px;
            }

            .ai-message {
                margin-bottom: 20px;
                display: flex;
                gap: 12px;
                animation: slideIn ${this.config.animationDuration}ms ease;
            }

            @keyframes slideIn {
                from { opacity: 0; transform: translateX(-10px); }
                to { opacity: 1; transform: translateX(0); }
            }

            .ai-message.user {
                flex-direction: row-reverse;
            }

            .ai-message-avatar {
                width: 36px;
                height: 36px;
                border-radius: 50%;
                background: var(--primary-light);
                color: var(--primary);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 16px;
                flex-shrink: 0;
            }

            .ai-message.user .ai-message-avatar {
                background: var(--accent);
                color: black;
            }

            .ai-message-content {
                max-width: 70%;
                background: var(--background);
                padding: 16px;
                border-radius: var(--radius-lg);
                position: relative;
            }

            .ai-message.user .ai-message-content {
                background: linear-gradient(135deg, var(--primary), var(--accent));
                color: black;
                border-radius: var(--radius-lg) var(--radius-lg) 4px var(--radius-lg);
            }

            .ai-message.assistant .ai-message-content {
                border-radius: var(--radius-lg) var(--radius-lg) var(--radius-lg) 4px;
            }

            .ai-message-text {
                font-size: 14px;
                line-height: 1.6;
                white-space: pre-wrap;
                word-break: break-word;
            }

            .ai-message-time {
                font-size: 11px;
                color: var(--text-secondary);
                margin-top: 8px;
                text-align: right;
            }

            .ai-message.user .ai-message-time {
                color: rgba(0, 0, 0, 0.7);
            }

            .ai-instruction-steps {
                margin-top: 16px;
                background: var(--surface);
                border-radius: var(--radius-md);
                padding: 16px;
                border: 1px solid var(--border);
            }

            .ai-step {
                padding: 12px;
                background: var(--background);
                border-radius: var(--radius-md);
                margin-bottom: 8px;
                border-left: 4px solid var(--primary);
            }

            .ai-step:last-child {
                margin-bottom: 0;
            }

            .ai-step-number {
                font-weight: 600;
                color: var(--primary);
                margin-right: 8px;
            }

            .ai-chat-input-container {
                padding: 20px 24px;
                background: var(--surface);
                border-top: 1px solid var(--border);
                display: flex;
                gap: 12px;
                align-items: flex-end;
                flex-shrink: 0;
            }

            .ai-chat-input-wrapper {
                flex: 1;
                position: relative;
            }

            .ai-chat-input {
                width: 100%;
                min-height: 44px;
                max-height: 120px;
                padding: 12px 48px 12px 16px;
                border: 2px solid var(--border);
                border-radius: var(--radius-lg);
                font-size: 14px;
                resize: none;
                background: var(--surface);
                color: var(--text-primary);
                transition: var(--transition);
                font-family: inherit;
            }

            .ai-chat-input:focus {
                outline: none;
                border-color: var(--primary);
                box-shadow: 0 0 0 3px var(--primary-light);
            }

            .ai-chat-voice-btn {
                position: absolute;
                right: 12px;
                bottom: 12px;
                background: transparent;
                border: none;
                color: var(--text-secondary);
                cursor: pointer;
                padding: 4px;
                border-radius: 50%;
                transition: var(--transition);
            }

            .ai-chat-voice-btn:hover {
                background: var(--background);
                color: var(--primary);
            }

            .ai-send-btn {
                background: linear-gradient(135deg, var(--primary), var(--accent));
                color: white;
                border: none;
                width: 44px;
                height: 44px;
                border-radius: 50%;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 18px;
                transition: var(--transition);
                flex-shrink: 0;
            }

            .ai-send-btn:hover:not(:disabled) {
                transform: scale(1.05);
                box-shadow: var(--shadow-md);
            }

            .ai-send-btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }

            .ai-typing-indicator {
                display: flex;
                align-items: center;
                gap: 4px;
                padding: 12px 16px;
                background: var(--background);
                border-radius: var(--radius-lg);
                margin: 8px 0;
                width: fit-content;
            }

            .ai-typing-dot {
                width: 8px;
                height: 8px;
                background: var(--text-secondary);
                border-radius: 50%;
                animation: typing 1.4s infinite;
            }

            .ai-typing-dot:nth-child(2) { animation-delay: 0.2s; }
            .ai-typing-dot:nth-child(3) { animation-delay: 0.4s; }

            @keyframes typing {
                0%, 60%, 100% { transform: translateY(0); }
                30% { transform: translateY(-6px); }
            }

            .ai-empty-state {
                text-align: center;
                padding: 48px 24px;
                color: var(--text-secondary);
            }

            .ai-empty-state-icon {
                font-size: 48px;
                margin-bottom: 16px;
                opacity: 0.5;
            }

            .ai-empty-state-text {
                font-size: 14px;
                line-height: 1.6;
            }

            /* Responsive Design */
            @media (max-width: ${this.config.mobileBreakpoint}px) {
                .ai-assistant-btn {
                    bottom: 16px;
                    right: 16px;
                    width: 56px;
                    height: 56px;
                }

                .ai-assistant-panel {
                    bottom: 88px;
                    right: 16px;
                    left: 16px;
                    width: auto;
                    height: 70vh;
                    background: rgba(255, 255, 255);
                }

                .ai-assistant-header {
                    padding: 16px 20px;
                    background: rgba(255, 255, 255);
                }

                .ai-tabs {
                    margin: 0 16px;
                    background: rgba(255, 255, 255);
                }

                .ai-tab-pane {
                    padding: 20px;
                }

                .ai-chat-input-container {
                    padding: 16px 20px;
                }

                .ai-message-content {
                    max-width: 85%;
                }
            }
        `;
        document.head.appendChild(styles);
    }

    createWidget() {
        // Создаем кнопку ассистента
        this.assistantBtn = document.createElement('button');
        this.assistantBtn.className = 'ai-assistant-btn';
        this.assistantBtn.innerHTML = `
            <span>🤖</span>
            <span class="notification-badge" style="display: none;"></span>
        `;

        // Создаем панель ассистента
        this.panel = document.createElement('div');
        this.panel.className = 'ai-assistant-panel';
        this.panel.innerHTML = this.getPanelTemplate();

        // Добавляем в DOM
        document.body.appendChild(this.assistantBtn);
        document.body.appendChild(this.panel);

        // Кэшируем элементы
        this.cacheElements();
    }

    getPanelTemplate() {
        return `
            <div class="ai-assistant-header">
                <h3>AI Ассистент</h3>
                <div class="ai-assistant-actions">
                    <button class="ai-action-btn" data-action="minimize">➖</button>
                    <button class="ai-action-btn" data-action="close">✕</button>
                </div>
            </div>

            <div class="ai-tabs">
                <button class="ai-tab-btn active" data-tab="tasks">
                    <span>📋</span>
                    <span>Задачи</span>
                </button>
                <button class="ai-tab-btn" data-tab="chat">
                    <span>💬</span>
                    <span>Чат</span>
                </button>
                <button class="ai-tab-btn" data-tab="help">
                    <span>❓</span>
                    <span>Помощь</span>
                </button>
            </div>

            <div class="ai-tab-content">
                <!-- Вкладка задач -->
                <div class="ai-tab-pane active" data-tab="tasks">
                    <div class="ai-search-box">
                        <input type="text" class="ai-search-input" placeholder="Поиск инструкций...">
                        <span class="ai-search-icon">🔍</span>
                    </div>

                    <button class="ai-voice-btn" data-voice="start">
                        <span>🎤</span>
                        <span>Голосовой поиск</span>
                    </button>

                    <div class="ai-section" data-section="popular">
                        <h4 class="ai-section-title">🔥 Популярные инструкции</h4>
                        <div class="ai-tasks-grid" data-popular-tasks></div>
                    </div>

                    <div class="ai-section" data-section="available">
                        <h4 class="ai-section-title">📝 Доступные задачи</h4>
                        <div class="ai-tasks-grid" data-available-tasks></div>
                    </div>

                    <div class="ai-empty-state" data-empty-tasks style="display: none;">
                        <div class="ai-empty-state-icon">🔍</div>
                        <div class="ai-empty-state-text">
                            <p>Нет доступных задач для этой страницы</p>
                            <p style="font-size: 12px; margin-top: 8px;">Попробуйте использовать поиск или голосовой ввод</p>
                        </div>
                    </div>
                </div>

                <!-- Вкладка чата -->
                <div class="ai-tab-pane" data-tab="chat">
                    <div class="ai-chat-messages" data-chat-messages></div>
                    <div class="ai-chat-input-container">
                        <div class="ai-chat-input-wrapper">
                            <textarea class="ai-chat-input" placeholder="Введите ваш вопрос..." rows="1"></textarea>
                            <button class="ai-chat-voice-btn" data-voice="chat">🎤</button>
                        </div>
                        <button class="ai-send-btn" data-send="message">
                            <span>➤</span>
                        </button>
                    </div>
                </div>

                <!-- Вкладка помощи -->
                <div class="ai-tab-pane" data-tab="help">
                    <div class="ai-empty-state">
                        <div class="ai-empty-state-icon">🤖</div>
                        <div class="ai-empty-state-text">
                            <p style="font-weight: 600; color: var(--text-primary); margin-bottom: 16px;">Как использовать ассистент</p>
                            <div style="text-align: left; max-width: 400px; margin: 0 auto;">
                                <div style="margin-bottom: 12px;">
                                    <span style="font-weight: 500;">🔍 Поиск:</span> Найдите инструкции по задачам
                                </div>
                                <div style="margin-bottom: 12px;">
                                    <span style="font-weight: 500;">🎤 Голос:</span> Используйте голосовой ввод
                                </div>
                                <div style="margin-bottom: 12px;">
                                    <span style="font-weight: 500;">💬 Чат:</span> Задавайте вопросы в чате
                                </div>
                                <div style="margin-bottom: 12px;">
                                    <span style="font-weight: 500;">📁 Экспорт:</span> Сохраняйте инструкции в PDF/JSON/TXT
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    cacheElements() {
        this.elements = {
            panel: this.panel,
            assistantBtn: this.assistantBtn,
            notificationBadge: this.assistantBtn.querySelector('.notification-badge'),
            
            // Кнопки действий
            minimizeBtn: this.panel.querySelector('[data-action="minimize"]'),
            closeBtn: this.panel.querySelector('[data-action="close"]'),
            
            // Вкладки
            tabBtns: this.panel.querySelectorAll('.ai-tab-btn'),
            tabPanes: this.panel.querySelectorAll('.ai-tab-pane'),
            
            // Вкладка задач
            searchInput: this.panel.querySelector('.ai-search-input'),
            voiceBtn: this.panel.querySelector('[data-voice="start"]'),
            popularTasks: this.panel.querySelector('[data-popular-tasks]'),
            availableTasks: this.panel.querySelector('[data-available-tasks]'),
            emptyTasks: this.panel.querySelector('[data-empty-tasks]'),
            
            // Вкладка чата
            chatMessages: this.panel.querySelector('[data-chat-messages]'),
            chatInput: this.panel.querySelector('.ai-chat-input'),
            chatVoiceBtn: this.panel.querySelector('[data-voice="chat"]'),
            sendBtn: this.panel.querySelector('[data-send="message"]'),
        };
    }

    attachEventListeners() {
        // Основная кнопка
        this.assistantBtn.addEventListener('click', () => this.togglePanel());

        // Кнопки действий
        this.elements.minimizeBtn.addEventListener('click', () => this.toggleMinimize());
        this.elements.closeBtn.addEventListener('click', () => this.hidePanel());

        // Вкладки
        this.elements.tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const tab = btn.dataset.tab;
                this.switchTab(tab);
            });
        });

        // Поиск
        this.elements.searchInput.addEventListener('input', (e) => {
            this.searchInstructions(e.target.value);
        });

        // Голосовой ввод
        this.elements.voiceBtn.addEventListener('click', () => this.startVoiceInput());
        this.elements.chatVoiceBtn.addEventListener('click', () => this.startVoiceInput());

        // Чат
        this.elements.chatInput.addEventListener('input', (e) => {
            this.state.currentChatMessage = e.target.value;
            this.adjustTextareaHeight(e.target);
        });

        this.elements.chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendChatMessage();
            }
        });

        this.elements.sendBtn.addEventListener('click', () => this.sendChatMessage());
    }

    adjustTextareaHeight(textarea) {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    }

    togglePanel() {
        if (this.state.isMinimized) {
            this.state.isMinimized = false;
            this.panel.classList.remove('minimized');
        }
        
        if (this.state.isVisible) {
            this.hidePanel();
        } else {
            this.showPanel();
        }
    }

    showPanel() {
        this.panel.classList.add('visible');
        this.state.isVisible = true;
        this.state.hasUnreadMessages = false;
        this.updateNotificationBadge();
        
        // Фокусируемся на активной вкладке
        if (this.state.activeTab === 'chat') {
            setTimeout(() => this.elements.chatInput.focus(), 300);
        } else {
            setTimeout(() => this.elements.searchInput.focus(), 300);
        }
    }

    hidePanel() {
        this.panel.classList.remove('visible');
        this.state.isVisible = false;
    }

    toggleMinimize() {
        this.state.isMinimized = !this.state.isMinimized;
        this.panel.classList.toggle('minimized', this.state.isMinimized);
    }

    switchTab(tabName) {
        // Обновляем активную вкладку
        this.elements.tabBtns.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabName);
        });

        this.elements.tabPanes.forEach(pane => {
            pane.classList.toggle('active', pane.dataset.tab === tabName);
        });

        this.state.activeTab = tabName;

        // Обновляем UI в зависимости от вкладки
        if (tabName === 'chat') {
            this.scrollChatToBottom();
            setTimeout(() => this.elements.chatInput.focus(), 100);
        } else if (tabName === 'tasks') {
            setTimeout(() => this.elements.searchInput.focus(), 100);
        }
    }

    addWelcomeMessage() {
        const welcomeMessages = [
            "Привет! Я ваш AI-ассистент. Чем могу помочь?",
            "Здравствуйте! Готов помочь с задачами на этой странице.",
            "Приветствую! Задавайте вопросы или ищите инструкции.",
            "Добрый день! Я здесь, чтобы помочь вам разобраться с интерфейсом."
        ];

        const randomMessage = welcomeMessages[Math.floor(Math.random() * welcomeMessages.length)];
        this.addChatMessage('assistant', randomMessage);
    }

    async initializeWidget() {
        try {
            const context = this.getPageContext();
            const tasks = await this.fetchHelp(context);
            this.state.availableTasks = tasks.available_tasks || [];
            this.renderAvailableTasks();
        } catch (error) {
            console.error('Ошибка инициализации ассистента:', error);
        }
    }

    async loadPopularInstructions() {
        try {
            const response = await fetch(`${this.config.apiUrl}/api/popular-instructions`);
            const data = await response.json();
            this.state.popularInstructions = data.popular_instructions || [];
            this.renderPopularInstructions();
        } catch (error) {
            console.error('Ошибка загрузки популярных инструкций:', error);
        }
    }

    renderAvailableTasks() {
        const container = this.elements.availableTasks;
        
        if (this.state.availableTasks.length === 0) {
            this.elements.emptyTasks.style.display = 'block';
            container.innerHTML = '';
            return;
        }

        this.elements.emptyTasks.style.display = 'none';
        
        const tasksHTML = this.state.availableTasks.map(task => `
            <div class="ai-task-card" onclick="window.aiAssistant.showInstruction('${task.id}', '${task.name}')">
                <div class="ai-task-icon">📋</div>
                <div class="ai-task-content">
                    <div class="ai-task-title">${task.name}</div>
                    <div class="ai-task-desc">${task.description}</div>
                </div>
            </div>
        `).join('');

        container.innerHTML = tasksHTML;
    }

    renderPopularInstructions() {
        const container = this.elements.popularTasks;
        
        if (this.state.popularInstructions.length === 0) {
            container.innerHTML = '<div style="color: var(--text-secondary); font-size: 14px; text-align: center; padding: 20px;">Популярные инструкции загружаются...</div>';
            return;
        }

        const instructionsHTML = this.state.popularInstructions.slice(0, 5).map(instruction => `
            <div class="ai-task-card" onclick="window.aiAssistant.loadInstruction(${JSON.stringify(instruction).replace(/"/g, '&quot;')})">
                <div class="ai-task-icon" style="background: #fef3c7; color: #d97706;">🔥</div>
                <div class="ai-task-content">
                    <div class="ai-task-title">${instruction.task_id}</div>
                    <div class="ai-task-desc">Использовано: ${instruction.usage_count} раз</div>
                </div>
            </div>
        `).join('');

        container.innerHTML = instructionsHTML;
    }

    async searchInstructions(query) {
        if (!query.trim()) {
            this.renderAvailableTasks();
            this.renderPopularInstructions();
            return;
        }

        try {
            const response = await fetch(`${this.config.apiUrl}/api/search-instructions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query })
            });
            
            const data = await response.json();
            this.renderSearchResults(data.results || []);
        } catch (error) {
            console.error('Ошибка поиска:', error);
        }
    }

    renderSearchResults(results) {
        const container = this.elements.availableTasks;
        
        if (results.length === 0) {
            container.innerHTML = '<div style="color: var(--text-secondary); font-size: 14px; text-align: center; padding: 20px;">По вашему запросу ничего не найдено</div>';
            this.elements.emptyTasks.style.display = 'none';
            return;
        }

        const resultsHTML = results.map(result => `
            <div class="ai-task-card" onclick="window.aiAssistant.loadInstruction(${JSON.stringify(result).replace(/"/g, '&quot;')})">
                <div class="ai-task-icon">🔍</div>
                <div class="ai-task-content">
                    <div class="ai-task-title">${result.task_id}</div>
                    <div class="ai-task-desc">${result.user_query || 'Без описания'}</div>
                </div>
            </div>
        `).join('');

        container.innerHTML = resultsHTML;
        this.elements.emptyTasks.style.display = 'none';
    }

    addChatMessage(role, content, instructionData = null) {
        const message = {
            id: Date.now() + Math.random(),
            role,
            content,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            instructionData
        };

        this.state.chatMessages.push(message);
        
        // Если панель закрыта, показываем уведомление
        if (!this.state.isVisible && role === 'assistant') {
            this.state.hasUnreadMessages = true;
            this.updateNotificationBadge();
        }
        
        this.renderChatMessages();
        
        // Прокручиваем вниз
        this.scrollChatToBottom();
    }

    renderChatMessages() {
        const container = this.elements.chatMessages;
        
        if (this.state.chatMessages.length === 0) {
            container.innerHTML = `
                <div class="ai-empty-state">
                    <div class="ai-empty-state-icon">💬</div>
                    <div class="ai-empty-state-text">
                        <p>Начните общение с ассистентом</p>
                        <p style="font-size: 12px; margin-top: 8px;">Задайте вопрос или выберите задачу</p>
                    </div>
                </div>
            `;
            return;
        }

        const messagesHTML = this.state.chatMessages.map(msg => {
            if (msg.role === 'user') {
                return `
                    <div class="ai-message user">
                        <div class="ai-message-avatar">👤</div>
                        <div class="ai-message-content">
                            <div class="ai-message-text">${this.escapeHtml(msg.content)}</div>
                            <div class="ai-message-time">${msg.timestamp}</div>
                        </div>
                    </div>
                `;
            } else {
                if (msg.instructionData) {
                    return `
                        <div class="ai-message assistant">
                            <div class="ai-message-avatar">🤖</div>
                            <div class="ai-message-content">
                                <div class="ai-message-text">${this.escapeHtml(msg.content)}</div>
                                <div class="ai-instruction-steps">
                                    ${msg.instructionData.steps.map((step, i) => `
                                        <div class="ai-step">
                                            <span class="ai-step-number">Шаг ${i + 1}:</span>
                                            <span>${this.escapeHtml(step)}</span>
                                        </div>
                                    `).join('')}
                                </div>
                                <div style="display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap;">
                                    <button onclick="window.aiAssistant.exportInstruction('pdf', '${msg.instructionData.instruction_id}')" 
                                            style="padding: 6px 12px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); font-size: 12px; cursor: pointer; transition: var(--transition);">
                                        📄 PDF
                                    </button>
                                    <button onclick="window.aiAssistant.exportInstruction('json', '${msg.instructionData.instruction_id}')" 
                                            style="padding: 6px 12px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); font-size: 12px; cursor: pointer; transition: var(--transition);">
                                        ⚙️ JSON
                                    </button>
                                    <button onclick="window.aiAssistant.exportInstruction('txt', '${msg.instructionData.instruction_id}')" 
                                            style="padding: 6px 12px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); font-size: 12px; cursor: pointer; transition: var(--transition);">
                                        📝 TXT
                                    </button>
                                </div>
                                <div class="ai-message-time">${msg.timestamp}</div>
                            </div>
                        </div>
                    `;
                } else {
                    return `
                        <div class="ai-message assistant">
                            <div class="ai-message-avatar">🤖</div>
                            <div class="ai-message-content">
                                <div class="ai-message-text">${this.escapeHtml(msg.content)}</div>
                                <div class="ai-message-time">${msg.timestamp}</div>
                            </div>
                        </div>
                    `;
                }
            }
        }).join('');

        container.innerHTML = messagesHTML;
    }

    async sendChatMessage() {
        const message = this.state.currentChatMessage.trim();
        if (!message || this.state.isWaitingForResponse) return;

        // Добавляем сообщение пользователя
        this.addChatMessage('user', message);
        
        // Очищаем поле ввода
        this.elements.chatInput.value = '';
        this.state.currentChatMessage = '';
        this.elements.chatInput.style.height = 'auto';
        
        // Показываем индикатор набора
        this.showTypingIndicator();
        
        this.state.isWaitingForResponse = true;
        this.elements.sendBtn.disabled = true;

        try {
            const response = await fetch(`${this.config.apiUrl}/api/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    message: message,
                    context: this.getPageContext()
                })
            });

            const data = await response.json();
            this.hideTypingIndicator();

            if (data.type === 'instruction') {
                this.addChatMessage('assistant', data.message, data.instruction_data);
            } else {
                this.addChatMessage('assistant', data.message);
            }

        } catch (error) {
            console.error('Chat error:', error);
            this.hideTypingIndicator();
            this.addChatMessage('assistant', 'Извините, произошла ошибка. Попробуйте еще раз.');
        } finally {
            this.state.isWaitingForResponse = false;
            this.elements.sendBtn.disabled = false;
        }
    }

    showTypingIndicator() {
        const indicator = document.createElement('div');
        indicator.className = 'ai-typing-indicator';
        indicator.innerHTML = `
            <span>Ассистент печатает</span>
            <span class="ai-typing-dot"></span>
            <span class="ai-typing-dot"></span>
            <span class="ai-typing-dot"></span>
        `;
        this.elements.chatMessages.appendChild(indicator);
        this.scrollChatToBottom();
    }

    hideTypingIndicator() {
        const indicator = this.elements.chatMessages.querySelector('.ai-typing-indicator');
        if (indicator) {
            indicator.remove();
        }
    }

    scrollChatToBottom() {
        requestAnimationFrame(() => {
            this.elements.chatMessages.scrollTop = this.elements.chatMessages.scrollHeight;
        });
    }

    updateNotificationBadge() {
        if (this.state.hasUnreadMessages && !this.state.isVisible) {
            this.elements.notificationBadge.style.display = 'flex';
        } else {
            this.elements.notificationBadge.style.display = 'none';
        }
    }

    async showInstruction(taskId, taskName) {
        try {
            const context = this.getPageContext();
            const response = await fetch(`${this.config.apiUrl}/api/get-instruction`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    task_id: taskId, 
                    context,
                    user_query: taskName 
                })
            });
            
            const data = await response.json();
            
            // Переключаемся на чат и показываем инструкцию
            this.switchTab('chat');
            this.addChatMessage('assistant', `Вот инструкция для задачи "${taskName}":`, {
                steps: data.steps || [],
                instruction_id: data.instruction_id
            });
            
        } catch (error) {
            console.error('Ошибка получения инструкции:', error);
            this.addChatMessage('assistant', 'Извините, не удалось получить инструкцию.');
        }
    }

    loadInstruction(instruction) {
        this.switchTab('chat');
        this.addChatMessage('assistant', `Вот инструкция:`, {
            steps: instruction.steps || [],
            instruction_id: instruction.id
        });
    }

    async startVoiceInput() {
        if (this.state.isListening) return;
        
        this.state.isListening = true;
        this.elements.voiceBtn.classList.add('listening');
        this.elements.voiceBtn.innerHTML = `
            <span>🔴</span>
            <span>Слушаю...</span>
        `;

        try {
            // Здесь должна быть реализация Web Speech API
            // Для демо используем prompt
            const text = prompt("Введите голосовой запрос:");
            
            if (text) {
                this.processVoiceQuery(text);
            }
        } catch (error) {
            console.error('Ошибка голосового ввода:', error);
        } finally {
            this.state.isListening = false;
            this.elements.voiceBtn.classList.remove('listening');
            this.elements.voiceBtn.innerHTML = `
                <span>🎤</span>
                <span>Голосовой поиск</span>
            `;
        }
    }

    async processVoiceQuery(text) {
        try {
            const context = this.getPageContext();
            const response = await fetch(`${this.config.apiUrl}/api/process-voice`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text, 
                    context
                })
            });
            
            const data = await response.json();
            
            this.switchTab('chat');
            this.addChatMessage('user', text);
            
            if (data.source === 'existing' || data.source === 'generated' || data.source === 'fallback') {
                this.addChatMessage('assistant', data.text, {
                    steps: data.steps,
                    instruction_id: data.instruction_id
                });
            } else {
                this.addChatMessage('assistant', data.text);
            }
            
        } catch (error) {
            console.error('Ошибка обработки голоса:', error);
            this.addChatMessage('assistant', 'Извините, произошла ошибка при обработке голосового запроса.');
        }
    }

    getPageContext() {
        return {
            url: window.location.href,
            dom_snapshot: document.documentElement.outerHTML,
            viewport: {
                width: window.innerWidth,
                height: window.innerHeight
            }
        };
    }

    async fetchHelp(context) {
        const response = await fetch(`${this.config.apiUrl}/api/get-help`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(context)
        });
        return await response.json();
    }

    async exportInstruction(format, instructionId = null) {
        if (!instructionId) return;
        
        try {
            const response = await fetch(
                `${this.config.apiUrl}/api/export/${format}/${instructionId}`
            );
            
            if (response.ok) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `instruction_${instructionId}.${format}`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
            }
        } catch (error) {
            console.error('Ошибка экспорта:', error);
        }
    }

    escapeHtml(unsafe) {
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    lightenColor(color, percent) {
        const num = parseInt(color.replace("#", ""), 16);
        const amt = Math.round(2.55 * percent);
        const R = (num >> 16) + amt;
        const G = (num >> 8 & 0x00FF) + amt;
        const B = (num & 0x0000FF) + amt;
        
        return "#" + (
            0x1000000 +
            (R < 255 ? R < 1 ? 0 : R : 255) * 0x10000 +
            (G < 255 ? G < 1 ? 0 : G : 255) * 0x100 +
            (B < 255 ? B < 1 ? 0 : B : 255)
        ).toString(16).slice(1);
    }

    darkenColor(color, percent) {
        const num = parseInt(color.replace("#", ""), 16);
        const amt = Math.round(2.55 * percent);
        const R = (num >> 16) - amt;
        const G = (num >> 8 & 0x00FF) - amt;
        const B = (num & 0x0000FF) - amt;
        
        return "#" + (
            0x1000000 +
            (R > 0 ? R : 0) * 0x10000 +
            (G > 0 ? G : 0) * 0x100 +
            (B > 0 ? B : 0)
        ).toString(16).slice(1);
    }

    // Публичные методы
    show() {
        this.showPanel();
    }

    hide() {
        this.hidePanel();
    }

    sendMessage(message) {
        this.state.currentChatMessage = message;
        this.sendChatMessage();
    }

    destroy() {
        this.assistantBtn.remove();
        this.panel.remove();
    }
}

// Автоматическая инициализация
function initAIAssistant(config = {}) {
    if (window.aiAssistant) {
        console.warn('AI Assistant уже инициализирован');
        return window.aiAssistant;
    }

    window.aiAssistant = new AIAssistantWidget(config);
    return window.aiAssistant;
}

// Инициализация при загрузке страницы
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        initAIAssistant();
    });
} else {
    initAIAssistant();
}

// Экспорт для использования в качестве модуля
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { AIAssistantWidget, initAIAssistant };
}