/* Collaboration / Share / Move / Manage Groups helpers for explorer.html */

/** Session-only: user ids just added to a group while Manage Groups stays open. */
let justAddedGroupMembers = {};

function showMapOverlay({ title, bodyHtml, actions, maxWidth, actionsAlign, actionsHint }) {
  const overlay = document.getElementById('map-overlay');
  const panel = document.getElementById('map-overlay-panel');
  const body = document.getElementById('map-overlay-body');
  document.getElementById('map-overlay-title').textContent = title || '';
  body.innerHTML = bodyHtml || '';
  body.style.maxHeight = 'min(70vh, 560px)';
  body.style.overflowY = 'auto';
  if (panel) panel.style.maxWidth = maxWidth || '520px';
  const act = document.getElementById('map-overlay-actions');
  act.innerHTML = '';
  act.style.justifyContent = actionsAlign || 'flex-end';
  act.style.alignItems = 'center';
  act.style.flexWrap = 'wrap';
  if (actionsHint) {
    const hint = document.createElement('div');
    hint.className = 'map-overlay-actions-hint';
    hint.textContent = actionsHint;
    act.appendChild(hint);
  }
  (actions || []).forEach((a) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = a.label;
    if (a.id) btn.id = a.id;
    btn.className = a.danger
      ? 'map-dialog-btn map-dialog-btn-danger'
      : a.primary
        ? 'map-dialog-btn map-dialog-btn-primary'
        : 'map-dialog-btn map-dialog-btn-secondary';
    btn.disabled = !!a.disabled;
    if (a.disabled) {
      btn.style.opacity = '0.45';
      btn.style.cursor = 'not-allowed';
    }
    btn.onclick = async () => {
      if (btn.disabled) return;
      if (a.onClick) await a.onClick();
    };
    act.appendChild(btn);
  });
  overlay.onclick = (e) => {
    if (e.target === overlay) hideMapOverlay();
  };
  overlay.style.display = 'flex';
}

function hideMapOverlay() {
  const overlay = document.getElementById('map-overlay');
  overlay.style.display = 'none';
  overlay.onclick = null;
  justAddedGroupMembers = {};
  const panel = document.getElementById('map-overlay-panel');
  if (panel) panel.style.maxWidth = '520px';
  const explorer = document.getElementById('finder-explorer');
  if (explorer) explorer.focus({ preventScroll: true });
}

/** Reload the explorer column that contains a branch so shared badges update. */
function refreshExplorerItemColumn(branchId) {
  if (!branchId || typeof loadFolder !== 'function') return;
  const el =
    document.querySelector(`.item[data-branch-id="${branchId}"]`) ||
    document.querySelector(`.item[data-id="${branchId}"]`);
  if (el) {
    const parentId = el.getAttribute('data-parent-id');
    const col = el.closest('.finder-column');
    if (parentId && col) {
      const level = parseInt(col.dataset.level, 10);
      if (!Number.isNaN(level)) loadFolder(parentId, level);
    }
  }
  refreshCollaborationColumnIfOpen();
}

/** If Collaboration is open in the explorer, reload that column so share roots appear. */
function refreshCollaborationColumnIfOpen() {
  if (typeof loadFolder !== 'function') return;
  document.querySelectorAll('.finder-column[data-folder-id]').forEach((col) => {
    const path = col.dataset.folderPath || '';
    if (!path.includes('/Collaboration')) return;
    const folderId = col.dataset.folderId;
    const level = parseInt(col.dataset.level, 10);
    if (folderId && !Number.isNaN(level)) loadFolder(folderId, level);
  });
}

function hideMapDialog() {
  const overlay = document.getElementById('map-dialog-overlay');
  if (!overlay) return;
  overlay.style.display = 'none';
  overlay.onclick = null;
  const explorer = document.getElementById('finder-explorer');
  if (explorer) explorer.focus({ preventScroll: true });
}

function showMapDialog({ title, message, actions }) {
  const overlay = document.getElementById('map-dialog-overlay');
  document.getElementById('map-dialog-title').textContent = title || '';
  document.getElementById('map-dialog-message').textContent = message || '';
  const act = document.getElementById('map-dialog-actions');
  act.innerHTML = '';
  (actions || []).forEach((a) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = a.label;
    btn.className = a.danger
      ? 'map-dialog-btn map-dialog-btn-danger'
      : a.primary
        ? 'map-dialog-btn map-dialog-btn-primary'
        : 'map-dialog-btn map-dialog-btn-secondary';
    btn.onclick = async () => {
      if (a.onClick) await a.onClick();
    };
    act.appendChild(btn);
  });
  overlay.onclick = (e) => {
    if (e.target === overlay) {
      /* backdrop click acts as cancel when a cancel action exists */
      const cancel = (actions || []).find((a) => !a.primary && !a.danger);
      if (cancel && cancel.onClick) cancel.onClick();
    }
  };
  overlay.style.display = 'flex';
}

function mapConfirm({
  title = 'Confirm',
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  danger = false,
} = {}) {
  return new Promise((resolve) => {
    showMapDialog({
      title,
      message,
      actions: [
        {
          label: cancelLabel,
          onClick: () => {
            hideMapDialog();
            resolve(false);
          },
        },
        {
          label: confirmLabel,
          primary: !danger,
          danger,
          onClick: () => {
            hideMapDialog();
            resolve(true);
          },
        },
      ],
    });
  });
}

function mapAlert({ title = 'Notice', message, okLabel = 'OK' } = {}) {
  return new Promise((resolve) => {
    showMapDialog({
      title,
      message,
      actions: [
        {
          label: okLabel,
          primary: true,
          onClick: () => {
            hideMapDialog();
            resolve();
          },
        },
      ],
    });
  });
}

window.mapConfirm = mapConfirm;
window.mapAlert = mapAlert;
window.showMapDialog = showMapDialog;
window.hideMapDialog = hideMapDialog;

function formatPermLabel(perm) {
  if (perm === 'read_only') return 'view-only';
  if (perm === 'owner') return 'owner';
  return perm || '';
}

async function loadBranchPreview(branchId, level) {
  const container = document.getElementById('dynamic-columns');
  container.querySelectorAll('.finder-column').forEach((col) => {
    if (parseInt(col.dataset.level, 10) >= level) col.remove();
  });
  const response = await fetch(`/get-branch-preview/${branchId}/`);
  const html = await response.text();
  const newCol = document.createElement('div');
  newCol.className = 'finder-column preview-column';
  newCol.dataset.level = level;
  newCol.innerHTML = html;
  container.appendChild(newCol);
}

