// Knowledge helpers used by the Assist Chat modal.
// Main knowledge tab wiring lives in garage-main.js.
(function () {
    function getFileIcon(filename = '') {
        const ext = String(filename).split('.').pop().toLowerCase();
        const icons = {
            pdf: 'fa-file-pdf',
            doc: 'fa-file-word',
            docx: 'fa-file-word',
            xls: 'fa-file-excel',
            xlsx: 'fa-file-excel',
            csv: 'fa-file-excel',
            ppt: 'fa-file-powerpoint',
            pptx: 'fa-file-powerpoint',
            json: 'fa-file-code',
            js: 'fa-file-code',
            py: 'fa-file-code',
            java: 'fa-file-code',
            cpp: 'fa-file-code',
            c: 'fa-file-code',
            ts: 'fa-file-code',
            md: 'fa-file-lines',
            txt: 'fa-file-lines',
            png: 'fa-file-image',
            jpg: 'fa-file-image',
            jpeg: 'fa-file-image',
            gif: 'fa-file-image',
            bmp: 'fa-file-image',
            mp3: 'fa-file-audio',
            wav: 'fa-file-audio',
            ogg: 'fa-file-audio',
            mp4: 'fa-file-video',
            avi: 'fa-file-video',
            mov: 'fa-file-video'
        };
        return icons[ext] || 'fa-file-lines';
    }

    async function loadKnowledgeFiles() {
        const list = document.getElementById('knowledge-files-list');
        if (!list) return;

        if (!selectedAssistant || !selectedAssistant.id) {
            list.innerHTML = '<em>No assistant selected.</em>';
            return;
        }

        list.innerHTML = '<div class="loading">Loading files...</div>';

        try {
            const resp = await fetch(`/v1/assistants/${selectedAssistant.id}/files`);
            const payload = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                throw new Error(payload.detail || payload.error || 'Failed to load assistant files');
            }

            const files = Array.isArray(payload)
                ? payload
                : (Array.isArray(payload.data) ? payload.data : []);

            const metadataFiles = (typeof availableFiles !== 'undefined' && Array.isArray(availableFiles))
                ? availableFiles
                : [];

            const normalizedFiles = files.map((entry, index) => {
                if (typeof entry === 'string') {
                    const meta = metadataFiles.find(f => f?.id === entry);
                    return {
                        id: entry,
                        label: meta?.filename || meta?.name || entry
                    };
                }

                if (entry && typeof entry === 'object') {
                    const nested = (entry.file && typeof entry.file === 'object') ? entry.file : null;
                    const entryId = entry.id || entry.file_id || entry.fileId || nested?.id || null;
                    const meta = entryId ? metadataFiles.find(f => f?.id === entryId) : null;
                    const label =
                        entry.filename ||
                        entry.name ||
                        nested?.filename ||
                        nested?.name ||
                        meta?.filename ||
                        meta?.name ||
                        entryId ||
                        `File ${index + 1}`;

                    return {
                        id: entryId,
                        label
                    };
                }

                return {
                    id: null,
                    label: `File ${index + 1}`
                };
            });

            if (!normalizedFiles.length) {
                list.innerHTML = '<em>No knowledge files found.</em>';
                return;
            }

            list.innerHTML = normalizedFiles.map((file, index) => {
                const fileName = file.label;
                const canAttach = Boolean(file.id);
                const isAlreadyAttached = canAttach
                    && typeof window.isKnowledgeFileAttachedInModal === 'function'
                    && window.isKnowledgeFileAttachedInModal(file.id);
                const actionLabel = isAlreadyAttached ? 'View' : 'Attach';
                const actionIcon = isAlreadyAttached ? 'fa-eye' : 'fa-paperclip';
                const disabledState = canAttach ? '' : 'disabled title="File id unavailable"';
                return `
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px;">
                        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                            <i class="fas ${getFileIcon(fileName)}"></i> ${fileName}
                        </span>
                        <button class="btn btn-sm btn-secondary" id="attach-knowledge-file-btn-${index}" ${disabledState}>
                            <i class="fas ${actionIcon}"></i> ${actionLabel}
                        </button>
                    </div>
                `;
            }).join('');

            normalizedFiles.forEach((file, index) => {
                const button = document.getElementById(`attach-knowledge-file-btn-${index}`);
                if (!button) return;
                button.addEventListener('click', () => {
                    if (!file.id) {
                        showNotification('Cannot attach file: missing file identifier.', 'error');
                        return;
                    }

                    const isAlreadyAttached = typeof window.isKnowledgeFileAttachedInModal === 'function'
                        && window.isKnowledgeFileAttachedInModal(file.id);

                    if (isAlreadyAttached) {
                        if (typeof window.viewKnowledgeFileInModal !== 'function') {
                            showNotification('Preview helper is not available.', 'error');
                            return;
                        }
                        window.viewKnowledgeFileInModal(file.id, file.label);
                        return;
                    }

                    if (typeof window.attachKnowledgeFileInModal !== 'function') {
                        showNotification('Chat attachment helper is not available.', 'error');
                        return;
                    }

                    window.attachKnowledgeFileInModal(file.id, file.label);
                    loadKnowledgeFiles();
                });
            });
        } catch (error) {
            list.innerHTML = `<div class="error">${error.message}</div>`;
        }
    }

    function toggleKnowledgeFiles() {
        const list = document.getElementById('knowledge-files-list');
        if (!list) return;

        const shouldShow = list.style.display === 'none' || !list.style.display;
        list.style.display = shouldShow ? 'block' : 'none';
        if (shouldShow) {
            loadKnowledgeFiles();
        }
    }

    window.getFileIcon = getFileIcon;
    window.loadKnowledgeFiles = loadKnowledgeFiles;
    window.toggleKnowledgeFiles = toggleKnowledgeFiles;
})();
