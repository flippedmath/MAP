/**
 * Global overlay dialogs replacing window.alert / confirm / prompt.
 *
 * API:
 *   mapAlert({ title, message, okLabel }) -> Promise<void>
 *   mapConfirm({ title, message, confirmLabel, cancelLabel, danger }) -> Promise<boolean>
 *   mapPrompt({ title, message, defaultValue, okLabel, cancelLabel, placeholder }) -> Promise<string|null>
 *   showMapDialog({ title, message, actions, input })  (low-level)
 *   hideMapDialog()
 *
 * Forms/buttons: data-map-confirm="…", optional data-map-confirm-danger,
 * data-map-confirm-title, data-map-confirm-ok, data-map-confirm-cancel.
 */
(function () {
  'use strict';

  var ESCAPE_HANDLER = null;
  var alertQueue = Promise.resolve();

  function ensureDialogDom() {
    var overlay = document.getElementById('map-dialog-overlay');
    if (overlay) return overlay;

    overlay = document.createElement('div');
    overlay.id = 'map-dialog-overlay';
    overlay.setAttribute('role', 'alertdialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-labelledby', 'map-dialog-title');
    overlay.setAttribute('aria-describedby', 'map-dialog-message');
    overlay.innerHTML =
      '<div id="map-dialog-panel">' +
      '<h3 id="map-dialog-title"></h3>' +
      '<p id="map-dialog-message"></p>' +
      '<div id="map-dialog-input-wrap" hidden>' +
      '<input id="map-dialog-input" type="text" autocomplete="off" />' +
      '</div>' +
      '<div id="map-dialog-actions"></div>' +
      '</div>';
    document.body.appendChild(overlay);
    return overlay;
  }

  function hideMapDialog() {
    var overlay = document.getElementById('map-dialog-overlay');
    if (!overlay) return;
    overlay.style.display = 'none';
    overlay.onclick = null;
    if (ESCAPE_HANDLER) {
      document.removeEventListener('keydown', ESCAPE_HANDLER);
      ESCAPE_HANDLER = null;
    }
    var inputWrap = document.getElementById('map-dialog-input-wrap');
    var input = document.getElementById('map-dialog-input');
    if (inputWrap) inputWrap.hidden = true;
    if (input) {
      input.value = '';
      input.onkeydown = null;
    }
  }

  function showMapDialog(opts) {
    opts = opts || {};
    var overlay = ensureDialogDom();
    var titleEl = document.getElementById('map-dialog-title');
    var messageEl = document.getElementById('map-dialog-message');
    var act = document.getElementById('map-dialog-actions');
    var inputWrap = document.getElementById('map-dialog-input-wrap');
    var input = document.getElementById('map-dialog-input');
    var actions = opts.actions || [];

    titleEl.textContent = opts.title || '';
    messageEl.textContent = opts.message || '';
    messageEl.style.display = opts.message ? '' : 'none';
    titleEl.style.display = opts.title ? '' : 'none';

    if (opts.input) {
      inputWrap.hidden = false;
      input.value = opts.input.defaultValue != null ? String(opts.input.defaultValue) : '';
      input.placeholder = opts.input.placeholder || '';
      input.setAttribute('aria-label', opts.input.ariaLabel || opts.title || 'Value');
    } else {
      inputWrap.hidden = true;
      input.value = '';
    }

    act.innerHTML = '';
    actions.forEach(function (a) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = a.label;
      btn.className = a.danger
        ? 'map-dialog-btn map-dialog-btn-danger'
        : a.primary
          ? 'map-dialog-btn map-dialog-btn-primary'
          : 'map-dialog-btn map-dialog-btn-secondary';
      btn.onclick = async function () {
        if (a.onClick) await a.onClick();
      };
      act.appendChild(btn);
    });

    overlay.onclick = function (e) {
      if (e.target !== overlay) return;
      var cancel = actions.find(function (a) {
        return !a.primary && !a.danger;
      });
      if (cancel && cancel.onClick) cancel.onClick();
    };

    if (ESCAPE_HANDLER) {
      document.removeEventListener('keydown', ESCAPE_HANDLER);
    }
    ESCAPE_HANDLER = function (e) {
      if (e.key !== 'Escape') return;
      var cancel = actions.find(function (a) {
        return !a.primary && !a.danger;
      });
      if (cancel && cancel.onClick) {
        e.preventDefault();
        cancel.onClick();
      } else if (actions.length === 1 && actions[0].onClick) {
        e.preventDefault();
        actions[0].onClick();
      }
    };
    document.addEventListener('keydown', ESCAPE_HANDLER);

    overlay.style.display = 'flex';

    if (opts.input) {
      setTimeout(function () {
        input.focus();
        input.select();
      }, 0);
      input.onkeydown = function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          var ok = actions.find(function (a) {
            return a.primary || a.danger;
          });
          if (ok && ok.onClick) ok.onClick();
        }
      };
    } else {
      var primary = act.querySelector('.map-dialog-btn-primary, .map-dialog-btn-danger');
      if (primary) {
        setTimeout(function () {
          primary.focus();
        }, 0);
      }
    }
  }

  function mapConfirm(options) {
    options = options || {};
    var message = options.message;
    if (message == null && typeof options === 'string') {
      message = options;
      options = {};
    }
    return new Promise(function (resolve) {
      showMapDialog({
        title: options.title || 'Confirm',
        message: message || '',
        actions: [
          {
            label: options.cancelLabel || 'Cancel',
            onClick: function () {
              hideMapDialog();
              resolve(false);
            },
          },
          {
            label: options.confirmLabel || 'Confirm',
            primary: !options.danger,
            danger: !!options.danger,
            onClick: function () {
              hideMapDialog();
              resolve(true);
            },
          },
        ],
      });
    });
  }

  function mapAlert(options) {
    options = options || {};
    var message = options.message;
    if (message == null && typeof options === 'string') {
      message = options;
      options = {};
    }
    return new Promise(function (resolve) {
      showMapDialog({
        title: options.title || 'Notice',
        message: message || '',
        actions: [
          {
            label: options.okLabel || 'OK',
            primary: true,
            onClick: function () {
              hideMapDialog();
              resolve();
            },
          },
        ],
      });
    });
  }

  function mapPrompt(options) {
    options = options || {};
    return new Promise(function (resolve) {
      showMapDialog({
        title: options.title || 'Input',
        message: options.message || '',
        input: {
          defaultValue: options.defaultValue != null ? options.defaultValue : '',
          placeholder: options.placeholder || '',
          ariaLabel: options.ariaLabel || options.title || 'Value',
        },
        actions: [
          {
            label: options.cancelLabel || 'Cancel',
            onClick: function () {
              hideMapDialog();
              resolve(null);
            },
          },
          {
            label: options.okLabel || 'OK',
            primary: true,
            onClick: function () {
              var input = document.getElementById('map-dialog-input');
              var value = input ? input.value : '';
              hideMapDialog();
              resolve(value);
            },
          },
        ],
      });
    });
  }

  var pendingSubmitter = null;

  function armAndSubmit(form, submitter) {
    form.setAttribute('data-map-confirm-armed', '1');
    if (typeof form.requestSubmit === 'function') {
      if (submitter) form.requestSubmit(submitter);
      else form.requestSubmit();
    } else {
      form.submit();
    }
  }

  function confirmOptionsFrom(el) {
    return {
      title: el.getAttribute('data-map-confirm-title') || 'Confirm',
      message: el.getAttribute('data-map-confirm') || '',
      confirmLabel: el.getAttribute('data-map-confirm-ok') || 'Confirm',
      cancelLabel: el.getAttribute('data-map-confirm-cancel') || 'Cancel',
      danger: el.hasAttribute('data-map-confirm-danger'),
    };
  }

  function bindDataMapConfirm() {
    // Track submitter for browsers with weak submitter support.
    document.addEventListener(
      'click',
      function (e) {
        var btn =
          e.target && e.target.closest
            ? e.target.closest(
                'button[type="submit"][data-map-confirm], input[type="submit"][data-map-confirm], button[data-map-confirm]:not([type]), button[form][data-map-confirm]'
              )
            : null;
        pendingSubmitter = btn || null;
      },
      true
    );

    document.addEventListener(
      'submit',
      function (e) {
        var form = e.target;
        if (!form || form.tagName !== 'FORM') return;
        if (form.getAttribute('data-map-confirm-armed') === '1') {
          form.removeAttribute('data-map-confirm-armed');
          pendingSubmitter = null;
          return;
        }
        var submitter = e.submitter || pendingSubmitter;
        if (submitter && submitter.form && submitter.form !== form) {
          submitter = e.submitter || null;
        }
        var source = null;
        if (submitter && submitter.hasAttribute && submitter.hasAttribute('data-map-confirm')) {
          source = submitter;
        } else if (form.hasAttribute('data-map-confirm')) {
          source = form;
        } else {
          return;
        }
        e.preventDefault();
        e.stopPropagation();
        mapConfirm(confirmOptionsFrom(source)).then(function (ok) {
          if (ok) armAndSubmit(form, submitter && source === submitter ? submitter : null);
        });
      },
      true
    );
  }

  // Queue overlays so rapid alert() calls don't stack on top of each other.
  function queuedAlert(message) {
    alertQueue = alertQueue.then(function () {
      return mapAlert({ message: String(message == null ? '' : message) });
    });
    return undefined;
  }

  window.showMapDialog = showMapDialog;
  window.hideMapDialog = hideMapDialog;
  window.mapConfirm = mapConfirm;
  window.mapAlert = mapAlert;
  window.mapPrompt = mapPrompt;

  // Replace native alert with overlay (async, queued). confirm/prompt stay
  // native only as last-resort fallbacks; call sites should use mapConfirm/mapPrompt.
  window.alert = queuedAlert;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindDataMapConfirm);
  } else {
    bindDataMapConfirm();
  }
})();