async function handleCopyToWorkspace() {
  const res = await fetch('/collaboration/copy-to-workspace/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
    body: JSON.stringify({ branch_id: currentItem.id }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    await mapAlert({ title: 'Copy failed', message: data.error || 'Copy failed' });
    return;
  }
  await mapAlert({ title: 'Copied', message: `Copied to Workspace as "${data.name}"` });
}

async function handleOpenMode(mode) {
  const type = currentItem.type;
  const linkedId = currentItem.linkedId;
  const targetEl =
    document.querySelector(`.item[data-branch-id="${currentItem.id}"]`) ||
    document.querySelector(`.item[data-id="${currentItem.id}"][data-type="${currentItem.type}"]`);
  const inCollab =
    (currentItem.location || '').includes('/Collaboration/') ||
    !!(
      targetEl &&
      (targetEl.classList.contains('item-collab-owned') ||
        targetEl.classList.contains('item-collab-foreign'))
    );
  if (mode === 'edit' && inCollab) {
    showMapOverlay({
      title: 'Edit shared item?',
      bodyHtml:
        '<p>This item is in Collaboration. Prefer copying it to your Workspace, editing locally, then using <strong>Move to…</strong> back onto the shared folder with the <em>same name</em> to replace the shared copy — otherwise collaborators may see a half-edited version.</p>',
      actions: [
        { label: 'Cancel', onClick: hideMapOverlay },
        {
          label: 'Copy to Workspace',
          primary: true,
          onClick: async () => {
            hideMapOverlay();
            await handleCopyToWorkspace();
          },
        },
        {
          label: 'Continue editing',
          onClick: () => {
            hideMapOverlay();
            navigateOpenMode(mode, type, linkedId);
          },
        },
      ],
    });
    return;
  }
  navigateOpenMode(mode, type, linkedId);
}

function handleGoToCourse() {
  const linkedId = currentItem.linkedId;
  if (!linkedId) return;
  // Clear explorer view-only and open the course with normal (editable) access.
  window.location.href = `/courses/${linkedId}/?mode=edit`;
}

async function navigateOpenMode(mode, type, linkedId) {
  let url = '';
  if (type === 'course' && linkedId) url = `/courses/${linkedId}/?mode=${mode}&from=explorer`;
  else if (type === 'assessment' && linkedId) url = `/assessments/${linkedId}/edit/?mode=${mode}&from=explorer`;
  else if (type === 'problem' && linkedId) {
    try {
      const openFn = await waitForOpenProblemOverlay();
      await openFn(linkedId, { mode, readOnly: mode === 'view' });
    } catch (err) {
      await mapAlert({
        title: 'Open problem',
        message: err.message || 'Problem editor is not available on this page.',
      });
    }
    return;
  }
  if (url) window.location.href = url;
}

function waitForOpenProblemOverlay(timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    if (typeof window.openProblemOverlay === 'function') {
      resolve(window.openProblemOverlay);
      return;
    }
    const started = Date.now();
    const timer = setInterval(() => {
      if (typeof window.openProblemOverlay === 'function') {
        clearInterval(timer);
        resolve(window.openProblemOverlay);
      } else if (Date.now() - started > timeoutMs) {
        clearInterval(timer);
        reject(new Error('Problem overlay failed to load. Refresh the page and try again.'));
      }
    }, 40);
  });
}


function renderShareAclList(acl, { isOwner = false } = {}) {
  const rows = acl || [];
  const hasCollaborators = rows.some((r) => r.permissions !== 'owner');
  let body;
  if (!rows.length) {
    body = '<em style="color:#94a3b8;">Not shared with anyone yet.</em>';
  } else {
    body = rows
      .map((row) => {
        const who = row.user_id
          ? `<strong>${row.username || 'user #' + row.user_id}</strong>`
          : `<strong>Group:</strong> ${row.permission_group_name || 'group #' + row.permission_group_id}`;
        const perm = row.permissions;
        let permControl;
        let removeBtn = '';
        if (perm === 'owner') {
          permControl = `<span style="color:#64748b;font-size:0.85rem;min-width:110px;text-align:right;">owner</span>`;
        } else if (perm === 'edit' || perm === 'read_only') {
          const kind = row.user_id ? 'user' : 'group';
          const idAttr = row.user_id
            ? `data-user-id="${row.user_id}"`
            : `data-pg-id="${row.permission_group_id}"`;
          permControl = `
          <select class="share-acl-perm map-select map-select-sm"
            data-kind="${kind}"
            ${idAttr}
            data-current="${perm}">
            <option value="edit" ${perm === 'edit' ? 'selected' : ''}>Edit</option>
            <option value="read_only" ${perm === 'read_only' ? 'selected' : ''}>View-only</option>
          </select>`;
          removeBtn = `
          <button type="button" class="share-acl-remove"
            data-kind="${kind}"
            ${idAttr}
            title="Remove access"
            style="border:none;background:#fee2e2;color:#b91c1c;border-radius:4px;padding:4px 8px;cursor:pointer;font-size:0.8rem;">
            <i class="fas fa-trash"></i>
          </button>`;
        } else {
          permControl = `<span style="color:#64748b;font-size:0.85rem;min-width:110px;text-align:right;">${formatPermLabel(perm)}</span>`;
        }
        return `<div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid #eef2f7;font-size:0.9rem;">
        <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;">${who}</span>
        <span style="flex-shrink:0;width:118px;display:flex;justify-content:flex-end;">${permControl}</span>
        <span style="flex-shrink:0;width:36px;display:flex;justify-content:center;">${removeBtn}</span>
      </div>`;
      })
      .join('');
  }

  // Only the item owner may stop collaboration for everyone.
  const stopBtn =
    isOwner && hasCollaborators
      ? `<div style="margin-top:12px;padding-top:12px;border-top:2px solid #cbd5e1;">
        <button type="button" id="share-stop-all"
          style="width:100%;padding:8px 10px;border:1px solid #fecaca;background:#fff1f2;color:#9f1239;border-radius:6px;cursor:pointer;font-size:0.85rem;font-weight:600;">
          Remove all access &amp; stop collaboration
        </button>
        <div style="margin-top:6px;font-size:0.75rem;color:#64748b;line-height:1.35;">
          Removes every collaborator and group from this item.
        </div>
      </div>`
      : '';

  return body + stopBtn;
}

