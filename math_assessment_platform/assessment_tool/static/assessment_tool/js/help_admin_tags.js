(function () {
    function normalizeTag(raw) {
        return String(raw || '').replace(/\s+/g, ' ').trim();
    }

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function initTagInput(root) {
        if (!root || root._helpTagInputReady) return;
        root._helpTagInputReady = true;

        var hidden = root.querySelector('input[type="hidden"][name="tags"]');
        var chipsEl = root.querySelector('.help-tag-chips');
        var textInput = root.querySelector('.help-tag-text');
        if (!hidden || !chipsEl || !textInput) return;

        var tags = [];
        var seen = {};

        function syncHidden() {
            hidden.value = tags.join(', ');
        }

        function render() {
            chipsEl.innerHTML = tags.map(function (tag, index) {
                return (
                    '<span class="help-tag help-tag--editable" data-index="' + index + '">' +
                    '<span class="help-tag-label">' + escapeHtml(tag) + '</span>' +
                    '<button type="button" class="help-tag-remove" aria-label="Remove tag ' + escapeHtml(tag) + '">&times;</button>' +
                    '</span>'
                );
            }).join('');
            syncHidden();
        }

        function addTag(raw) {
            var tag = normalizeTag(raw);
            if (!tag) return false;
            var key = tag.toLowerCase();
            if (seen[key]) return false;
            seen[key] = true;
            tags.push(tag);
            return true;
        }

        function commitPending() {
            var value = textInput.value || '';
            if (!value.trim()) {
                textInput.value = '';
                return;
            }
            var parts = value.split(',');
            var changed = false;
            parts.forEach(function (part) {
                if (addTag(part)) changed = true;
            });
            textInput.value = '';
            if (changed) render();
            else syncHidden();
        }

        // Seed from hidden initial value
        String(hidden.value || '').split(',').forEach(function (part) {
            addTag(part);
        });
        render();

        textInput.addEventListener('keydown', function (e) {
            if (e.key === ',') {
                e.preventDefault();
                commitPending();
                return;
            }
            if (e.key === 'Enter') {
                e.preventDefault();
                commitPending();
                return;
            }
            if (e.key === 'Backspace' && !textInput.value && tags.length) {
                var removed = tags.pop();
                delete seen[removed.toLowerCase()];
                render();
            }
        });

        textInput.addEventListener('input', function () {
            if (textInput.value.indexOf(',') === -1) return;
            commitPending();
        });

        textInput.addEventListener('blur', function () {
            commitPending();
        });

        chipsEl.addEventListener('click', function (e) {
            var btn = e.target.closest('.help-tag-remove');
            if (!btn) return;
            var chip = btn.closest('.help-tag--editable');
            if (!chip) return;
            var index = parseInt(chip.getAttribute('data-index'), 10);
            if (isNaN(index) || index < 0 || index >= tags.length) return;
            var removed = tags.splice(index, 1)[0];
            delete seen[removed.toLowerCase()];
            render();
            textInput.focus();
        });

        root.addEventListener('click', function (e) {
            if (e.target.closest('.help-tag-remove')) return;
            textInput.focus();
        });
    }

    document.querySelectorAll('.help-tag-input').forEach(initTagInput);
})();
