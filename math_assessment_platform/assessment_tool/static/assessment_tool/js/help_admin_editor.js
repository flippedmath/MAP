(function () {
    function initEditor(root) {
        if (!root || root._helpEditorReady) return;
        if (typeof Quill === 'undefined') return;
        root._helpEditorReady = true;

        var hidden = root.querySelector('[name="content"]');
        var editorEl = root.querySelector('.help-quill-editor');
        if (!hidden || !editorEl) return;

        var quill = new Quill(editorEl, {
            theme: 'snow',
            placeholder: 'Write Q&A content… Paste a public YouTube link to embed it.',
            modules: {
                toolbar: [
                    ['bold', 'italic', 'underline'],
                    [{ list: 'ordered' }, { list: 'bullet' }],
                    ['link'],
                    ['clean']
                ]
            }
        });

        var initial = hidden.value || '';
        var format = (root.getAttribute('data-content-format') || 'html').toLowerCase();
        if (initial.trim()) {
            if (format === 'plain' && initial.indexOf('<') === -1) {
                quill.setText(initial);
            } else {
                quill.clipboard.dangerouslyPasteHTML(0, initial);
            }
        }

        var form = root.closest('form');
        if (form) {
            form.addEventListener('submit', function (e) {
                var html = quill.root.innerHTML || '';
                var text = (quill.getText() || '').replace(/\u00a0/g, ' ').trim();
                if (!text) {
                    e.preventDefault();
                    alert('Content is required.');
                    quill.focus();
                    return;
                }
                hidden.value = html;
            });
        }
    }

    document.querySelectorAll('.help-content-editor').forEach(initEditor);
})();