function bindShareAclControls(aclRef, options = {}) {
  const list = document.getElementById('share-acl-list');
  if (!list) return;

  list.querySelectorAll('select.share-acl-perm').forEach((sel) => {
    sel.onchange = async () => {
      const previous = sel.dataset.current;
      const next = sel.value;
      if (next === previous) return;
      const payload = { kind: sel.dataset.kind, permissions: next };
      if (sel.dataset.kind === 'user') payload.user_id = parseInt(sel.dataset.userId, 10);
      else payload.pg_id = parseInt(sel.dataset.pgId, 10);
      const r = await fetch(`/collaboration/share/${currentItem.id}/update-perm/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (!r.ok) {
        await mapAlert({ title: 'Update failed', message: d.error || 'Failed to update permission' });
        sel.value = previous;
        return;
      }
      aclRef.length = 0;
      (d.acl || []).forEach((row) => aclRef.push(row));
      refreshShareAclPanel(aclRef, options);
    };
  });

  list.querySelectorAll('button.share-acl-remove').forEach((btn) => {
    btn.onclick = async () => {
      if (!(await mapConfirm({
        title: 'Remove collaborator',
        message: 'Remove this collaborator from the share list?',
        confirmLabel: 'Remove',
        danger: true,
      }))) return;
      const payload = { kind: btn.dataset.kind };
      if (btn.dataset.kind === 'user') payload.user_id = parseInt(btn.dataset.userId, 10);
      else payload.pg_id = parseInt(btn.dataset.pgId, 10);
      const r = await fetch(`/collaboration/share/${currentItem.id}/revoke/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (!r.ok) {
        await mapAlert({ title: 'Remove failed', message: d.error || 'Failed to remove collaborator' });
        return;
      }
      aclRef.length = 0;
      (d.acl || []).forEach((row) => aclRef.push(row));
      refreshShareAclPanel(aclRef, options);
    };
  });

  const stopBtn = document.getElementById('share-stop-all');
  if (stopBtn) {
    stopBtn.onclick = async () => {
      if (!options.isOwner) return;
      const hasCollaborators = (aclRef || []).some((r) => r.permissions !== 'owner');
      if (hasCollaborators) {
        const ok = await mapConfirm({
          title: 'Stop collaboration',
          message:
            'Other users or groups currently have access to this item.\n\n' +
            'Remove all collaboration permissions and stop sharing? This cannot be undone from here.',
          confirmLabel: 'Stop collaboration',
          danger: true,
        });
        if (!ok) return;
      }
      const r = await fetch(`/collaboration/share/${currentItem.id}/unshare/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify({ confirmed: true }),
      });
      const d = await r.json();
      if (!r.ok) {
        await mapAlert({ title: 'Stop collaboration failed', message: d.error || 'Failed to stop collaboration' });
        return;
      }
      aclRef.length = 0;
      (d.acl || []).forEach((row) => aclRef.push(row));
      refreshShareAclPanel(aclRef, options);
    };
  }
}

function refreshShareAclPanel(aclRef, options = {}) {
  const list = document.getElementById('share-acl-list');
  if (!list) return;
  list.innerHTML = renderShareAclList(aclRef, options);
  bindShareAclControls(aclRef, options);
}

function updateSharePendingUI(grants) {
  const el = document.getElementById('share-pending');
  if (el) {
    if (!grants.length) {
      el.innerHTML = '';
    } else {
      el.innerHTML =
        `<div style="font-weight:600;margin-bottom:4px;">Ready to add</div>` +
        grants
          .map((g, idx) => {
            let label;
            if (g.kind === 'user') {
              label = `${g.username || `User #${g.user_id}`} (${formatPermLabel(g.permissions)})`;
            } else if (g.pg_id === 'public') {
              label = `Group: public (${formatPermLabel(g.permissions)})`;
            } else {
              label = `Group #${g.pg_id} (${formatPermLabel(g.permissions)})`;
            }
            return `
              <div class="share-pending-row" style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:4px 0;border-bottom:1px solid #eee;">
                <span>${label}</span>
                <button type="button" data-remove-pending="${idx}" title="Remove"
                        style="border:none;background:transparent;color:#b91c1c;cursor:pointer;font-size:1rem;line-height:1;padding:2px 6px;">&times;</button>
              </div>`;
          })
          .join('');
      el.querySelectorAll('[data-remove-pending]').forEach((btn) => {
        btn.onclick = () => {
          const idx = parseInt(btn.getAttribute('data-remove-pending'), 10);
          if (Number.isNaN(idx) || idx < 0 || idx >= grants.length) return;
          grants.splice(idx, 1);
          updateSharePendingUI(grants);
        };
      });
    }
  }
  const confirmBtn = document.getElementById('share-confirm-btn');
  if (confirmBtn) {
    const enabled = grants.length > 0;
    confirmBtn.disabled = !enabled;
    confirmBtn.style.opacity = enabled ? '' : '0.45';
    confirmBtn.style.cursor = enabled ? 'pointer' : 'not-allowed';
  }
}

function isShareGrantDuplicate(grants, acl, grant) {
  if (grant.kind === 'user') {
    if (grants.some((g) => g.kind === 'user' && g.user_id === grant.user_id)) return 'pending';
    if ((acl || []).some((r) => r.user_id === grant.user_id)) return 'existing';
  } else if (grant.kind === 'group') {
    if (grants.some((g) => g.kind === 'group' && String(g.pg_id) === String(grant.pg_id))) return 'pending';
    if (grant.pg_id === 'public') {
      if ((acl || []).some((r) => (r.permission_group_name || '').toLowerCase() === 'public')) return 'existing';
    } else if ((acl || []).some((r) => r.permission_group_id === grant.pg_id)) {
      return 'existing';
    }
  }
  return null;
}

