(function () {
    var root = document.getElementById('help-page');
    if (!root) return;

    var searchUrl = root.getAttribute('data-search-url');
    var input = document.getElementById('help-search-input');
    var resultsEl = document.getElementById('help-results');
    var statusEl = document.getElementById('help-status');
    var paginationEl = document.getElementById('help-pagination');
    var pageInfoEl = document.getElementById('help-page-info');
    var prevBtn = document.getElementById('help-prev');
    var nextBtn = document.getElementById('help-next');
    var activeTagEl = document.getElementById('help-active-tag');

    var PAGE_SIZE = 10;
    var primaryResults = []; // tags + titles (or browse/tag mode)
    var contentResults = [];
    var page = 1;
    var debounceTimer = null;
    var requestSeq = 0;
    var controllers = [];

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

    function renderTagChip(name, opts) {
        opts = opts || {};
        var cls = 'help-tag';
        if (opts.matched) cls += ' is-matched';
        if (opts.active) cls += ' is-active';
        var href = '/qa/?tag=' + encodeURIComponent(name);
        return '<a class="' + cls + '" href="' + href + '">' + escapeHtml(name) + '</a>';
    }

    function render() {
        var all = mergedResults();
        var total = all.length;
        var totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE) || 1);
        if (page > totalPages) page = totalPages;
        if (page < 1) page = 1;
        var start = (page - 1) * PAGE_SIZE;
        var slice = all.slice(start, start + PAGE_SIZE);

        if (!slice.length) {
            resultsEl.innerHTML = '<li class="help-empty" style="border:none;padding:0;">No matching Q&A articles.</li>';
        } else {
            resultsEl.innerHTML = slice.map(function (item) {
                var tagsToShow = item.matched_tags && item.matched_tags.length
                    ? item.matched_tags
                    : (item.tags || []);
                // Prefer matched tags; if active tag mode show all tags with active highlighted
                var activeTag = root.getAttribute('data-active-tag') || '';
                var chips;
                if (activeTag) {
                    chips = (item.tags || []).map(function (t) {
                        return renderTagChip(t, { active: t.toLowerCase() === activeTag.toLowerCase() });
                    }).join('');
                } else {
                    chips = tagsToShow.map(function (t) {
                        return renderTagChip(t, { matched: true });
                    }).join('');
                }
                var restriction = item.restriction_label || 'Public';
                return (
                    '<li>' +
                    '<div class="help-card-header">' +
                    '<a class="help-title-link" href="' + escapeHtml(item.detail_url) + '">' +
                    escapeHtml(item.title) + '</a>' +
                    '<span class="help-restriction-label">' + escapeHtml(restriction) + '</span>' +
                    '</div>' +
                    (chips ? '<div class="help-tag-list">' + chips + '</div>' : '') +
                    '</li>'
                );
            }).join('');
        }

        if (total > PAGE_SIZE) {
            paginationEl.hidden = false;
            pageInfoEl.textContent = 'Page ' + page + ' of ' + totalPages + ' (' + total + ' results)';
            prevBtn.disabled = page <= 1;
            nextBtn.disabled = page >= totalPages;
        } else {
            paginationEl.hidden = total === 0;
            if (total > 0) {
                paginationEl.hidden = false;
                pageInfoEl.textContent = total + (total === 1 ? ' result' : ' results');
                prevBtn.disabled = true;
                nextBtn.disabled = true;
            }
        }
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
            ' <a href="/qa/" id="help-clear-tag">Clear</a>';
    }

    function updateUrl(params) {
        var url = new URL(window.location.href);
        url.search = '';
        Object.keys(params).forEach(function (k) {
            if (params[k]) url.searchParams.set(k, params[k]);
        });
        window.history.replaceState({}, '', url.pathname + url.search);
    }

    function runBrowse() {
        var seq = ++requestSeq;
        abortAll();
        setActiveTagChip('');
        setStatus('Loading…');
        primaryResults = [];
        contentResults = [];
        page = 1;
        updateUrl({});
        fetchJson(searchUrl)
            .then(function (data) {
                if (seq !== requestSeq) return;
                primaryResults = sortByViews(data.results || []);
                contentResults = [];
                setStatus('');
                render();
            })
            .catch(function (err) {
                if (err.name === 'AbortError') return;
                if (seq !== requestSeq) return;
                setStatus('Unable to load Q&A articles.');
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
        updateUrl({ tag: tag });
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
        updateUrl({ q: q });
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
        if (e.target && e.target.id === 'help-clear-tag') {
            e.preventDefault();
            runBrowse();
        }
    });

    // Initial load from URL / data attributes
    var initialTag = (root.getAttribute('data-initial-tag') || '').trim();
    var initialQ = (root.getAttribute('data-initial-q') || '').trim();
    if (initialTag) {
        runTag(initialTag);
    } else if (initialQ) {
        input.value = initialQ;
        runSearch(initialQ);
    } else {
        runBrowse();
    }
})();
