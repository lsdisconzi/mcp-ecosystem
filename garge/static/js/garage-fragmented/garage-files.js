document.addEventListener('DOMContentLoaded', setupFileSection);

// === FILE MANAGEMENT FUNCTIONS ===
function setupFileSection() {
    if (fileEventsBound) return;
    fileEventsBound = true;

    document.getElementById('upload-file-btn')?.addEventListener('click', openFilePicker);
    document.getElementById('refresh-files-btn')?.addEventListener('click', loadFiles);
    document.getElementById('confirm-upload-btn')?.addEventListener('click', () => {
        document.getElementById('upload-file-modal')?.classList.add('hidden');
    });

    document.getElementById('confirm-attach-btn')?.addEventListener('click', confirmAttachAssistant);
    document.querySelectorAll('#attach-assistant-modal .close-modal').forEach(btn =>
        btn.addEventListener('click', () => toggleAttachAssistantModal(false))
    );

    document.querySelector('[data-section="files-section"]')?.addEventListener('click', () => {
        loadFiles();
    });
}

function openFilePicker() {
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.style.display = 'none';
    input.addEventListener('change', handleFileUpload);
    document.body.appendChild(input);
    input.click();
}

async function handleFileUpload(event) {
    const files = event.target.files;
    if (!files || files.length === 0) {
        event.target.remove();
        return;
    }

    for (const file of files) {
        await uploadFile(file);
    }

    event.target.remove();
    await loadFiles();
}

async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('purpose', 'assistants');

    try {
        showNotification(`📤 Uploading ${file.name}...`, 'info');

        const response = await fetch('/v1/files', {
            method: 'POST',
            body: formData
        });

        const payload = await response.json().catch(() => null);

        if (!response.ok) {
            throw new Error(payload?.detail || 'Upload failed');
        }

        if (payload?.id) {
            availableFiles.push(payload);
        }

        showNotification(`✅ ${file.name} uploaded successfully!`, 'success');
    } catch (error) {
        showNotification(`❌ Failed to upload ${file.name}: ${error.message}`, 'error');
    }
}

async function downloadFile(fileId, filename) {
    try {
        const response = await fetch(`/v1/files/${fileId}/content`);

        if (!response.ok) {
            if (response.status === 404) {
                throw new Error('File not found on server');
            }
            throw new Error('Download failed');
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename || `file_${fileId}`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        showNotification(`✅ ${filename} downloaded successfully!`, 'success');
    } catch (error) {
        showNotification(`❌ Failed to download ${filename}: ${error.message}`, 'error');
        if (error.message.includes('not found')) {
            loadFiles();
        }
    }
}

async function deleteFile(fileId) {
    const file = availableFiles.find(f => f.id === fileId);
    const filename = file ? file.filename : 'this file';

    if (!confirm(`Are you sure you want to delete "${filename}"? This action cannot be undone.`)) {
        return;
    }

    try {
        const response = await fetch(`/v1/files/${fileId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            if (response.status === 404) {
                showNotification('File already deleted or not found.', 'warning');
                await loadFiles();
                return;
            }
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Failed to delete file');
        }

        availableFiles = availableFiles.filter(f => f.id !== fileId);
        showNotification('✅ File deleted successfully!', 'success');
        await loadFiles();
    } catch (error) {
        showNotification('❌ Error deleting file: ' + error.message, 'error');
    }
}

async function loadFiles() {
    const filesList = document.getElementById('files-list');
    if (!filesList) return;

    filesList.innerHTML = '<div style="text-align: center; padding: 20px; color: var(--gray-400);">Loading files...</div>';

    try {
        const response = await fetch('/v1/files');
        const data = await response.json();
        let files = [];

        if (Array.isArray(data?.data)) {
            files = data.data;
        } else if (Array.isArray(data)) {
            files = data;
        }

        availableFiles = files;

        if (!files.length) {
            filesList.innerHTML = `
                <div style="text-align: center; padding: 40px; background: var(--gray-100); border-radius: 8px;">
                    <div style="font-size: 48px; margin-bottom: 16px; color: var(--gray-400);">📁</div>
                    <h3>No Files Uploaded</h3>
                    <p style="color: var(--gray-400); margin-bottom: 20px;">Upload files to use with your assistants</p>
                    <button class="btn btn-primary" onclick="openFilePicker()">
                        <i class="fas fa-upload"></i> Upload First File
                    </button>
                </div>
            `;
            return;
        }

        filesList.innerHTML = '';
        files.forEach(file => {
            const fileCard = document.createElement('div');
            fileCard.className = 'model-item';
            fileCard.addEventListener('click', () => openFilePreview(file));
            fileCard.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <div class="model-name">${file.filename || file.id}</div>
                        <div class="model-meta">
                            <span>Size: ${file.bytes ? (file.bytes / 1024).toFixed(1) + ' KB' : 'Unknown'}</span>
                            <span>Type: ${file.purpose || 'Unknown'}</span>
                        </div>
                    </div>
                    <div class="assistant-actions">
                        <button class="action-btn attach" title="Attach to assistant">
                            <i class="fas fa-paperclip"></i>
                        </button>
                        <button class="action-btn download" title="Download file">
                            <i class="fas fa-download"></i>
                        </button>
                        <button class="action-btn delete" title="Delete file">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
            `;

            fileCard.querySelector('.attach').addEventListener('click', (event) => {
                event.stopPropagation();
                showAttachAssistantModal(file);
            });
            fileCard.querySelector('.download').addEventListener('click', (event) => {
                event.stopPropagation();
                downloadFile(file.id, file.filename);
            });
            fileCard.querySelector('.delete').addEventListener('click', (event) => {
                event.stopPropagation();
                deleteFile(file.id);
            });

            filesList.appendChild(fileCard);
        });
    } catch (error) {
        filesList.innerHTML = `
            <div style="text-align: center; padding: 40px; background: var(--gray-100); border-radius: 8px; border: 1px solid var(--danger);">
                <h3 style="color: var(--danger);">Failed to Load Files</h3>
                <p style="color: var(--gray-400);">Error: ${error.message}</p>
                <button class="btn btn-secondary" onclick="loadFiles()">
                    <i class="fas a-sync-alt"></i> Try Again
                </button>
            </div>
        `;
    }
}