async function openShareOverlay() {
  const res = await fetch(`/collaboration/share/${currentItem.id}/`);
  const ctx = await res.json();
  if (!res.ok) {
    await mapAlert({ title: 'Cannot share', message: ctx.error || 'Cannot share' });
    return;
  }
  let grants = [];
  const acl = ctx.acl || [];
  const shareUiOpts = { isOwner: !!ctx.is_owner };
  const itemName = ctx.name || currentItem.name || 'this item';
  const closeTip =
    `If you add no users or groups with permissions and close the overlay ${itemName} will be removed from the 'Collaboration' and the only access will be in your 'Workspace' folder.`;

  async function closeShareOverlay() {
    const branchId = currentItem && currentItem.id;
    const elBefore =
      (branchId && document.querySelector(`.item[data-branch-id="${branchId}"]`)) ||
      (branchId && document.querySelector(`.item[data-id="${branchId}"]`));
    const parentId = elBefore && elBefore.getAttribute('data-parent-id');
    const level = elBefore
      ? parseInt(elBefore.closest('.finder-column')?.dataset.level || '', 10)
      : NaN;

    let hasCollaborators = acl.some((r) => r.permissions && r.permissions !== 'owner');
    try {
      const check = await fetch(`/collaboration/share/${branchId}/`);
      const checkData = await check.json();
      if (check.ok && typeof checkData.has_collaborators === 'boolean') {
        hasCollaborators = checkData.has_collaborators;
      }
    } catch (_e) {
      /* keep local acl estimate */
    }

    if (shareUiOpts.isOwner && !hasCollaborators) {
      const r = await fetch(`/collaboration/share/${branchId}/unshare/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify({ confirmed: true }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        await mapAlert({
          title: 'Could not leave Collaboration',
          message: d.error || 'Failed to remove this item from Collaboration.',
        });
        return;
      }
    }
    hideMapOverlay();
    if (parentId && !Number.isNaN(level) && typeof loadFolder === 'function') {
      await loadFolder(parentId, level);
    } else {
      refreshExplorerItemColumn(branchId);
    }
    refreshCollaborationColumnIfOpen();
  }

  showMapOverlay({
    title: `Share “${itemName}”`,
    maxWidth: '760px',
    actionsAlign: 'space-between',
    bodyHtml: `
      <div style="display:flex;gap:16px;align-items:stretch;min-height:280px;">
        <div style="flex:1;min-width:0;">
          <div style="display:flex;gap:8px;margin-bottom:8px;">
            <button type="button" id="share-tab-user" style="flex:1;padding:6px;">Add user</button>
            <button type="button" id="share-tab-group" style="flex:1;padding:6px;">Add group</button>
          </div>
          <div id="share-user-pane">
            <input id="share-user-q" placeholder="Username or email" style="width:100%;padding:8px;box-sizing:border-box;">
            <div id="share-user-results" style="max-height:140px;overflow:auto;margin-top:6px;border:1px solid #eee;"></div>
          </div>
          <div id="share-group-pane" style="display:none;">
            <select id="share-group-select" class="map-select">
              <option value="">Select a group…</option>
              ${(ctx.my_groups || []).map((g) => `<option value="${g.pg_id}">${g.name} (${formatPermLabel(g.permissions)})</option>`).join('')}
              <option value="public">public (system)</option>
            </select>
          </div>
          <label style="display:block;margin-top:10px;">Permission
            <select id="share-perm" class="map-select" style="margin-top:4px;">
              <option value="edit">Edit</option>
              <option value="read_only">View-only</option>
            </select>
          </label>
          <label style="display:block;margin-top:10px;">Note to send (optional)
            <textarea id="share-note" rows="3" placeholder="Any message here will be sent to the notification inbox of the newly added users being granted permissions." style="width:100%;padding:8px;box-sizing:border-box;margin-top:4px;"></textarea>
          </label>
          <div id="share-pending" style="margin-top:8px;font-size:0.85rem;color:#555;"></div>
          <div id="share-add-hint" style="margin-top:6px;font-size:0.8rem;color:#b91c1c;"></div>
        </div>
        <div style="width:1px;background:#cbd5e1;flex-shrink:0;"></div>
        <div style="flex:1;min-width:0;display:flex;flex-direction:column;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
            <span style="font-weight:600;">Currently shared with</span>
            <span class="share-info-tip" tabindex="0" aria-label="${closeTip.replace(/"/g, '&quot;')}">
              <i class="fas fa-info-circle" aria-hidden="true"></i>
              <span class="share-info-tip-bubble">${closeTip
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')}</span>
            </span>
          </div>
          <div id="share-acl-list" style="flex:1;overflow:auto;max-height:360px;border:1px solid #e2e8f0;border-radius:8px;padding:8px 12px;background:#f8fafc;">
            ${renderShareAclList(acl, shareUiOpts)}
          </div>
        </div>
      </div>
    `,
    actions: [
      {
        id: 'share-confirm-btn',
        label: 'Confirm',
        primary: true,
        disabled: true,
        onClick: async () => {
          const perm = document.getElementById('share-perm').value;
          const note = document.getElementById('share-note').value;
          if (!grants.length) return;
          const payload = {
            note,
            permissions: perm,
            grants: grants.map((g) => ({ ...g, permissions: g.permissions || perm })),
          };
          const r = await fetch(`/collaboration/share/${currentItem.id}/grant/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
            body: JSON.stringify(payload),
          });
          const d = await r.json();
          if (!r.ok) {
            await mapAlert({ title: 'Share failed', message: d.error || d.message || 'Share failed' });
            return;
          }
          grants.length = 0;
          updateSharePendingUI(grants);
          acl.length = 0;
          (d.acl || []).forEach((row) => acl.push(row));
          refreshShareAclPanel(acl, shareUiOpts);
          const q = document.getElementById('share-user-q');
          if (q) q.value = '';
          const results = document.getElementById('share-user-results');
          if (results) results.innerHTML = '';
          const hintEl = document.getElementById('share-add-hint');
          if (hintEl) hintEl.textContent = '';
        },
      },
      { label: 'Close', onClick: closeShareOverlay },
    ],
  });

  bindShareAclControls(acl, shareUiOpts);
  updateSharePendingUI(grants);

  const overlay = document.getElementById('map-overlay');
  overlay.onclick = (e) => {
    if (e.target === overlay) closeShareOverlay();
  };

  const hint = document.getElementById('share-add-hint');
  const showHint = (msg) => {
    if (hint) hint.textContent = msg || '';
  };

  document.getElementById('share-tab-user').onclick = () => {
    document.getElementById('share-user-pane').style.display = 'block';
    document.getElementById('share-group-pane').style.display = 'none';
  };
  document.getElementById('share-tab-group').onclick = () => {
    document.getElementById('share-user-pane').style.display = 'none';
    document.getElementById('share-group-pane').style.display = 'block';
  };
  document.getElementById('share-group-select').onchange = (e) => {
    const v = e.target.value;
    if (!v) return;
    const grant =
      v === 'public'
        ? { kind: 'group', pg_id: 'public', permissions: document.getElementById('share-perm').value }
        : { kind: 'group', pg_id: parseInt(v, 10), permissions: document.getElementById('share-perm').value };
    const dup = isShareGrantDuplicate(grants, acl, grant);
    if (dup === 'pending') showHint('That group is already in the pending list.');
    else if (dup === 'existing') showHint('That group already has access on this item.');
    else {
      grants.push(grant);
      showHint('');
      updateSharePendingUI(grants);
    }
    e.target.value = '';
  };

  let searchTimer;
  document.getElementById('share-user-q').oninput = (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
      const q = e.target.value.trim();
      const box = document.getElementById('share-user-results');
      if (!q) {
        box.innerHTML = '';
        return;
      }
      const r = await fetch(`/collaboration/users/search/?q=${encodeURIComponent(q)}`);
      const d = await r.json();
      if (d.not_found) {
        box.innerHTML = `<div style="padding:8px;">No Teacher/IT user matches “${q}”.</div>`;
        return;
      }
      box.innerHTML = (d.results || [])
        .map(
          (u) => `
        <div style="padding:8px;border-bottom:1px solid #f0f0f0;cursor:pointer;" data-uid="${u.user_id}">
          <strong>${u.username}</strong> · ${u.email || ''}<br>
          <span style="color:#666;font-size:0.85rem;">${u.first_name || ''} ${u.last_name || ''} · ${u.organization || ''}</span>
        </div>`
        )
        .join('');
      box.querySelectorAll('[data-uid]').forEach((row) => {
        row.onclick = () => {
          const grant = {
            kind: 'user',
            user_id: parseInt(row.dataset.uid, 10),
            username: row.querySelector('strong')?.textContent || '',
            permissions: document.getElementById('share-perm').value,
          };
          const dup = isShareGrantDuplicate(grants, acl, grant);
          if (dup === 'pending') showHint('That user is already in the pending list.');
          else if (dup === 'existing') showHint('That user already has access on this item.');
          else {
            grants.push(grant);
            showHint('');
            updateSharePendingUI(grants);
          }
        };
      });
    }, 250);
  };
}

