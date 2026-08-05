/**
 * Student live assessment take: load frozen attempt, render via PracticeTestPreviewAPI,
 * autosave answers, one-shot submit (server grades; never shows answer keys).
 * Polls for assessment close and kicks the student with a forced submit.
 */

function getCookie(name) {
  if (typeof window.getCookie === 'function') return window.getCookie(name);
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : '';
}

function escapeHtml(val) {
  return String(val ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function buildSegmentMap(segments) {
  const map = {};
  (segments || []).forEach((seg) => {
    const key = String(seg.sequence_token || '').trim();
    if (key) map[key] = seg;
  });
  return map;
}

function buildLatexByToken(segments) {
  const out = {};
  (segments || []).forEach((seg) => {
    const key = String(seg.sequence_token || '').trim();
    if (!key) return;
    if (seg.latex_output !== undefined && seg.latex_output !== null && seg.latex_output !== '') {
      out[key] = seg.latex_output;
    }
  });
  return out;
}

function waitForPreviewApi(timeoutMs = 20000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    (function tick() {
      if (window.PracticeTestPreviewAPI && window.PracticeTestPreviewAPI.ready) {
        resolve(window.PracticeTestPreviewAPI);
        return;
      }
      if (Date.now() - start > timeoutMs) {
        reject(
          new Error(
            'Preview API failed to load. Hard-refresh the page (Cmd/Ctrl+Shift+R). If it still fails, the problem workspace scripts did not initialize.'
          )
        );
        return;
      }
      setTimeout(tick, 50);
    })();
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const cfg = window.STUDENT_TAKE_CONFIG || {};
  const statusEl = document.getElementById('student-take-status');
  const problemsEl = document.getElementById('student-take-problems');
  const submitBtn = document.getElementById('student-submit-btn');
  const resultSection = document.getElementById('student-take-result');
  const resultBody = document.getElementById('student-take-result-body');
  const timerEl = document.getElementById('student-take-timer');
  const timerValueEl = timerEl
    ? timerEl.querySelector('[data-role="timer-value"]')
    : null;
  const closeTimerEl = document.getElementById('student-take-close-timer');
  const closeTimerValueEl = closeTimerEl
    ? closeTimerEl.querySelector('[data-role="close-timer-value"]')
    : null;
  const focusLockOverlay = document.getElementById('student-focus-lock-overlay');
  const focusLockSubmitBtn = document.getElementById('student-focus-lock-submit');
  const focusLockStatusEl = document.getElementById('student-focus-lock-status');
  const saveStatusEl = document.getElementById('student-take-save-status');

  let problems = [];
  let autosaveTimer = null;
  let saving = false;
  let autosaveRetryTimer = null;
  let autosaveFailCount = 0;
  let closedHandling = false;
  let sessionEnded = false;
  let previewApi = null;
  let statusPollTimer = null;
  let backupAutosaveTimer = null;
  let countUpTimer = null;
  let countUpBaseElapsedMs = 0;
  let countUpAnchorMs = null;
  let forceSubmitAtMs = null;
  let countdownEndsAtMs = null;
  let showCountdownTimer = false;
  let forceSubmitReason = null;
  let closeCountdownTimer = null;
  let focusLockEnabled = false;
  let focusLocked = false;
  let focusLockRequestPending = false;
  let focusLeaveTimer = null;
  let internalNavigationPending = false;
  let focusTrapHandler = null;
  const focusClientActive = true;

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg || '';
  }

  function setSaveStatus(msg, kind) {
    if (!saveStatusEl) return;
    saveStatusEl.textContent = msg || '';
    saveStatusEl.classList.remove('is-saving', 'is-saved', 'is-error');
    if (kind) saveStatusEl.classList.add(kind);
  }

  function setFocusLockStatus(msg) {
    if (focusLockStatusEl) focusLockStatusEl.textContent = msg || '';
  }

  function trapFocusInOverlay() {
    if (!focusLockOverlay) return;
    const focusable = focusLockOverlay.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const list = Array.from(focusable).filter((el) => !el.disabled);
    if (!list.length) return;
    const first = list[0];
    const last = list[list.length - 1];
    first.focus();
    if (focusTrapHandler) {
      focusLockOverlay.removeEventListener('keydown', focusTrapHandler);
    }
    focusTrapHandler = (event) => {
      if (event.key !== 'Tab' || list.length === 0) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    focusLockOverlay.addEventListener('keydown', focusTrapHandler);
  }

  function showFocusLockOverlay() {
    focusLocked = true;
    document.body.classList.add('student-focus-lock-active');
    if (problemsEl) problemsEl.inert = true;
    if (submitBtn) submitBtn.disabled = true;
    if (focusLockOverlay) {
      focusLockOverlay.classList.add('is-visible');
      focusLockOverlay.setAttribute('aria-hidden', 'false');
      trapFocusInOverlay();
    }
    setFocusLockStatus('Awaiting your teacher’s release.');
  }

  function hideFocusLockOverlay() {
    focusLocked = false;
    document.body.classList.remove('student-focus-lock-active');
    if (problemsEl) problemsEl.inert = false;
    if (focusLockOverlay) {
      focusLockOverlay.classList.remove('is-visible');
      focusLockOverlay.setAttribute('aria-hidden', 'true');
      if (focusTrapHandler) {
        focusLockOverlay.removeEventListener('keydown', focusTrapHandler);
        focusTrapHandler = null;
      }
    }
    if (submitBtn && problems.length && !sessionEnded) submitBtn.disabled = false;
    setFocusLockStatus('');
  }

  function applyFocusLockState(data) {
    focusLockEnabled = data?.focus_lock_enabled === true;
    if (data?.focus_locked === true) {
      showFocusLockOverlay();
      return;
    }
    if (focusLocked) {
      hideFocusLockOverlay();
      setStatus('Your teacher unlocked the assessment. You may continue.');
    }
  }

  function formatElapsed(ms) {
    const totalSec = Math.max(0, Math.floor(ms / 1000));
    const hours = Math.floor(totalSec / 3600);
    const minutes = Math.floor((totalSec % 3600) / 60);
    const seconds = totalSec % 60;
    if (hours > 0) {
      return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }
    return `${minutes}:${String(seconds).padStart(2, '0')}`;
  }

  function stopCountUpTimer() {
    if (countUpTimer) {
      clearInterval(countUpTimer);
      countUpTimer = null;
    }
  }

  function stopCloseCountdown() {
    if (closeCountdownTimer) {
      clearInterval(closeCountdownTimer);
      closeCountdownTimer = null;
    }
    if (closeTimerEl) {
      closeTimerEl.hidden = true;
      closeTimerEl.classList.remove('is-visible');
    }
  }

  function tickCountUpTimer() {
    if (!timerValueEl || countUpAnchorMs == null) return;
    const elapsedMs =
      countUpBaseElapsedMs + (Date.now() - countUpAnchorMs);
    timerValueEl.textContent = formatElapsed(elapsedMs);
  }

  function parseWindowEndMs(iso, remainingSeconds) {
    if (iso) {
      const ms = Date.parse(iso);
      if (Number.isFinite(ms)) return ms;
    }
    // Number(null) === 0 in JS — treat null/undefined/'' as "no window",
    // otherwise retakes on closed assessments force-close immediately.
    if (remainingSeconds == null || remainingSeconds === '') {
      return null;
    }
    const rem = Number(remainingSeconds);
    if (Number.isFinite(rem) && rem >= 0) {
      return Date.now() + rem * 1000;
    }
    return null;
  }

  function formatCountdown(remainingSec) {
    if (remainingSec >= 60) {
      const minutes = Math.floor(remainingSec / 60);
      return `${minutes} min`;
    }
    return `${Math.max(0, remainingSec)} sec`;
  }

  function tickCloseCountdown(api) {
    if (sessionEnded) return;
    const nowMs = Date.now();
    if (forceSubmitAtMs != null && forceSubmitAtMs - nowMs <= 0) {
      stopCloseCountdown();
      handleForcedClose(api, { reason: forceSubmitReason });
      return;
    }

    if (!showCountdownTimer || countdownEndsAtMs == null || !closeTimerValueEl) {
      if (closeTimerEl) {
        closeTimerEl.hidden = true;
        closeTimerEl.classList.remove('is-visible');
      }
      return;
    }

    const remainingSec = Math.max(0, Math.ceil((countdownEndsAtMs - nowMs) / 1000));
    if (closeTimerEl) {
      closeTimerEl.hidden = false;
      closeTimerEl.classList.add('is-visible');
    }
    closeTimerValueEl.textContent = formatCountdown(remainingSec);
  }

  function syncWindowCloseCountdown(api, data) {
    const nextForceSubmitAt = parseWindowEndMs(
      data?.force_submit_at,
      data?.force_submit_remaining_seconds
    );
    const nextCountdownEnd = parseWindowEndMs(
      data?.countdown_ends_at,
      data?.countdown_remaining_seconds
    );
    forceSubmitAtMs = nextForceSubmitAt;
    countdownEndsAtMs = nextCountdownEnd;
    showCountdownTimer = data?.show_countdown_timer === true;
    forceSubmitReason = data?.force_submit_reason || null;

    if (forceSubmitAtMs == null && countdownEndsAtMs == null) {
      stopCloseCountdown();
      return;
    }
    tickCloseCountdown(api);
    if (!closeCountdownTimer && !sessionEnded) {
      closeCountdownTimer = window.setInterval(() => tickCloseCountdown(api), 250);
    }
  }

  function startCountUpTimer(startedAtIso, showTimer, elapsedSeconds) {
    const shouldShow = showTimer === true || cfg.showCountUpTimer === true;
    if (!shouldShow || !timerEl || !timerValueEl) return;

    // Prefer server-computed elapsed so naive/UTC timestamp parsing cannot
    // leave the display stuck at 0:00 when clocks/timezones disagree.
    let baseElapsedMs = 0;
    const serverElapsed = Number(elapsedSeconds);
    if (Number.isFinite(serverElapsed) && serverElapsed >= 0) {
      baseElapsedMs = serverElapsed * 1000;
    } else {
      const startedMs = Date.parse(startedAtIso || '');
      if (Number.isFinite(startedMs)) {
        baseElapsedMs = Math.max(0, Date.now() - startedMs);
      }
    }

    countUpBaseElapsedMs = baseElapsedMs;
    countUpAnchorMs = Date.now();
    timerEl.hidden = false;
    timerEl.classList.add('is-visible');
    tickCountUpTimer();
    stopCountUpTimer();
    countUpTimer = window.setInterval(tickCountUpTimer, 250);
  }

  function collectPayload(api) {
    const cards = Array.from(problemsEl.querySelectorAll('.practice-problem-card'));
    return {
      focus_client_active: focusClientActive,
      problems: cards.map((card, idx) => {
        const problem = problems[idx] || {};
        const previewRoot = card.querySelector('[data-role="preview"]');
        return {
          problem_row_id: problem.problem_row_id,
          student_answers: api.captureAnswers(previewRoot),
        };
      }),
    };
  }

  function disableEditing() {
    if (submitBtn) submitBtn.disabled = true;
    if (problemsEl) {
      problemsEl.querySelectorAll('input, textarea, button, select').forEach((el) => {
        el.disabled = true;
      });
    }
  }

  function showClosedResult(message) {
    problemsEl.style.display = 'none';
    const footer = document.querySelector('.student-take-footer');
    if (footer) footer.style.display = 'none';
    if (resultSection) resultSection.hidden = false;
    if (resultBody) {
      resultBody.innerHTML =
        `<p><strong>${escapeHtml(message)}</strong></p>` +
        `<p style="margin-top:8px;color:#64748b;">` +
        `Your entered answers were submitted automatically.</p>`;
    }
    setStatus('Assessment closed.');
  }

  function redirectToAssessmentsSoon() {
    const url = cfg.assessmentsUrl || '/';
    window.setTimeout(() => {
      window.location.href = url;
    }, 2500);
  }

  async function autosave(api) {
    if (sessionEnded || focusLocked || saving || !cfg.autosaveUrl || !api) return null;
    saving = true;
    setSaveStatus('Saving…', 'is-saving');
    try {
      const res = await fetch(cfg.autosaveUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify(collectPayload(api)),
      });
      let data = {};
      try {
        data = await res.json();
      } catch (_) {
        data = {};
      }
      if (!res.ok && data.code !== 'focus_locked' && data.code !== 'assessment_closed') {
        throw new Error(data.error || `Autosave failed (${res.status}).`);
      }
      // Do not key off bare `closed` — class assessments stay closed during retakes.
      // Only end the session when the server says this take was finalized / forbidden.
      if (
        data.code === 'assessment_closed'
        || data.force_close === true
        || data.submitted === true
        || data.taking_allowed === false
      ) {
        await handleForcedClose(api, {
          alreadyFinalized: true,
          reason: data.force_submit_reason || forceSubmitReason,
        });
      } else if (data.code === 'focus_locked' || data.focus_locked === true) {
        showFocusLockOverlay();
      }
      autosaveFailCount = 0;
      setSaveStatus('Saved', 'is-saved');
      return data;
    } catch (err) {
      console.warn('autosave failed', err);
      autosaveFailCount += 1;
      setSaveStatus(
        'Not saved — retrying… Tap Submit only after “Saved” appears.',
        'is-error'
      );
      clearTimeout(autosaveRetryTimer);
      const delay = Math.min(8000, 1000 * autosaveFailCount);
      autosaveRetryTimer = setTimeout(() => autosave(api), delay);
      return null;
    } finally {
      saving = false;
    }
  }

  function scheduleAutosave(api) {
    if (sessionEnded || focusLocked) return;
    clearTimeout(autosaveTimer);
    autosaveTimer = setTimeout(() => autosave(api), 1200);
  }

  async function handleForcedClose(api, opts = {}) {
    if (closedHandling || sessionEnded) return;
    closedHandling = true;
    sessionEnded = true;
    const answerSnapshot = api ? collectPayload(api) : null;
    clearTimeout(autosaveTimer);
    if (statusPollTimer) clearInterval(statusPollTimer);
    if (backupAutosaveTimer) clearInterval(backupAutosaveTimer);
    stopCountUpTimer();
    stopCloseCountdown();
    disableEditing();
    const closeMessage =
      opts.reason === 'time_limit'
        ? 'Your time limit has ended.'
        : 'The assessment window has ended.';
    setStatus(`${closeMessage} Submitting your answers…`);

    if (!opts.alreadyFinalized && api && cfg.submitUrl) {
      try {
        const forcedPayload = answerSnapshot || { problems: [] };
        forcedPayload.force_submit = true;
        const response = await fetch(cfg.submitUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
          },
          body: JSON.stringify(forcedPayload),
        });
        if (!response.ok) {
          throw new Error(`Forced submission failed (${response.status}).`);
        }
      } catch (err) {
        console.warn('forced submit failed', err);
        sessionEnded = false;
        closedHandling = false;
        setStatus('Your time ended, but submission failed. Keep this page open while it retries.');
        window.setTimeout(() => handleForcedClose(api, opts), 1500);
        return;
      }
    }

    showClosedResult(closeMessage);
    redirectToAssessmentsSoon();
  }

  async function pollTakeStatus(api) {
    if (sessionEnded || !cfg.statusUrl) return;
    try {
      const res = await fetch(cfg.statusUrl, {
        headers: { Accept: 'application/json' },
        credentials: 'same-origin',
      });
      const data = await res.json();
      if (!res.ok || !data.success) return;
      applyFocusLockState(data);
      // Teacher may have just enabled lock while this tab is not visible.
      if (
        data.focus_lock_enabled === true
        && data.focus_locked !== true
        && document.visibilityState !== 'visible'
      ) {
        requestFocusLock(api);
      }
      // End only when THIS student may no longer continue. Class `closed` alone
      // must not kill an authorized per-student retake.
      const shouldForceClose =
        data.taking_allowed === false
        || data.force_close === true
        || (data.closed === true && data.taking_allowed !== true);
      if (shouldForceClose) {
        await handleForcedClose(api, {
          alreadyFinalized: data.submitted === true,
          reason: data.force_submit_reason,
        });
        return;
      }
      syncWindowCloseCountdown(api, data);
    } catch (err) {
      console.warn('take status poll failed', err);
    }
  }

  async function requestFocusLock(api) {
    if (
      !focusLockEnabled
      || focusLocked
      || focusLockRequestPending
      || sessionEnded
      || !cfg.focusLockUrl
      || !api
    ) {
      return;
    }
    focusLockRequestPending = true;
    try {
      const res = await fetch(cfg.focusLockUrl, {
        method: 'POST',
        credentials: 'same-origin',
        keepalive: true,
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify(collectPayload(api)),
      });
      const data = await res.json();
      if (res.ok && data.focus_locked === true) {
        showFocusLockOverlay();
      }
    } catch (err) {
      console.warn('focus lock request failed', err);
    } finally {
      focusLockRequestPending = false;
    }
  }

  function showSubmittedResult(submitData) {
    sessionEnded = true;
    hideFocusLockOverlay();
    if (statusPollTimer) clearInterval(statusPollTimer);
    if (backupAutosaveTimer) clearInterval(backupAutosaveTimer);
    stopCountUpTimer();
    stopCloseCountdown();
    problemsEl.style.display = 'none';
    const footer = document.querySelector('.student-take-footer');
    if (footer) footer.style.display = 'none';
    if (resultSection) resultSection.hidden = false;
    // Never show numeric scores on the take page after submit — release is
    // teacher-controlled and only after the assessment is closed.
    if (resultBody) {
      const message =
        submitData.message ||
        'Your assessment was submitted successfully.';
      resultBody.innerHTML =
        `<p>${escapeHtml(message)}</p>` +
        '<p style="margin-top:8px;color:#64748b;">Your score will be available after your teacher finishes grading and releases scores.</p>';
    }
    setStatus('Submitted.');
  }

  async function loadAndRender() {
    try {
      setStatus('Loading assessment…');
      const res = await fetch(cfg.startUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken'),
        },
        body: '{}',
      });
      const data = await res.json();
      // Only treat as closed when start was rejected — success payloads must not
      // end a retake just because the class assessment row is closed.
      if (!res.ok && (data.code === 'assessment_closed' || data.closed)) {
        showClosedResult('This assessment has been closed.');
        redirectToAssessmentsSoon();
        return;
      }
      if (!res.ok || !data.success) {
        throw new Error(data.error || 'Failed to start assessment.');
      }
      problems = Array.isArray(data.problems) ? data.problems : [];
      if (!problems.length) {
        setStatus('This assessment has no problems available.');
        return;
      }

      startCountUpTimer(
        data.started_at,
        data.show_count_up_timer === true || cfg.showCountUpTimer === true,
        data.elapsed_seconds
      );

      const api = await waitForPreviewApi();
      previewApi = api;
      syncWindowCloseCountdown(api, data);
      if (sessionEnded) return;
      problemsEl.innerHTML = '';
      problems.forEach((problem, idx) => {
        const slot = problem.slot_index || idx + 1;
        const card = document.createElement('article');
        card.className = 'practice-problem-card';
        card.dataset.slotIndex = String(slot);
        card.dataset.problemRowId = String(problem.problem_row_id || '');

        const metaBits = [];
        if (problem.section_name) {
          metaBits.push(
            `<span class="practice-problem-chip">${escapeHtml(problem.section_name)}</span>`
          );
        }
        if (problem.from_problem_set) {
          metaBits.push(
            `<span class="practice-problem-chip">From set: ${escapeHtml(problem.from_problem_set)}</span>`
          );
        }

        card.innerHTML = `
          <div class="practice-problem-meta">
            <h3 class="practice-problem-title">${slot}. ${escapeHtml(problem.title || `Question ${slot}`)}</h3>
            ${metaBits.join('')}
          </div>
          <div class="practice-preview-target" data-role="preview"></div>
          <div class="practice-stub-host" data-role="stubs" aria-hidden="true"></div>
        `;
        problemsEl.appendChild(card);

        const previewTarget = card.querySelector('[data-role="preview"]');
        const stubHost = card.querySelector('[data-role="stubs"]');
        const segments = problem.loaded_segments || [];
        api.buildStubCards(stubHost, segments);
        api.renderPreview(previewTarget, problem.body_html || '<p><br></p>', {
          cardScope: stubHost,
          segmentMap: buildSegmentMap(segments),
          latexByToken: buildLatexByToken(segments),
          studentAnswers: problem.student_answers || {},
          previewNamePrefix: `slot${slot}`,
        });
        previewTarget.addEventListener('input', () => scheduleAutosave(api));
        previewTarget.addEventListener('change', () => scheduleAutosave(api));
      });

      setStatus(`${problems.length} question${problems.length === 1 ? '' : 's'} ready.`);
      if (submitBtn) submitBtn.disabled = false;
      applyFocusLockState(data);

      backupAutosaveTimer = setInterval(() => autosave(api), 20000);
      statusPollTimer = setInterval(() => pollTakeStatus(api), 3000);
      pollTakeStatus(api);

      if (submitBtn) {
        submitBtn.addEventListener('click', async () => {
          if (sessionEnded) return;
          if (!(await mapConfirm({
            title: 'Submit assessment',
            message: 'Submit this assessment? You will not be able to change answers after submitting.',
            confirmLabel: 'Submit',
          }))) {
            return;
          }
          submitBtn.disabled = true;
          setStatus('Submitting…');
          clearTimeout(autosaveTimer);
          await autosave(api);
          if (sessionEnded) return;
          try {
            const submitRes = await fetch(cfg.submitUrl, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
              },
              body: JSON.stringify(collectPayload(api)),
            });
            const submitData = await submitRes.json();
            if (!submitRes.ok || !submitData.success) {
              throw new Error(submitData.error || 'Submit failed.');
            }
            showSubmittedResult(submitData);
          } catch (err) {
            console.error(err);
            setStatus(err.message || 'Submit failed.');
            submitBtn.disabled = false;
          }
        });
      }

      document.addEventListener('click', (event) => {
        const link = event.target.closest('a[href]');
        if (!link) return;
        try {
          const target = new URL(link.href, window.location.href);
          if (target.origin === window.location.origin) {
            internalNavigationPending = true;
          }
        } catch (_) {
          // Ignore malformed/non-navigation hrefs.
        }
      }, true);

      document.addEventListener('submit', (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        let target;
        try {
          target = new URL(form.action || window.location.href, window.location.href);
        } catch (_) {
          return;
        }
        if (target.origin !== window.location.origin) return;
        const isLogout = form.classList.contains('nav-account-logout-form');
        if (!isLogout) {
          internalNavigationPending = true;
          return;
        }
        if (!focusLockEnabled || focusLocked || sessionEnded) return;
        event.preventDefault();
        requestFocusLock(api).finally(() => {
          form.submit();
        });
      }, true);

      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
          clearTimeout(focusLeaveTimer);
          internalNavigationPending = false;
          return;
        }
        if (internalNavigationPending) return;
        clearTimeout(focusLeaveTimer);
        focusLeaveTimer = window.setTimeout(() => requestFocusLock(api), 300);
      });

      window.addEventListener('assessment:focus-leave', () => {
        if (!internalNavigationPending) requestFocusLock(api);
      });

      window.addEventListener('pagehide', () => {
        if (!internalNavigationPending) requestFocusLock(api);
      });

      if (focusLockSubmitBtn) {
        focusLockSubmitBtn.addEventListener('click', async () => {
          if (!focusLocked || !cfg.submitLockedUrl || sessionEnded) return;
          if (!(await mapConfirm({
            title: 'Submit assessment',
            message: 'Submit your currently saved answers? The assessment cannot be reopened after submission.',
            confirmLabel: 'Submit',
          }))) {
            return;
          }
          focusLockSubmitBtn.disabled = true;
          setFocusLockStatus('Submitting your saved answers…');
          try {
            const res = await fetch(cfg.submitLockedUrl, {
              method: 'POST',
              credentials: 'same-origin',
              headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
              },
              body: '{}',
            });
            const submitData = await res.json();
            if (!res.ok || !submitData.success) {
              throw new Error(submitData.error || 'Submission failed.');
            }
            showSubmittedResult(submitData);
          } catch (err) {
            setFocusLockStatus(err.message || 'Submission failed.');
            focusLockSubmitBtn.disabled = false;
          }
        });
      }
    } catch (err) {
      console.error(err);
      setStatus(err.message || 'Failed to load assessment.');
    }
  }

  loadAndRender();
});