async function openFilePreview(file) {
    const modal = document.getElementById('file-preview-modal');
    const title = document.getElementById('preview-filename');
    const content = document.getElementById('file-preview-content');

    if (!modal || !title || !content) return;

    title.textContent = file.filename || file.id;
    content.textContent = 'Loading preview...';
    modal.classList.remove('hidden');

    try {
        const response = await fetch(`/v1/files/${file.id}/content`);
        if (!response.ok) {
            throw new Error('Unable to load file preview');
        }
        const text = await response.text();
        content.textContent = text;
    } catch (error) {
        content.textContent = `Preview unavailable: ${error.message}`;
    }
}

function showAttachAssistantModal(file) {
    const modal = document.getElementById('attach-assistant-modal');
    const hiddenField = document.getElementById('attach-file-id');
    const container = modal?.querySelector('.form-group');

    if (!modal || !hiddenField || !container) return;

    hiddenField.value = file.id;

    const selectId = 'attach-assistant-select';
    let selector = document.getElementById(selectId);

    if (!selector) {
        selector = document.createElement('select');
        selector.id = selectId;
        selector.style.width = '100%';
        container.innerHTML = '';
        container.appendChild(selector);
    } else {
        selector.innerHTML = '';
    }

    if (!availableAssistants.length) {
        loadAssistants().catch(() => {});
    }

    selector.innerHTML = '<option value="">Select an assistant...</option>';
    availableAssistants.forEach(assistant => {
        const option = document.createElement('option');
        option.value = assistant.id;
        option.textContent = assistant.name || assistant.id;
        selector.appendChild(option);
    });

    modal.classList.remove('hidden');
}

function toggleAttachAssistantModal(show) {
    const modal = document.getElementById('attach-assistant-modal');
    if (!modal) return;
    if (show) {
        modal.classList.remove('hidden');
    } else {
        modal.classList.add('hidden');
    }
}

async function confirmAttachAssistant() {
    const fileId = document.getElementById('attach-file-id')?.value;
    const selector = document.getElementById('attach-assistant-select');

    if (!fileId || !selector || !selector.value) {
        showNotification('Select an assistant before attaching the file.', 'error');
        return;
    }

    try {
        const response = await fetch(`/v1/assistants/${selector.value}/files`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_id: fileId })
        });

        const payload = await response.json().catch(() => null);
        if (!response.ok) {
            throw new Error(payload?.detail || 'Failed to attach file');
        }

        showNotification('File attached to assistant successfully.', 'success');
        toggleAttachAssistantModal(false);
        await loadAssistants();
    } catch (error) {
        showNotification(`Failed to attach file: ${error.message}`, 'error');
    }
}