async function handleUnshare() {
  const r = await fetch(`/collaboration/share/${currentItem.id}/unshare/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
    body: JSON.stringify({ confirmed: false }),
  });
  const d = await r.json().catch(() => ({}));
  if (d.needs_confirm) {
    showMapOverlay({
      title: 'Unshare this item?',
      bodyHtml: `<p>${d.message}</p>`,
      actions: [
        { label: 'Cancel', onClick: hideMapOverlay },
        {
          label: 'Unshare',
          primary: true,
          onClick: async () => {
            const r2 = await fetch(`/collaboration/share/${currentItem.id}/unshare/`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
              body: JSON.stringify({ confirmed: true }),
            });
            const d2 = await r2.json().catch(() => ({}));
            hideMapOverlay();
            if (!r2.ok) {
              await mapAlert({ title: 'Unshare failed', message: d2.error || 'Unshare failed' });
              return;
            }
            refreshCollaborationColumnIfOpen();
          },
        },
      ],
    });
    return;
  }
  if (!r.ok) {
    await mapAlert({ title: 'Unshare failed', message: d.error || 'Unshare failed' });
    return;
  }
  refreshCollaborationColumnIfOpen();
}

async function handleLeaveShare() {
  const r = await fetch(`/collaboration/share/${currentItem.id}/leave/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
    body: '{}',
  });
  const d = await r.json();
  if (!r.ok) await mapAlert({ title: 'Leave failed', message: d.error || 'Leave failed' });
  else location.reload();
}

let moveDestParentId = null;
let movePathStack = []; // [{ id, name }, ...] from root → current folder
let moveSourceBranchId = null;

async function fetchMoveFolderItems(folderId) {
  const res = await fetch(`/get-folder-contents/${folderId}/?level=1`);
  const html = await res.text();
  const tmp = document.createElement('div');
  tmp.innerHTML = html;
  return [...tmp.querySelectorAll('.item')].map((item) => ({
    id: parseInt(item.getAttribute('data-branch-id') || item.getAttribute('data-id'), 10),
    name: item.querySelector('span')?.textContent?.trim() || '',
    type: item.getAttribute('data-type') || 'folder',
  }));
}

function renderMoveBreadcrumb() {
  const crumb = document.getElementById('move-crumb');
  if (!crumb) return;
  crumb.innerHTML = '';
  const label = document.createElement('span');
  label.textContent = 'Current: ';
  label.style.color = '#666';
  crumb.appendChild(label);

  movePathStack.forEach((seg, idx) => {
    if (idx > 0) {
      const sep = document.createElement('span');
      sep.textContent = ' › ';
      sep.style.color = '#94a3b8';
      crumb.appendChild(sep);
    }
    const isLast = idx === movePathStack.length - 1;
    if (isLast) {
      const span = document.createElement('span');
      span.textContent = seg.name;
      span.style.fontWeight = '600';
      span.style.color = '#334155';
      crumb.appendChild(span);
    } else {
      const link = document.createElement('button');
      link.type = 'button';
      link.textContent = seg.name;
      link.style.cssText =
        'background:none;border:none;padding:0;color:#007aff;cursor:pointer;font:inherit;text-decoration:underline;';
      link.onclick = async () => {
        movePathStack = movePathStack.slice(0, idx + 1);
        await renderMoveBrowser();
      };
      crumb.appendChild(link);
    }
  });
}

async function renderMoveBrowser() {
  const current = movePathStack[movePathStack.length - 1];
  if (!current) return;
  moveDestParentId = current.id;
  renderMoveBreadcrumb();

  const list = document.getElementById('move-list');
  list.innerHTML = '';

  const hint = document.createElement('div');
  hint.style.cssText = 'padding:10px;background:#f8fafc;border-bottom:1px solid #eee;font-size:0.9rem;color:#475569;';
  hint.innerHTML =
    '<em>Destination set to this folder. Open a subfolder to go deeper, or click Move / Copy here.</em>';
  list.appendChild(hint);

  const items = await fetchMoveFolderItems(current.id);
  const navigable = items.filter((it) => {
    // At user root, only show top destinations used for moves.
    if (movePathStack.length === 1) {
      return it.type === 'folder' && ['Workspace', 'Collaboration'].includes(it.name);
    }
    return true;
  });

  if (!navigable.length) {
    const empty = document.createElement('div');
    empty.style.cssText = 'padding:12px;color:#94a3b8;font-size:0.9rem;';
    empty.textContent = 'No folders here.';
    list.appendChild(empty);
    return;
  }

  navigable.forEach((it) => {
    const isBlocked = it.id === moveSourceBranchId;
    const row = document.createElement('div');
    row.style.cssText = isBlocked
      ? 'padding:10px;border-bottom:1px solid #f3f3f3;display:flex;justify-content:space-between;align-items:center;color:#94a3b8;background:#f1f5f9;cursor:not-allowed;opacity:0.75;'
      : 'padding:10px;border-bottom:1px solid #f3f3f3;cursor:pointer;display:flex;justify-content:space-between;align-items:center;';
    row.innerHTML = isBlocked
      ? `<span><i class="fas fa-folder"></i> ${it.name}</span><span style="font-size:0.8rem;">Can't move into itself</span>`
      : `<span><i class="fas fa-folder"></i> ${it.name}</span><span style="color:#007aff;">Open</span>`;
    if (!isBlocked) {
      row.onclick = async () => {
        movePathStack.push({ id: it.id, name: it.name });
        await renderMoveBrowser();
      };
    }
    list.appendChild(row);
  });
}

async function openMoveOverlay() {
  moveSourceBranchId = parseInt(currentItem.id, 10);
  const rootId = window.MAP_EXPLORER.rootFolderId;
  const rootItems = await fetchMoveFolderItems(rootId);
  const workspace = rootItems.find((it) => it.name === 'Workspace' && it.type === 'folder');
  if (!workspace) {
    await mapAlert({ title: 'Move failed', message: 'Workspace folder not found.' });
    return;
  }

  const rootName = window.MAP_EXPLORER.rootFolderName || `${window.MAP_EXPLORER.username}_root`;

  movePathStack = [
    { id: rootId, name: rootName },
    { id: workspace.id, name: 'Workspace' },
  ];
  moveDestParentId = workspace.id;

  showMapOverlay({
    title: 'Move to…',
    bodyHtml: `
      <div id="move-crumb" style="font-size:0.85rem;margin-bottom:8px;line-height:1.5;flex-wrap:wrap;"></div>
      <div id="move-list" style="border:1px solid #eee;max-height:280px;overflow:auto;"></div>
    `,
    actions: [
      { label: 'Cancel', onClick: hideMapOverlay },
      {
        label: 'Move / Copy here',
        primary: true,
        onClick: async () => {
          if (!moveDestParentId) {
            await mapAlert({ title: 'Select a destination', message: 'Select a destination folder.' });
            return;
          }
          if (moveDestParentId === moveSourceBranchId) {
            await mapAlert({ title: 'Invalid move', message: 'Cannot move an item into itself.' });
            return;
          }
          await commitMove(false);
        },
      },
    ],
  });
  await renderMoveBrowser();
}

