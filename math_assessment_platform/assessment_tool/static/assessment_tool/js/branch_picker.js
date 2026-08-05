/**
 * Explorer-style branch picker for assessment setup copy flows.
 *
 * window.openBranchPicker({
 *   title, hint, rootFolderId, rootFolderName, contentsUrlTemplate,
 *   selectableTypes: ['problem','cqd'] | ['aqg'],
 *   onSelect(item) -> Promise|void,   // item: {id,name,type}
 * })
 */
(function () {
  'use strict';

  var pathStack = [];
  var selected = null;
  var activeOpts = null;

  function escapeHtml(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function iconForType(type) {
    switch (type) {
      case 'course':
        return 'fa-graduation-cap';
      case 'assessment':
        return 'fa-file-signature';
      case 'aqg':
        return 'fa-list-ol';
      case 'cqd':
        return 'fa-random';
      case 'problem':
        return 'fa-question-circle';
      default:
        return 'fa-folder';
    }
  }

  function ensureDom() {
    var overlay = document.getElementById('branch-picker-overlay');
    if (overlay) return overlay;

    overlay = document.createElement('div');
    overlay.id = 'branch-picker-overlay';
    overlay.className = 'branch-picker-overlay';
    overlay.setAttribute('aria-hidden', 'true');
    overlay.innerHTML =
      '<div class="branch-picker-panel" role="dialog" aria-modal="true" aria-labelledby="branch-picker-title">' +
      '<h3 id="branch-picker-title"></h3>' +
      '<p id="branch-picker-hint" class="branch-picker-hint"></p>' +
      '<div id="branch-picker-crumb" class="branch-picker-crumb"></div>' +
      '<div id="branch-picker-list" class="branch-picker-list"></div>' +
      '<div class="branch-picker-actions">' +
      '<button type="button" id="branch-picker-cancel" class="branch-picker-btn branch-picker-btn-secondary">Cancel</button>' +
      '<button type="button" id="branch-picker-copy" class="branch-picker-btn branch-picker-btn-primary" disabled>Copy here</button>' +
      '</div>' +
      '</div>';
    document.body.appendChild(overlay);

    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) closePicker();
    });
    document.getElementById('branch-picker-cancel').addEventListener('click', closePicker);
    document.getElementById('branch-picker-copy').addEventListener('click', commitSelection);
    return overlay;
  }

  function contentsUrl(folderId) {
    var tmpl = (activeOpts && activeOpts.contentsUrlTemplate) || '/api/branch-picker/{id}/';
    return tmpl.replace('{id}', String(folderId));
  }

  function setCopyEnabled() {
    var btn = document.getElementById('branch-picker-copy');
    if (!btn) return;
    btn.disabled = !selected;
    btn.style.opacity = selected ? '1' : '0.5';
    btn.style.cursor = selected ? 'pointer' : 'not-allowed';
  }

  function renderCrumb() {
    var crumb = document.getElementById('branch-picker-crumb');
    if (!crumb) return;
    crumb.innerHTML = '';
    var label = document.createElement('span');
    label.textContent = 'Current: ';
    label.style.color = '#666';
    crumb.appendChild(label);

    pathStack.forEach(function (seg, idx) {
      if (idx > 0) {
        var sep = document.createElement('span');
        sep.textContent = ' › ';
        sep.style.color = '#94a3b8';
        crumb.appendChild(sep);
      }
      var isLast = idx === pathStack.length - 1;
      if (isLast) {
        var span = document.createElement('span');
        span.textContent = seg.name;
        span.style.fontWeight = '600';
        span.style.color = '#334155';
        crumb.appendChild(span);
      } else {
        var link = document.createElement('button');
        link.type = 'button';
        link.textContent = seg.name;
        link.className = 'branch-picker-crumb-link';
        link.onclick = async function () {
          pathStack = pathStack.slice(0, idx + 1);
          selected = null;
          setCopyEnabled();
          await renderBrowser();
        };
        crumb.appendChild(link);
      }
    });
  }

  async function fetchItems(folderId) {
    var res = await fetch(contentsUrl(folderId), {
      headers: { Accept: 'application/json' },
    });
    var data = await res.json().catch(function () {
      return {};
    });
    if (!res.ok || !data.success) {
      throw new Error((data && data.error) || 'Failed to load folder contents.');
    }
    return data.items || [];
  }

  function isSelectable(type) {
    var allowed = (activeOpts && activeOpts.selectableTypes) || [];
    return allowed.indexOf(type) !== -1;
  }

  async function renderBrowser() {
    var current = pathStack[pathStack.length - 1];
    if (!current) return;
    renderCrumb();

    var list = document.getElementById('branch-picker-list');
    list.innerHTML = '<div class="branch-picker-loading">Loading…</div>';

    var items;
    try {
      items = await fetchItems(current.id);
    } catch (err) {
      list.innerHTML =
        '<div class="branch-picker-empty">' + escapeHtml(err.message || 'Failed to load.') + '</div>';
      return;
    }

    list.innerHTML = '';
    if (!items.length) {
      var empty = document.createElement('div');
      empty.className = 'branch-picker-empty';
      empty.textContent = 'Nothing here.';
      list.appendChild(empty);
      return;
    }

    items.forEach(function (it) {
      var selectable = isSelectable(it.type);
      var navigable = !!it.navigable && it.type !== 'problem';
      var isSelected = selected && selected.id === it.id;
      var row = document.createElement('div');
      row.className =
        'branch-picker-row' +
        (selectable ? ' is-selectable' : '') +
        (isSelected ? ' is-selected' : '') +
        (!selectable && !navigable ? ' is-disabled' : '');

      var left = document.createElement('span');
      left.className = 'branch-picker-row-label';
      left.innerHTML =
        '<i class="fas ' +
        iconForType(it.type) +
        '"></i> ' +
        escapeHtml(it.name);

      var right = document.createElement('span');
      right.className = 'branch-picker-row-actions';

      if (selectable) {
        var pickBtn = document.createElement('button');
        pickBtn.type = 'button';
        pickBtn.className = 'branch-picker-select-btn';
        pickBtn.textContent = isSelected ? 'Selected' : 'Select';
        pickBtn.onclick = function (e) {
          e.stopPropagation();
          selected = { id: it.id, name: it.name, type: it.type };
          setCopyEnabled();
          renderBrowser();
        };
        right.appendChild(pickBtn);
      }

      if (navigable) {
        var openBtn = document.createElement('button');
        openBtn.type = 'button';
        openBtn.className = 'branch-picker-open-btn';
        openBtn.textContent = 'Open';
        openBtn.onclick = async function (e) {
          e.stopPropagation();
          pathStack.push({ id: it.id, name: it.name, type: it.type || 'folder' });
          selected = null;
          setCopyEnabled();
          await renderBrowser();
        };
        right.appendChild(openBtn);
      }

      row.appendChild(left);
      row.appendChild(right);

      if (navigable && !selectable) {
        row.onclick = async function () {
          pathStack.push({ id: it.id, name: it.name, type: it.type || 'folder' });
          selected = null;
          setCopyEnabled();
          await renderBrowser();
        };
      } else if (selectable) {
        row.onclick = function () {
          selected = { id: it.id, name: it.name, type: it.type };
          setCopyEnabled();
          renderBrowser();
        };
      }

      list.appendChild(row);
    });
  }

  function closePicker() {
    var overlay = document.getElementById('branch-picker-overlay');
    if (!overlay) return;
    overlay.classList.remove('is-visible');
    overlay.setAttribute('aria-hidden', 'true');
    pathStack = [];
    selected = null;
    activeOpts = null;
  }

  async function commitSelection() {
    if (!selected || !activeOpts || typeof activeOpts.onSelect !== 'function') return;
    var copyBtn = document.getElementById('branch-picker-copy');
    var cancelBtn = document.getElementById('branch-picker-cancel');
    var item = selected;
    var opts = activeOpts;
    if (copyBtn) {
      copyBtn.disabled = true;
      copyBtn.textContent = 'Copying…';
    }
    if (cancelBtn) cancelBtn.disabled = true;
    try {
      await opts.onSelect(item);
      closePicker();
    } catch (err) {
      if (typeof mapAlert === 'function') {
        await mapAlert({
          title: 'Copy failed',
          message: (err && err.message) || 'Copy failed.',
        });
      } else {
        alert((err && err.message) || 'Copy failed.');
      }
      if (copyBtn) {
        copyBtn.disabled = !selected;
        copyBtn.textContent = 'Copy here';
      }
      if (cancelBtn) cancelBtn.disabled = false;
      setCopyEnabled();
    }
  }

  async function openBranchPicker(opts) {
    opts = opts || {};
    if (!opts.rootFolderId) {
      if (typeof mapAlert === 'function') {
        await mapAlert({
          title: 'Unavailable',
          message: 'Explorer root folder was not found for your account.',
        });
      }
      return;
    }

    activeOpts = opts;
    selected = null;
    pathStack = [
      {
        id: opts.rootFolderId,
        name: opts.rootFolderName || 'Home',
        type: 'folder',
      },
    ];

    var overlay = ensureDom();
    document.getElementById('branch-picker-title').textContent = opts.title || 'Copy from Explorer';
    var hint = document.getElementById('branch-picker-hint');
    if (opts.hint) {
      hint.textContent = opts.hint;
      hint.style.display = '';
    } else {
      hint.textContent = '';
      hint.style.display = 'none';
    }
    document.getElementById('branch-picker-copy').textContent = opts.commitLabel || 'Copy here';
    document.getElementById('branch-picker-cancel').disabled = false;
    setCopyEnabled();
    overlay.classList.add('is-visible');
    overlay.setAttribute('aria-hidden', 'false');
    await renderBrowser();
  }

  window.openBranchPicker = openBranchPicker;
  window.closeBranchPicker = closePicker;
})();
