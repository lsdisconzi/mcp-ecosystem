// Global State Variables
let currentApiUrl = '';
let availableModels = [];
let availableAssistants = [];
let availableFiles = [];
let selectedAssistant = null;
let allTools = [];
let availableTools = [];
let currentThreadId = null;
let collections = [];
let knowledgeEventsBound = false;
let vectorEventsBound = false;
let assistantEventsBound = false;
let fileEventsBound = false;
let toolEventsBound = false;
let playgroundEventsBound = false;

// Shared Utility Functions
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.remove();
    }, 5000);
}

function createModal(title, content, buttons = [], width = '500px') {
    const existingRuntimeModals = document.querySelectorAll('.modal.runtime-modal');
    existingRuntimeModals.forEach(modal => modal.remove());

    const modal = document.createElement('div');
    modal.className = 'modal runtime-modal';

    const dismissModal = () => {
        document.removeEventListener('keydown', escHandler);
        modal.remove();
    };

    // Close on backdrop click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            dismissModal();
        }
    });

    const modalContent = document.createElement('div');
    modalContent.className = 'modal-content';
    modalContent.style.cssText = `width: min(${width}, 90vw);`;

    modalContent.innerHTML = `
        <div class="modal-header">
            <h2>${title}</h2>
            <button class="modal-close-btn" title="Close">&#x2715;</button>
        </div>
        <div class="modal-body">${content}</div>
        <div class="modal-footer">
            ${buttons.map(btn => `<button class="btn ${btn.class}">${btn.text}</button>`).join('')}
        </div>
    `;

    modal.appendChild(modalContent);
    document.body.appendChild(modal);

    // Wire close button
    modalContent.querySelector('.modal-close-btn').onclick = dismissModal;

    // Wire footer buttons
    const buttonElements = modalContent.querySelectorAll('.modal-footer .btn');
    buttons.forEach((btn, index) => {
        if (buttonElements[index] && btn.onclick) {
            buttonElements[index].onclick = btn.onclick;
        }
    });

    // Close on Escape
    const escHandler = (e) => {
        if (e.key === 'Escape') {
            dismissModal();
        }
    };
    document.addEventListener('keydown', escHandler);

    return modal;
}

function closeModal() {
    const runtimeModals = document.querySelectorAll('.modal.runtime-modal');
    if (!runtimeModals.length) return;

    runtimeModals[runtimeModals.length - 1].remove();
}

function updateServerInfo() {
    const apiUrlElement = document.getElementById('api-url');
    const serverTimeElement = document.getElementById('server-time');
    if (apiUrlElement) apiUrlElement.textContent = currentApiUrl;
    if (serverTimeElement) serverTimeElement.textContent = new Date().toLocaleString();
}