async function commitMove(confirmed, replaceConfirmed = false) {
  const r = await fetch('/collaboration/move-item/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
    body: JSON.stringify({
      branch_id: currentItem.id,
      dest_parent_id: moveDestParentId,
      confirmed,
      replace_confirmed: replaceConfirmed,
    }),
  });
  const d = await r.json().catch(() => ({}));
  if (d.needs_confirm) {
    const isReplace = !!d.replace;
    showMapOverlay({
      title: isReplace
        ? 'Replace existing item?'
        : d.copy
          ? 'Copy into Collaboration?'
          : 'Add to shared folder?',
      bodyHtml: `<p>${d.message || ''}</p>`,
      actions: [
        { label: 'Cancel', onClick: hideMapOverlay },
        {
          label: isReplace ? 'Delete & replace' : 'Confirm',
          primary: true,
          onClick: async () => {
            hideMapOverlay();
            await commitMove(true, isReplace);
          },
        },
      ],
    });
    return;
  }
  if (!r.ok) {
    await mapAlert({ title: 'Move failed', message: d.error || 'Move failed' });
    return;
  }
  hideMapOverlay();
  location.reload();
}


async function closeManageGroups() {
  try {
    await fetch('/collaboration/groups/cleanup-empty/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: '{}',
    });
  } catch (_e) {
    /* still close */
  }
  hideMapOverlay();
}

async function openManageGroups() {
  const res = await fetch('/collaboration/groups/');
  const data = await res.json();
  if (!res.ok) {
    await mapAlert({ title: 'Failed', message: data.error || 'Failed' });
    return;
  }
  showMapOverlay({
    title: 'Manage Groups',
    maxWidth: '640px',
    actionsAlign: 'space-between',
    actionsHint:
      'Groups with no other users or sub-groups will be automatically deleted when you close this overlay.',
    bodyHtml: `
      <div style="margin-bottom:10px;">
        <input id="new-group-name" placeholder="New group name" style="width:70%;padding:8px;">
        <button id="btn-create-group" style="padding:8px 10px;">Create</button>
      </div>
      <div id="groups-list" style="max-height:180px;overflow:auto;border:1px solid #e2e8f0;border-radius:8px;">${
        (data.groups || [])
          .map(
            (g) => `
        <div style="padding:8px 10px;border-bottom:1px solid #eee;cursor:pointer;" onclick="openGroupDetail(${g.pg_id})">
          <strong>${g.name}</strong> · your role: ${formatPermLabel(g.permissions)}${g.is_public ? ' (public)' : ''}${g.is_admins ? ' (admins)' : ''}
        </div>`
          )
          .join('') || '<div style="padding:10px;"><em>No groups yet.</em></div>'
      }</div>
      <div id="group-detail" style="margin-top:16px;"></div>
    `,
    actions: [{ label: 'Close', primary: true, onClick: closeManageGroups }],
  });
  const overlay = document.getElementById('map-overlay');
  overlay.onclick = (e) => {
    if (e.target === overlay) closeManageGroups();
  };
  document.getElementById('btn-create-group').onclick = async () => {
    const name = document.getElementById('new-group-name').value.trim();
    if (!name) return;
    const r = await fetch('/collaboration/groups/create/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({ name }),
    });
    const d = await r.json();
    if (!r.ok) await mapAlert({ title: 'Create failed', message: d.error || 'Create failed' });
    else openManageGroups();
  };
}

function memberAccessControls(g, m) {
  if (g.is_public || g.is_admins || g.is_system) {
    if (m.is_owner) {
      return '<span style="color:#64748b;font-size:0.85rem;">owner</span>';
    }
    return `<span style="color:#64748b;font-size:0.85rem;">${formatPermLabel(m.permissions)}</span>`;
  }
  const isOwnerViewer = g.my_role === 'owner';
  const canManage = isOwnerViewer || g.my_role === 'edit';
  if (m.is_owner) {
    return '<span style="color:#64748b;font-size:0.85rem;">owner</span>';
  }
  if (isOwnerViewer) {
    const canTransfer = m.permissions === 'edit';
    return `
      <select
        class="map-select map-select-sm"
        data-pg-id="${g.id}"
        data-user-id="${m.user_id}"
        data-current="${m.permissions}"
        onchange="changeGroupMemberAccess(this)">
        <option value="edit" ${m.permissions === 'edit' ? 'selected' : ''}>Edit</option>
        <option value="read_only" ${m.permissions === 'read_only' ? 'selected' : ''}>View-only</option>
        <option value="transfer_ownership" ${canTransfer ? '' : 'disabled'}>
          Transfer ownership to this user
        </option>
      </select>
      <button onclick="removeGroupMember(${g.id},${m.user_id})" style="margin-left:6px;">Remove</button>
    `;
  }
  if (canManage) {
    return `<button onclick="removeGroupMember(${g.id},${m.user_id})">Remove</button>`;
  }
  return '';
}

function subgroupAccessControls(g, s) {
  const canManage = !g.is_system && !g.is_public && (g.my_role === 'owner' || g.my_role === 'edit');
  if (!canManage) {
    return `<span style="color:#64748b;font-size:0.85rem;">${formatPermLabel(s.permissions)}</span>`;
  }
  return `
    <select
      class="map-select map-select-sm"
      data-pg-id="${g.id}"
      data-child-pg-id="${s.pg_id}"
      data-current="${s.permissions}"
      onchange="changeSubgroupAccess(this)">
      <option value="edit" ${s.permissions === 'edit' ? 'selected' : ''}>Edit</option>
      <option value="read_only" ${s.permissions === 'read_only' ? 'selected' : ''}>View-only</option>
    </select>
    <button onclick="removeGroupSubgroup(${g.id},${s.pg_id})" style="margin-left:6px;">Remove</button>
  `;
}

