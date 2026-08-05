(function () {
    var root = document.getElementById('help-admin-list');
    if (!root) return;

    var searchUrl = root.getAttribute('data-search-url');
    var input = document.getElementById('help-admin-search-input');
    var statusEl = document.getElementById('help-admin-status');
    var activeTagEl = document.getElementById('help-admin-active-tag');
    var tbody = document.getElementById('help-admin-tbody');
    var emptyEl = document.getElementById('help-admin-empty');
    var tableWrap = document.getElementById('help-admin-table-wrap');
    var paginationEl = document.getElementById('help-admin-pagination');
    var pageInfoEl = document.getElementById('help-admin-page-info');
    var prevBtn = document.getElementById('help-admin-prev');
    var nextBtn = document.getElementById('help-admin-next');

    var PAGE_SIZE = 20;
    var primaryResults = [];
    var contentResults = [];
    var page = 1;
    var debounceTimer = null;
    var requestSeq = 0;
    var controllers = [];
    var csrfToken = root.getAttribute('data-csrf') || '';
    var deleteOverlay = document.getElementById('help-admin-delete-overlay');
    var deleteTitleText = document.getElementById('help-admin-delete-title-text');
    var deleteCancelBtn = document.getElementById('help-admin-delete-cancel');
    var deleteConfirmBtn = document.getElementById('help-admin-delete-confirm');
    var pendingDelete = null;
    var deleteInFlight = false;

    function abortAll() {
        controllers.forEach(function (c) {
            try { c.abort(); } catch (e) {}
        });
        controllers = [];
    }

    function fetchJson(url) {
        var controller = new AbortController();
        controllers.push(controller);
        return fetch(url, {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' },
            signal: controller.signal,
        }).then(function (res) {
            if (!res.ok) throw new Error('Search failed');
            return res.json();
        });
    }

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function mergedResults() {
        return primaryResults.concat(contentResults);
    }

    function setStatus(text) {
        statusEl.textContent = text || '';
    }

    function setActiveTagChip(tag) {
        if (!tag) {
            activeTagEl.hidden = true;
            activeTagEl.innerHTML = '';
            root.setAttribute('data-active-tag', '');
            return;
        }
        root.setAttribute('data-active-tag', tag);
        activeTagEl.hidden = false;
        activeTagEl.innerHTML =
            'Tag: ' + escapeHtml(tag) +
            ' <a href="#" id="help-admin-clear-tag">Clear</a>';
    }

    function sortByViews(list) {
        return list.slice().sort(function (a, b) {
            var dv = (b.view_count || 0) - (a.view_count || 0);
            if (dv !== 0) return dv;
            return (a.id || 0) - (b.id || 0);
        });
    }

    function mergeUnique(existing, incoming) {
        var seen = {};
        existing.forEach(function (r) { seen[r.id] = true; });
        var out = existing.slice();
        incoming.forEach(function (r) {
            if (!seen[r.id]) {
                seen[r.id] = true;
                out.push(r);
            }
        });
        return out;
    }

    function renderTagList(item) {
        var activeTag = root.getAttribute('data-active-tag') || '';
        var tags;
        if (activeTag) {
            tags = item.tags || [];
        } else if (item.matched_tags && item.matched_tags.length) {
            tags = item.matched_tags;
        } else {
            tags = item.tags || [];
        }
        if (!tags.length) return '—';
        return tags.map(function (t) {
            var cls = 'help-admin-tag';
            if (activeTag && t.toLowerCase() === activeTag.toLowerCase()) cls += ' is-active';
            return (
                '<a class="' + cls + '" href="#" data-tag="' + escapeHtml(t) + '">' +
                escapeHtml(t) + '</a>'
            );
        }).join(' ');
    }

    function render() {
        var all = mergedResults();
        var total = all.length;
        var totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE) || 1);
        if (page > totalPages) page = totalPages;
        if (page < 1) page = 1;
        var start = (page - 1) * PAGE_SIZE;
        var slice = all.slice(start, start + PAGE_SIZE);

        if (!total) {
            tableWrap.hidden = true;
            emptyEl.hidden = false;
            emptyEl.textContent = 'No matching Q&A articles.';
            paginationEl.hidden = true;
            return;
        }

        emptyEl.hidden = true;
        tableWrap.hidden = false;
        tbody.innerHTML = slice.map(function (item) {
            var preview = item.content_preview
                ? '<div class="help-admin-preview">' + escapeHtml(item.content_preview) +
                  (item.content_preview.length >= 160 ? '…' : '') + '</div>'
                : '';
            return (
                '<tr>' +
                '<td><strong>' + escapeHtml(item.title) + '</strong>' + preview + '</td>' +
                '<td>' + escapeHtml(item.restriction_label || 'Public') + '</td>' +
                '<td>' + renderTagList(item) + '</td>' +
                '<td>' + escapeHtml(String(item.view_count || 0)) + '</td>' +
                '<td style="white-space:nowrap;">' + escapeHtml(item.modification_date || '—') + '</td>' +
                '<td style="white-space:nowrap;">' +
                '<a href="' + escapeHtml(item.edit_url) + '">Edit</a> · ' +
                '<a href="' + escapeHtml(item.detail_url) + '">View</a> · ' +
                '<button type="button" class="help-admin-delete-link" data-delete-url="' +
                escapeHtml(item.delete_url || '') +
                '" data-delete-title="' + escapeHtml(item.title || '') +
                '" data-delete-id="' + escapeHtml(String(item.id || '')) +
                '">Delete</button>' +
                '</td>' +
                '</tr>'
            );
        }).join('');

        paginationEl.hidden = false;
        if (total > PAGE_SIZE) {
            pageInfoEl.textContent = 'Page ' + page + ' of ' + totalPages + ' (' + total + ' results)';
            prevBtn.disabled = page <= 1;
            nextBtn.disabled = page >= totalPages;
        } else {
            pageInfoEl.textContent = total + (total === 1 ? ' result' : ' results');
            prevBtn.disabled = true;
            nextBtn.disabled = true;
        }
    }

    function runBrowse() {
        var seq = ++requestSeq;
        abortAll();
        setActiveTagChip('');
        setStatus('Loading…');
        primaryResults = [];
        contentResults = [];
        page = 1;
        fetchJson(searchUrl)
            .then(function (data) {
                if (seq !== requestSeq) return;
                primaryResults = data.results || [];
                contentResults = [];
                setStatus('');
                render();
            })
            .catch(function (err) {
                if (err.name === 'AbortError') return;
                if (seq !== requestSeq) return;
                setStatus('Unable to load articles.');
            });
    }

    function runTag(tag) {
        var seq = ++requestSeq;
        abortAll();
        setActiveTagChip(tag);
        input.value = '';
        setStatus('Loading tag…');
        primaryResults = [];
        contentResults = [];
        page = 1;
        fetchJson(searchUrl + '?tag=' + encodeURIComponent(tag))
            .then(function (data) {
                if (seq !== requestSeq) return;
                primaryResults = sortByViews(data.results || []);
                contentResults = [];
                setStatus(primaryResults.length ? '' : 'No articles with this tag.');
                render();
            })
            .catch(function (err) {
                if (err.name === 'AbortError') return;
                if (seq !== requestSeq) return;
                setStatus('Unable to load tag results.');
            });
    }

    function runSearch(q) {
        var seq = ++requestSeq;
        abortAll();
        setActiveTagChip('');
        primaryResults = [];
        contentResults = [];
        page = 1;
        setStatus('Searching tags…');
        var exclude = [];

        fetchJson(searchUrl + '?q=' + encodeURIComponent(q) + '&stage=tags')
            .then(function (tagData) {
                if (seq !== requestSeq) return null;
                primaryResults = sortByViews(tagData.results || []);
                exclude = primaryResults.map(function (r) { return r.id; });
                render();
                setStatus('Searching titles…');
                return fetchJson(
                    searchUrl +
                    '?q=' + encodeURIComponent(q) +
                    '&stage=titles&exclude_ids=' + encodeURIComponent(exclude.join(','))
                );
            })
            .then(function (titleData) {
                if (!titleData || seq !== requestSeq) return null;
                primaryResults = sortByViews(
                    mergeUnique(primaryResults, titleData.results || [])
                );
                exclude = primaryResults.map(function (r) { return r.id; });
                render();
                setStatus('Searching content…');
                return fetchJson(
                    searchUrl +
                    '?q=' + encodeURIComponent(q) +
                    '&stage=content&exclude_ids=' + encodeURIComponent(exclude.join(','))
                );
            })
            .then(function (contentData) {
                if (!contentData || seq !== requestSeq) return;
                contentResults = sortByViews(contentData.results || []);
                setStatus('');
                render();
            })
            .catch(function (err) {
                if (err.name === 'AbortError') return;
                if (seq !== requestSeq) return;
                setStatus('Search failed. Please try again.');
            });
    }

    function onQueryChange() {
        var q = (input.value || '').trim();
        var activeTag = root.getAttribute('data-active-tag') || '';
        if (!q && !activeTag) {
            runBrowse();
            return;
        }
        if (!q && activeTag) {
            runTag(activeTag);
            return;
        }
        runSearch(q);
    }

    input.addEventListener('input', function () {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(onQueryChange, 280);
    });

    prevBtn.addEventListener('click', function () {
        if (page > 1) {
            page -= 1;
            render();
        }
    });
    nextBtn.addEventListener('click', function () {
        var totalPages = Math.max(1, Math.ceil(mergedResults().length / PAGE_SIZE) || 1);
        if (page < totalPages) {
            page += 1;
            render();
        }
    });

    activeTagEl.addEventListener('click', function (e) {
        if (e.target && e.target.id === 'help-admin-clear-tag') {
            e.preventDefault();
            runBrowse();
        }
    });

    function closeDeleteOverlay() {
        if (!deleteOverlay) return;
        pendingDelete = null;
        deleteInFlight = false;
        if (deleteConfirmBtn) {
            deleteConfirmBtn.disabled = false;
            deleteConfirmBtn.textContent = 'Delete';
        }
        deleteOverlay.hidden = true;
        deleteOverlay.setAttribute('aria-hidden', 'true');
    }

    function openDeleteOverlay(item) {
        if (!deleteOverlay || !item || !item.delete_url) return;
        pendingDelete = item;
        if (deleteTitleText) {
            deleteTitleText.textContent = item.title || 'This article';
        }
        deleteOverlay.hidden = false;
        deleteOverlay.setAttribute('aria-hidden', 'false');
        if (deleteConfirmBtn) deleteConfirmBtn.focus();
    }

    function removeDeletedFromResults(id) {
        var numId = Number(id);
        primaryResults = primaryResults.filter(function (r) { return Number(r.id) !== numId; });
        contentResults = contentResults.filter(function (r) { return Number(r.id) !== numId; });
        render();
    }

    function confirmDelete() {
        if (!pendingDelete || !pendingDelete.delete_url || deleteInFlight) return;
        deleteInFlight = true;
        if (deleteConfirmBtn) {
            deleteConfirmBtn.disabled = true;
            deleteConfirmBtn.textContent = 'Deleting…';
        }
        var deleteUrl = pendingDelete.delete_url;
        var deleteId = pendingDelete.id;
        fetch(deleteUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Accept': 'application/json',
                'X-CSRFToken': csrfToken,
            },
        })
            .then(function (res) {
                if (!res.ok) throw new Error('Delete failed');
                return res.json();
            })
            .then(function () {
                removeDeletedFromResults(deleteId);
                closeDeleteOverlay();
                setStatus('Article deleted.');
            })
            .catch(function () {
                deleteInFlight = false;
                if (deleteConfirmBtn) {
                    deleteConfirmBtn.disabled = false;
                    deleteConfirmBtn.textContent = 'Delete';
                }
                setStatus('Unable to delete article.');
            });
    }

    tbody.addEventListener('click', function (e) {
        var deleteBtn = e.target.closest('[data-delete-url]');
        if (deleteBtn) {
            e.preventDefault();
            openDeleteOverlay({
                id: deleteBtn.getAttribute('data-delete-id'),
                title: deleteBtn.getAttribute('data-delete-title') || '',
                delete_url: deleteBtn.getAttribute('data-delete-url') || '',
            });
            return;
        }
        var link = e.target.closest('a[data-tag]');
        if (!link) return;
        e.preventDefault();
        runTag(link.getAttribute('data-tag') || '');
    });

    if (deleteCancelBtn) {
        deleteCancelBtn.addEventListener('click', closeDeleteOverlay);
    }
    if (deleteConfirmBtn) {
        deleteConfirmBtn.addEventListener('click', confirmDelete);
    }
    if (deleteOverlay) {
        deleteOverlay.addEventListener('click', function (e) {
            if (e.target === deleteOverlay) closeDeleteOverlay();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && deleteOverlay && !deleteOverlay.hidden) {
                closeDeleteOverlay();
            }
        });
    }

    runBrowse();
})();