async function openGroupDetail(pgId) {
  const res = await fetch(`/collaboration/groups/${pgId}/`);
  const g = await res.json();
  if (!res.ok) {
    await mapAlert({ title: 'Failed', message: g.error || 'Failed' });
    return;
  }
  const canManage = !g.is_system && !g.is_public && (g.my_role === 'owner' || g.my_role === 'edit');
  const isOwner = g.my_role === 'owner';
  const justSet = justAddedGroupMembers[g.id] || new Set();
  const systemNote = g.is_admins
    ? `<div style="margin-bottom:10px;font-size:0.85rem;color:#64748b;">The admins group is system-managed and cannot be deleted. All IT Support users are added automatically; it owns the public group.</div>`
    : g.is_public
      ? `<div style="margin-bottom:10px;font-size:0.85rem;color:#64748b;">The public group is owned by admins (not an individual). Members are system-managed; Public Library shows the shared items themselves, not a personal Workspace copy.</div>`
      : '';
  document.getElementById('group-detail').innerHTML = `
    <div style="border-top:2px solid #94a3b8;margin:4px 0 14px;"></div>
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px;">
      <h4 style="margin:0;">${g.name}</h4>
      ${
        isOwner && !g.is_system && !g.is_public
          ? `<button type="button" class="map-dialog-btn map-dialog-btn-danger" style="padding:6px 10px;font-size:0.85rem;" onclick="deleteManagedGroup(${g.id}, ${JSON.stringify(g.name)})">Delete group</button>`
          : ''
      }
    </div>
    ${systemNote}
    <div style="font-size:0.8rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:6px;">Members</div>
    <div id="group-members-list" style="max-height:180px;overflow:auto;border:1px solid #e2e8f0;border-radius:8px;background:#fff;">
      ${
        (g.members || [])
          .map((m) => {
            const isJustAdded = justSet.has(m.user_id);
            const rowStyle = isJustAdded
              ? 'display:flex;justify-content:space-between;align-items:center;gap:8px;padding:8px 10px;border-bottom:1px solid #bbf7d0;background:#dcfce7;'
              : 'display:flex;justify-content:space-between;align-items:center;gap:8px;padding:8px 10px;border-bottom:1px solid #f1f5f9;';
            const badge = isJustAdded
              ? '<span style="margin-left:8px;font-size:0.72rem;font-weight:700;color:#166534;background:#86efac;padding:2px 6px;border-radius:999px;">just added</span>'
              : '';
            return `
      <div style="${rowStyle}">
        <span>${m.username} · ${formatPermLabel(m.permissions)}${badge}</span>
        <span style="display:flex;align-items:center;flex-shrink:0;">${memberAccessControls(g, m)}</span>
      </div>`;
          })
          .join('') || '<div style="padding:10px;"><em>No visible members.</em></div>'
      }
    </div>
    ${
      !g.is_system && !g.is_public
        ? `
    <div style="font-size:0.8rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:0.04em;margin:14px 0 6px;">Subgroups</div>
    <div id="group-subgroups-list" style="max-height:140px;overflow:auto;border:1px solid #e2e8f0;border-radius:8px;background:#fff;">
      ${
        (g.subgroups || [])
          .map(
            (s) => `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;padding:8px 10px;border-bottom:1px solid #f1f5f9;">
        <span><i class="fas fa-users" style="margin-right:6px;color:#64748b;"></i>${s.name} · ${formatPermLabel(s.permissions)}</span>
        <span style="display:flex;align-items:center;flex-shrink:0;">${subgroupAccessControls(g, s)}</span>
      </div>`
          )
          .join('') || '<div style="padding:10px;"><em>No subgroups.</em></div>'
      }
    </div>`
        : ''
    }
    ${g.my_role !== 'owner' && !g.is_system && !g.is_public ? `<button style="margin-top:8px;" onclick="leaveGroup(${g.id})">Leave group</button>` : ''}
    ${
      canManage
        ? `
      <div style="margin-top:12px;display:flex;gap:8px;">
        <button type="button" id="group-add-tab-user" style="flex:1;padding:6px;">Add user</button>
        <button type="button" id="group-add-tab-group" style="flex:1;padding:6px;">Add subgroup</button>
      </div>
      <div id="group-add-user-pane" style="margin-top:8px;">
        <input id="add-member-q" placeholder="Add user (username/email)" style="width:100%;padding:6px;box-sizing:border-box;">
        <div id="add-member-results" style="max-height:140px;overflow:auto;margin-top:4px;border:1px solid #eee;"></div>
      </div>
      <div id="group-add-subgroup-pane" style="margin-top:8px;display:none;">
        <input id="add-subgroup-q" placeholder="Filter groups you belong to" style="width:100%;padding:6px;box-sizing:border-box;">
        <div id="add-subgroup-results" style="max-height:140px;overflow:auto;margin-top:4px;border:1px solid #eee;"></div>
      </div>
      <div id="add-member-hint" style="margin-top:4px;font-size:0.8rem;color:#b91c1c;"></div>`
        : ''
    }
  `;
  if (canManage) {
    const userTab = document.getElementById('group-add-tab-user');
    const groupTab = document.getElementById('group-add-tab-group');
    const userPane = document.getElementById('group-add-user-pane');
    const groupPane = document.getElementById('group-add-subgroup-pane');
    userTab.onclick = () => {
      userPane.style.display = '';
      groupPane.style.display = 'none';
    };
    groupTab.onclick = () => {
      userPane.style.display = 'none';
      groupPane.style.display = '';
      renderSubgroupCandidates(g);
    };

    const input = document.getElementById('add-member-q');
    let t;
    input.oninput = () => {
      clearTimeout(t);
      t = setTimeout(async () => {
        const r = await fetch(`/collaboration/users/search/?q=${encodeURIComponent(input.value.trim())}`);
        const d = await r.json();
        const box = document.getElementById('add-member-results');
        box.innerHTML = (d.results || [])
          .map(
            (u) => `
          <div style="padding:6px;cursor:pointer;" onclick="addGroupMember(${g.id},${u.user_id})">${u.username} · ${u.email}</div>
        `
          )
          .join('');
      }, 200);
    };

    const sgInput = document.getElementById('add-subgroup-q');
    sgInput.oninput = () => renderSubgroupCandidates(g);
  }
}

async function renderSubgroupCandidates(g) {
  const box = document.getElementById('add-subgroup-results');
  const q = (document.getElementById('add-subgroup-q')?.value || '').trim().toLowerCase();
  if (!box) return;
  const res = await fetch('/collaboration/groups/');
  const data = await res.json();
  if (!res.ok) {
    box.innerHTML = `<div style="padding:6px;color:#b91c1c;">${data.error || 'Failed to load groups'}</div>`;
    return;
  }
  const existing = new Set((g.subgroups || []).map((s) => s.pg_id));
  const candidates = (data.groups || []).filter((cand) => {
    if (cand.is_public || cand.is_admins || cand.is_system) return false;
    if (cand.pg_id === g.id) return false;
    if (existing.has(cand.pg_id)) return false;
    if (q && !(cand.name || '').toLowerCase().includes(q)) return false;
    return true;
  });
  box.innerHTML =
    candidates
      .map(
        (cand) => `
      <div style="padding:6px;cursor:pointer;" onclick="addGroupSubgroup(${g.id},${cand.pg_id})">
        ${cand.name} · your role: ${formatPermLabel(cand.permissions)}
      </div>`
      )
      .join('') || '<div style="padding:6px;"><em>No matching groups.</em></div>';
}

async function changeSubgroupAccess(selectEl) {
  const pgId = parseInt(selectEl.dataset.pgId, 10);
  const childId = parseInt(selectEl.dataset.childPgId, 10);
  const previous = selectEl.dataset.current;
  const next = selectEl.value;
  if (next === previous) return;
  const r = await fetch(`/collaboration/groups/${pgId}/add-subgroup/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
    body: JSON.stringify({ child_pg_id: childId, permissions: next }),
  });
  const d = await r.json();
  if (!r.ok) {
    await mapAlert({ title: 'Update failed', message: d.error || 'Failed to update subgroup access' });
    selectEl.value = previous;
    return;
  }
  openGroupDetail(pgId);
}

async function addGroupSubgroup(pgId, childPgId) {
  const hint = document.getElementById('add-member-hint');
  const r = await fetch(`/collaboration/groups/${pgId}/add-subgroup/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
    body: JSON.stringify({ child_pg_id: childPgId, permissions: 'read_only', only_if_new: true }),
  });
  const d = await r.json();
  if (!r.ok) {
    if (hint) hint.textContent = d.error || 'Failed';
    else await mapAlert({ title: 'Failed', message: d.error || 'Failed' });
    return;
  }
  if (d.already_member) {
    if (hint) hint.textContent = 'That group is already a subgroup.';
    return;
  }
  if (hint) hint.textContent = '';
  openGroupDetail(pgId);
}

async function removeGroupSubgroup(pgId, childPgId) {
  const r = await fetch(`/collaboration/groups/${pgId}/remove-subgroup/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
    body: JSON.stringify({ child_pg_id: childPgId }),
  });
  const d = await r.json();
  if (!r.ok) await mapAlert({ title: 'Failed', message: d.error || 'Failed' });
  else openGroupDetail(pgId);
}

async function deleteManagedGroup(pgId, name) {
  if (
    !(await mapConfirm({
      title: 'Delete group',
      message: `Delete “${name}”? All users and subgroups will be removed from this group.`,
      confirmLabel: 'Delete',
      danger: true,
    }))
  ) {
    return;
  }
  const r = await fetch(`/collaboration/groups/${pgId}/delete/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
    body: '{}',
  });
  const d = await r.json();
  if (!r.ok) await mapAlert({ title: 'Delete failed', message: d.error || 'Delete failed' });
  else openManageGroups();
}

async function changeGroupMemberAccess(selectEl) {
  const pgId = parseInt(selectEl.dataset.pgId, 10);
  const userId = parseInt(selectEl.dataset.userId, 10);
  const previous = selectEl.dataset.current;
  const next = selectEl.value;

  if (next === previous) return;

  if (next === 'transfer_ownership') {
    if (
      !(await mapConfirm({
        title: 'Transfer ownership',
        message:
          'Transfer ownership to this user? Shared files for this group will move into their Workspace, and you will keep edit access.',
        confirmLabel: 'Transfer',
        danger: true,
      }))
    ) {
      selectEl.value = previous;
      return;
    }
    const r = await fetch(`/collaboration/groups/${pgId}/transfer/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({ user_id: userId }),
    });
    const d = await r.json();
    if (!r.ok) {
      await mapAlert({ title: 'Transfer failed', message: d.error || 'Transfer failed' });
      selectEl.value = previous;
      return;
    }
    openManageGroups();
    return;
  }

  const r = await fetch(`/collaboration/groups/${pgId}/add/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
    body: JSON.stringify({ user_id: userId, permissions: next }),
  });
  const d = await r.json();
  if (!r.ok) {
    await mapAlert({ title: 'Update failed', message: d.error || 'Failed to update access' });
    selectEl.value = previous;
    return;
  }
  openGroupDetail(pgId);
}

async function addGroupMember(pgId, userId) {
  const hint = document.getElementById('add-member-hint');
  const r = await fetch(`/collaboration/groups/${pgId}/add/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
    body: JSON.stringify({ user_id: userId, permissions: 'read_only', only_if_new: true }),
  });
  const d = await r.json();
  if (!r.ok) {
    if (hint) hint.textContent = d.error || 'Failed';
    else await mapAlert({ title: 'Failed', message: d.error || 'Failed' });
    return;
  }
  if (d.already_member) {
    if (hint) hint.textContent = 'That user is already in this group.';
    return;
  }
  if (!justAddedGroupMembers[pgId]) justAddedGroupMembers[pgId] = new Set();
  justAddedGroupMembers[pgId].add(userId);
  const input = document.getElementById('add-member-q');
  if (input) input.value = '';
  const box = document.getElementById('add-member-results');
  if (box) box.innerHTML = '';
  if (hint) hint.textContent = '';
  openGroupDetail(pgId);
}

async function removeGroupMember(pgId, userId) {
  const r = await fetch(`/collaboration/groups/${pgId}/remove/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
    body: JSON.stringify({ user_id: userId }),
  });
  const d = await r.json();
  if (!r.ok) await mapAlert({ title: 'Failed', message: d.error || 'Failed' });
  else {
    if (justAddedGroupMembers[pgId]) justAddedGroupMembers[pgId].delete(userId);
    openGroupDetail(pgId);
  }
}

async function leaveGroup(pgId) {
  const r = await fetch(`/collaboration/groups/${pgId}/remove/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
    body: JSON.stringify({ user_id: window.MAP_EXPLORER.userId }),
  });
  const d = await r.json();
  if (!r.ok) await mapAlert({ title: 'Failed', message: d.error || 'Failed' });
  else openManageGroups();
}

let dragBranchId = null;
document.addEventListener('dragstart', (e) => {
  const item = e.target.closest('.item[data-branch-id]');
  if (!item) return;
  dragBranchId = item.getAttribute('data-branch-id');
});
document.addEventListener('dragover', (e) => {
  const item = e.target.closest('.item[data-branch-id]');
  if (!item || !dragBranchId) return;
  e.preventDefault();
});
document.addEventListener('drop', async (e) => {
  const item = e.target.closest('.item[data-branch-id]');
  if (!item || !dragBranchId) return;
  e.preventDefault();
  const beforeId = item.getAttribute('data-branch-id');
  if (beforeId === dragBranchId) return;
  const parentId = item.getAttribute('data-parent-id');
  const level = parseInt(item.closest('.finder-column')?.dataset.level || '1', 10);
  const r = await fetch('/collaboration/reorder/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
    body: JSON.stringify({ branch_id: parseInt(dragBranchId, 10), before_id: parseInt(beforeId, 10) }),
  });
  dragBranchId = null;
  if (r.ok && parentId) loadFolder(parentId, level);
});
