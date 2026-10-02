/**
 * @fileoverview Dashboard Page Controller
 * Handles today's summary, real-time portal checks, attendance states, and safety decisions.
 */

import { API } from '../api.js';

export class DashboardController {
  constructor() {
    this.currentData = null;
    this.latestCheck = null;
    this.recentNotifications = [];
    this.sessionStatus = null;
    this.appSettings = null;
    this.isRunningCheck = false;
    this.lastActiveElement = null;

    this.els = {
      loading: document.getElementById('dashboard-loading'),
      error: document.getElementById('dashboard-error'),
      errorText: document.getElementById('dashboard-error-text'),
      content: document.getElementById('dashboard-content'),
      
      // Hero Card elements (preserved for existing tests and contracts)
      heroCard: document.getElementById('dashboard-hero-card'),
      heroDateBadge: document.getElementById('hero-date-text'),
      heroStatusBadge: document.getElementById('hero-status-badge'),
      heroTitle: document.getElementById('hero-title'),
      heroDesc: document.getElementById('hero-desc'),
      heroNoteContainer: document.getElementById('hero-note-container'),
      inputConfirmNote: document.getElementById('input-confirm-note'),
      btnConfirm: document.getElementById('btn-confirm-attendance'),
      btnConfirmText: document.getElementById('btn-confirm-text'),
      btnOpenRunCheck: document.getElementById('btn-open-run-check'),
      
      // Metric Stats Grid elements
      statCheckStatus: document.getElementById('stat-check-status'),
      statCheckTime: document.getElementById('stat-check-time'),
      statConfirmationStatus: document.getElementById('stat-confirmation-status'),
      statConfirmationHint: document.getElementById('stat-confirmation-hint'),
      statSubjectBreakdown: document.getElementById('stat-subject-breakdown'),
      statSubjectSubtext: document.getElementById('stat-subject-subtext'),
      statSessionStatus: document.getElementById('stat-session-status'),
      statSessionHint: document.getElementById('stat-session-hint'),

      // Schedule & Records lists
      holidayCard: document.getElementById('dashboard-holiday-card'),
      expectedClasses: document.getElementById('dashboard-expected-classes'),
      attendanceRecords: document.getElementById('dashboard-attendance-records'),
      recentChecks: document.getElementById('dashboard-recent-checks'),
      notificationsFeed: document.getElementById('dashboard-notifications-feed'),
      
      btnRetry: document.getElementById('btn-retry-dashboard'),
      btnQuickManageSubjects: document.getElementById('btn-quick-manage-subjects'),

      // Manual Run Check Modal elements
      modalRunCheck: document.getElementById('modal-run-check'),
      btnCloseRunCheckModal: document.getElementById('btn-close-run-check-modal'),
      btnCancelRunCheck: document.getElementById('btn-cancel-run-check'),
      btnExecuteRunCheck: document.getElementById('btn-execute-run-check'),
      btnExecuteRunCheckText: document.getElementById('btn-execute-run-check-text'),
      inputRunCheckDate: document.getElementById('input-run-check-date'),
      runCheckProgress: document.getElementById('run-check-progress'),
      runCheckResult: document.getElementById('run-check-result'),
      runCheckDryRunBadge: document.getElementById('run-check-dryrun-badge'),
      runCheckDryRunText: document.getElementById('run-check-dryrun-text'),
      runCheckSessionWarning: document.getElementById('run-check-session-warning'),
      heroConfirmationMeta: document.getElementById('hero-confirmation-meta'),
      heroConfirmationMetaText: document.getElementById('hero-confirmation-meta-text'),
    };

    this.isLoading = false;
    this.initEvents();
  }

  initEvents() {
    if (this.els.btnRetry) {
      this.els.btnRetry.addEventListener('click', () => this.loadData());
    }
    if (this.els.btnQuickManageSubjects) {
      this.els.btnQuickManageSubjects.addEventListener('click', () => {
        const subjectsTab = document.getElementById('tab-subjects') || document.querySelector('[data-route="subjects"]');
        if (subjectsTab) {
          subjectsTab.click();
        } else if (window.App && typeof window.App.navigate === 'function') {
          window.App.navigate('subjects');
        }
      });
    }
    if (this.els.btnConfirm) {
      this.els.btnConfirm.addEventListener('click', () => this.handleConfirmation());
    }
    if (this.els.btnOpenRunCheck) {
      this.els.btnOpenRunCheck.addEventListener('click', () => this.openRunCheckModal());
    }
    if (this.els.btnCloseRunCheckModal) {
      this.els.btnCloseRunCheckModal.addEventListener('click', () => this.closeRunCheckModal());
    }
    if (this.els.btnCancelRunCheck) {
      this.els.btnCancelRunCheck.addEventListener('click', () => this.closeRunCheckModal());
    }
    if (this.els.btnExecuteRunCheck) {
      this.els.btnExecuteRunCheck.addEventListener('click', () => this.executeManualCheck());
    }

    // Modal backdrop click handling
    if (this.els.modalRunCheck) {
      this.els.modalRunCheck.addEventListener('click', (e) => {
        if (e.target === this.els.modalRunCheck && !this.isRunningCheck) {
          this.closeRunCheckModal();
        }
      });
    }

    // Keyboard Escape to dismiss modal safely & Tab focus trap
    window.addEventListener('keydown', (e) => {
      if (this.els.modalRunCheck && this.els.modalRunCheck.style.display !== 'none') {
        if (e.key === 'Escape' && !this.isRunningCheck) {
          this.closeRunCheckModal();
          return;
        }
        if (e.key === 'Tab') {
          const focusable = this.els.modalRunCheck.querySelectorAll(
            'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'
          );
          if (focusable.length === 0) return;
          const firstEl = focusable[0];
          const lastEl = focusable[focusable.length - 1];
          if (e.shiftKey && document.activeElement === firstEl) {
            e.preventDefault();
            lastEl.focus();
          } else if (!e.shiftKey && document.activeElement === lastEl) {
            e.preventDefault();
            firstEl.focus();
          }
        }
      }
    });
  }

  async loadData() {
    if (this.isLoading) return;
    this.isLoading = true;
    this.showState('loading');
    try {
      const [todayRes, latestCheckRes, notifsRes, sessionRes, settingsRes] = await Promise.allSettled([
        API.dashboard.getToday(),
        API.checks.getLatest(),
        API.checks.getNotifications(5),
        API.settings.getSessionStatus(),
        API.settings.read(),
      ]);

      if (todayRes.status === 'rejected') {
        throw todayRes.reason;
      }

      this.currentData = todayRes.value;
      this.latestCheck = latestCheckRes.status === 'fulfilled' ? latestCheckRes.value?.check : null;
      this.recentNotifications = notifsRes.status === 'fulfilled' ? (notifsRes.value || []) : [];
      this.sessionStatus = sessionRes.status === 'fulfilled' ? sessionRes.value : null;
      this.appSettings = settingsRes.status === 'fulfilled' ? settingsRes.value : null;

      this.render();
      this.showState('content');
    } catch (err) {
      if (this.els.errorText) {
        this.els.errorText.innerText = err.message || 'Unknown error occurred while fetching dashboard data.';
      }
      this.showState('error');
    } finally {
      this.isLoading = false;
    }
  }

  showState(state) {
    if (this.els.loading) this.els.loading.style.display = state === 'loading' ? 'block' : 'none';
    if (this.els.error) this.els.error.style.display = state === 'error' ? 'block' : 'none';
    if (this.els.content) this.els.content.style.display = state === 'content' ? 'block' : 'none';
  }

  render() {
    const data = this.currentData;
    if (!data) return;

    // 1. Date formatting
    if (this.els.heroDateBadge) {
      const d = parseLocalDate(data.today);
      this.els.heroDateBadge.innerText = d.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
    }

    // 2. Confirmation Status (Hero Card)
    this.renderConfirmationStatus(data.is_confirmed);

    // 3. Holiday Status
    if (this.els.holidayCard) {
      this.els.holidayCard.style.display = data.is_holiday ? 'block' : 'none';
      if (data.is_holiday) {
        const d = parseLocalDate(data.today);
        const monthStr = d.toLocaleDateString(undefined, { month: 'short' }).toUpperCase();
        const dayStr = String(d.getDate()).padStart(2, '0');
        const mEl = document.getElementById('dashboard-holiday-month');
        const dEl = document.getElementById('dashboard-holiday-day');
        const tEl = document.getElementById('dashboard-holiday-title');
        if (mEl) mEl.innerText = monthStr;
        if (dEl) dEl.innerText = dayStr;
        if (tEl) tEl.innerText = 'Official Holiday Exemption';
      }
    }

    // Header actions dynamic badges
    const modeBadge = document.getElementById('dashboard-mode-badge');
    const modeText = document.getElementById('dashboard-mode-badge-text');
    if (modeBadge && modeText) {
      const isDry = this.appSettings ? this.appSettings.dry_run : true;
      modeBadge.className = isDry ? 'badge badge-warning' : 'badge badge-danger';
      modeText.innerText = isDry ? 'Sandbox: Safe Mode' : 'Live: Sending Active';
    }

    const adapterText = document.getElementById('dashboard-adapter-badge-text');
    if (adapterText) {
      const adName = (this.appSettings?.portal_adapter || 'pwioi').toUpperCase();
      adapterText.innerText = `Adapter: ${adName} Active`;
    }

    // 4. Expected Classes
    this.renderExpectedClasses(data.expected_classes);

    // 5. Attendance Records
    this.renderAttendanceRecords(data.attendance_records);

    // 6. Metric Stats
    this.renderMetricStats();

    // 7. Recent Check Runs
    this.renderRecentChecks();

    // 8. Recent Notifications & Safety Decisions
    this.renderNotificationsFeed();
  }

  renderConfirmationStatus(isConfirmed) {
    if (!this.els.heroCard) return;

    if (isConfirmed) {
      this.els.heroCard.classList.add('confirmed');
      if (this.els.heroStatusBadge) {
        this.els.heroStatusBadge.className = 'badge badge-success';
        this.els.heroStatusBadge.innerHTML = '<span class="badge-dot"></span>Confirmed for Today';
      }
      if (this.els.heroTitle) this.els.heroTitle.innerText = 'Attendance Confirmed for Today';
      if (this.els.heroDesc) this.els.heroDesc.innerText = 'Your attendance check-in has been recorded. The AttendFlow automated scheduler safely verifies college portal records post-lecture before the 5:00 PM IST correction cutoff.';
      
      if (this.els.btnConfirm) {
        this.els.btnConfirm.disabled = true;
        this.els.btnConfirm.classList.add('btn-confirmed');
      }
      if (this.els.btnConfirmText) this.els.btnConfirmText.innerText = 'Attendance Confirmed (Logged)';
      if (this.els.heroNoteContainer) this.els.heroNoteContainer.style.display = 'none';
      if (this.els.heroConfirmationMeta) this.els.heroConfirmationMeta.style.display = 'flex';
    } else {
      this.els.heroCard.classList.remove('confirmed');
      if (this.els.heroStatusBadge) {
        this.els.heroStatusBadge.className = 'badge badge-warning';
        this.els.heroStatusBadge.innerHTML = '<span class="badge-dot pulse"></span>Awaiting Confirmation';
      }
      if (this.els.heroTitle) this.els.heroTitle.innerText = 'Did you attend college today?';
      if (this.els.heroDesc) this.els.heroDesc.innerText = 'Mark your attendance so the automated scheduler knows to verify your portal records post-lecture. AttendFlow reconciles attendance before the critical 5:00 PM IST correction cutoff.';
      
      if (this.els.btnConfirm) {
        this.els.btnConfirm.disabled = false;
        this.els.btnConfirm.classList.remove('btn-confirmed');
      }
      if (this.els.btnConfirmText) this.els.btnConfirmText.innerText = 'I WENT TO COLLEGE';
      if (this.els.heroNoteContainer) this.els.heroNoteContainer.style.display = 'block';
      if (this.els.heroConfirmationMeta) this.els.heroConfirmationMeta.style.display = 'none';
    }
  }

  renderMetricStats() {
    // Stat 1: Today's Check Status
    if (this.els.statCheckStatus) {
      if (this.latestCheck) {
        const isSuccess = this.latestCheck.status === 'SUCCESS';
        this.els.statCheckStatus.innerText = isSuccess ? 'SUCCESS' : this.latestCheck.status;
        this.els.statCheckStatus.style.color = 'var(--primary)';
        if (this.els.statCheckTime) {
          const checkedTime = new Date(this.latestCheck.checked_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
          this.els.statCheckTime.innerText = `Checked at ${checkedTime} (${this.latestCheck.adapter_name})`;
        }
      } else {
        this.els.statCheckStatus.innerText = 'Pending';
        this.els.statCheckStatus.style.color = 'var(--text-muted)';
        if (this.els.statCheckTime) {
          this.els.statCheckTime.innerText = 'No check executed today';
        }
      }
    }

    // Stat 2: Confirmation
    if (this.els.statConfirmationStatus) {
      const isConfirmed = this.currentData?.is_confirmed;
      this.els.statConfirmationStatus.innerText = isConfirmed ? 'CONFIRMED' : 'Awaiting';
      this.els.statConfirmationStatus.style.color = 'var(--primary)';
      if (this.els.statConfirmationHint) {
        this.els.statConfirmationHint.innerText = 'Explicit student check-in';
      }
    }

    // Stat 3: Academic Attendance / Today's Portal Extraction
    // Development Safety: Never display synthetic attendance information.
    if (this.els.statSubjectBreakdown) {
      const acadRate = this.currentData?.academic_attendance_rate;
      const acadAtt = this.currentData?.academic_attended_classes;
      const acadTot = this.currentData?.academic_total_classes;
      const records = this.currentData?.attendance_records || [];

      if (typeof acadRate === 'number') {
        this.els.statSubjectBreakdown.innerHTML = `${acadRate.toFixed(1)}% <span style="font-size: 0.85rem; font-weight: 500; color: var(--text-muted); margin-left: 0.25rem;">Rate</span>`;
        if (this.els.statSubjectSubtext) {
          if (acadAtt !== null && acadTot !== null) {
            this.els.statSubjectSubtext.innerText = `${acadAtt} of ${acadTot} classes attended`;
          } else {
            this.els.statSubjectSubtext.innerText = 'Portal verified attendance';
          }
        }
      } else if (records.length > 0) {
        let present = 0, absent = 0, unknown = 0;
        records.forEach(r => {
          if (r.status === 'PRESENT') present++;
          else if (r.status === 'ABSENT') absent++;
          else unknown++;
        });
        this.els.statSubjectBreakdown.innerHTML = `${records.length} Verified <span style="font-size: 0.85rem; font-weight: 500; color: var(--text-muted); margin-left: 0.25rem;">Today</span>`;
        if (this.els.statSubjectSubtext) {
          this.els.statSubjectSubtext.innerText = `${present} Present · ${absent} Absent · ${unknown} Pending`;
        }
      } else {
        this.els.statSubjectBreakdown.innerText = 'Awaiting Sync';
        if (this.els.statSubjectSubtext) {
          this.els.statSubjectSubtext.innerText = 'Waiting for portal synchronization';
        }
      }
    }

    // Stat 4: Session Status
    if (this.els.statSessionStatus) {
      const isAuth = this.sessionStatus?.is_authenticated;
      this.els.statSessionStatus.innerText = isAuth ? 'VALID & READY' : 'LOGIN REQUIRED';
      this.els.statSessionStatus.style.color = 'var(--primary)';
      if (this.els.statSessionHint) {
        const adapterName = (this.appSettings?.portal_adapter || 'pwioi').toLowerCase();
        this.els.statSessionHint.innerText = `${adapterName} token verified`;
      }
    }
  }

  async handleConfirmation() {
    if (!this.els.btnConfirm) return;
    this.els.btnConfirm.disabled = true;
    if (this.els.btnConfirmText) this.els.btnConfirmText.innerText = 'Confirming...';
    
    const note = this.els.inputConfirmNote ? this.els.inputConfirmNote.value.trim() : '';
    const today = this.currentData ? this.currentData.today : new Date().toISOString().split('T')[0];
    
    try {
      await API.confirmations.confirm(today, note || undefined);
      this.renderConfirmationStatus(true);
      if (this.currentData) this.currentData.is_confirmed = true;
      this.renderMetricStats();
      
      window.dispatchEvent(new CustomEvent('app-alert', { 
        detail: { message: 'Attendance confirmed successfully!', type: 'success' } 
      }));
    } catch (err) {
      window.dispatchEvent(new CustomEvent('app-alert', { 
        detail: { message: `Failed to confirm: ${err.message}`, type: 'error' } 
      }));
      this.els.btnConfirm.disabled = false;
      if (this.els.btnConfirmText) this.els.btnConfirmText.innerText = 'I WENT TO COLLEGE';
    }
  }

  renderExpectedClasses(classes) {
    if (!this.els.expectedClasses) return;
    if (!classes || classes.length === 0) {
      this.els.expectedClasses.innerHTML = `
        <div style="padding: 1.5rem; text-align: center; color: var(--text-muted); font-size: 0.9rem;">
          No classes scheduled for today.
        </div>
      `;
      return;
    }
    
    let html = '<div class="table-responsive"><table class="data-table"><tbody>';
    for (const c of classes) {
      const mappingPill = c.professor_email 
        ? `<span class="badge badge-success" style="font-size: 0.7rem; padding: 0.2rem 0.5rem;"><span class="badge-dot"></span>Configured</span>`
        : `<span class="badge badge-warning" style="font-size: 0.7rem; padding: 0.2rem 0.5rem;">Unmapped</span>`;
      html += `
        <tr>
          <td>
            <strong>${escapeHtml(c.code)}</strong>
            <div style="font-size:0.8rem; color:var(--text-muted);">${escapeHtml(c.name)}</div>
          </td>
          <td style="text-align:right;">
            <div style="font-weight: 500; color: var(--text-main); font-size: 0.85rem;">${escapeHtml(c.professor_name || 'No Instructor')}</div>
            <div style="margin-top: 0.2rem;">${mappingPill}</div>
          </td>
        </tr>
      `;
    }
    html += '</tbody></table></div>';
    this.els.expectedClasses.innerHTML = html;
  }

  renderAttendanceRecords(records) {
    const countBadge = document.getElementById('dashboard-records-count-badge');
    if (countBadge) {
      if (records && records.length > 0) {
        countBadge.className = 'badge badge-success';
        countBadge.innerHTML = `<span class="badge-dot"></span>Reconciled: ${records.length} Records`;
      } else {
        countBadge.className = 'badge badge-neutral';
        countBadge.innerHTML = `<span class="badge-dot"></span>0 Records Today`;
      }
    }

    if (!this.els.attendanceRecords) return;
    if (!records || records.length === 0) {
      this.els.attendanceRecords.innerHTML = `
        <div style="padding: 2rem; text-align: center; color: var(--text-muted); font-size: 0.875rem;">
          No portal records extracted for today yet. Use "Run Manual Portal Verification" above to trigger a check.
        </div>
      `;
      return;
    }
    
    let html = '<div class="table-responsive"><table class="data-table"><thead><tr><th>Course Code &amp; Title</th><th>Timeline</th><th>Portal Status</th><th style="text-align:right;">Verification Decision</th></tr></thead><tbody>';
    for (let idx = 0; idx < records.length; idx++) {
      const r = records[idx];
      let badgeClass = 'badge-neutral';
      let statusStr = 'Unknown';
      let decisionPill = '<span class="badge badge-neutral">No Action</span>';
      
      if (r.status === 'PRESENT') { 
        badgeClass = 'badge-success'; 
        statusStr = 'PRESENT'; 
        decisionPill = '<span class="badge badge-neutral" style="font-size: 0.72rem; background: var(--neutral-light); color: var(--text-main); font-weight: 600;">✓ Verified (No Action)</span>';
      } else if (r.status === 'ABSENT') { 
        badgeClass = 'badge-danger'; 
        statusStr = 'ABSENT'; 
        decisionPill = '<span class="badge badge-danger" style="font-size: 0.72rem;">⚠️ Discrepancy Alert</span>';
      } else if (r.status === 'NOT_MARKED') { 
        badgeClass = 'badge-warning'; 
        statusStr = 'NOT MARKED'; 
        decisionPill = '<span class="badge badge-warning" style="font-size: 0.72rem;">Fails Closed (Safe)</span>';
      } else if (r.status === 'UNKNOWN') {
        badgeClass = 'badge-warning';
        statusStr = 'UNKNOWN';
        decisionPill = '<span class="badge badge-warning" style="font-size: 0.72rem;">Fails Closed (Safe)</span>';
      }

      const timelineText = r.period ? `Period ${r.period}` : 'Period 1';
      
      const courseTitleMap = {
        '306JWD': 'Web Development',
        '304ELS': 'Essential Language Skills',
        '302OPS': 'Operating System',
        '304VEP': 'Data Visualization & PowerBI',
        '301ADS': 'Advance Data Structures & Algorithms',
        '303PDS': 'Python for Data Science',
      };
      const displayTitle = courseTitleMap[r.subject_code] || r.subject_name || r.raw_status || 'Enrolled Course';
      
      html += `
        <tr>
          <td>
            <div style="font-weight: 700; font-size: 0.85rem; color: var(--text-main);">${escapeHtml(r.subject_code)}</div>
            <div style="font-size: 0.775rem; color: var(--text-muted); margin-top: 0.1rem;">${escapeHtml(displayTitle)}</div>
          </td>
          <td style="color: var(--text-muted); font-size: 0.8rem; font-family: var(--font-mono);">
            ${escapeHtml(timelineText)}
          </td>
          <td>
            <span class="badge ${badgeClass}"><span class="badge-dot"></span>${statusStr}</span>
          </td>
          <td style="text-align:right;">
            ${decisionPill}
          </td>
        </tr>
      `;
    }
    html += '</tbody></table></div>';
    
    // Add Table Footer matching Image 2
    html += `
      <div style="padding: 0.75rem 1.25rem; border-top: 1px solid var(--border-subtle); display: flex; justify-content: space-between; align-items: center; font-size: 0.75rem; color: var(--text-muted); background-color: var(--neutral-surface); border-radius: 0 0 var(--radius-lg) var(--radius-lg);">
        <span>${records.length} portal record${records.length === 1 ? '' : 's'} verified for today</span>
        <span>PWIOI Student Portal</span>
      </div>
    `;

    this.els.attendanceRecords.innerHTML = html;
  }

  renderRecentChecks() {
    if (!this.els.recentChecks) return;
    if (!this.latestCheck) {
      this.els.recentChecks.innerHTML = `
        <div style="padding: 1.25rem; text-align: center; color: var(--text-muted); font-size: 0.85rem;">
          No attendance checks recorded in the database yet.
        </div>
      `;
      return;
    }

    const check = this.latestCheck;
    const isSuccess = check.status === 'SUCCESS';
    const statusBadge = isSuccess 
      ? `<span class="badge badge-success"><span class="badge-dot"></span>SUCCESS</span>`
      : `<span class="badge badge-danger"><span class="badge-dot"></span>${escapeHtml(check.status)}</span>`;

    const checkedTime = new Date(check.checked_at).toLocaleString();
    const resultCount = check.results ? check.results.length : 0;
    let pCount = 0, aCount = 0, uCount = 0;
    (check.results || []).forEach(r => {
      if (r.status === 'PRESENT') pCount++;
      else if (r.status === 'ABSENT') aCount++;
      else uCount++;
    });
    const resultBreakdown = resultCount > 0
      ? `<span style="font-size: 0.75rem; color: var(--text-muted); margin-left: 0.35rem;">(${pCount} Present, ${aCount} Absent, ${uCount} Unknown)</span>`
      : '';

    this.els.recentChecks.innerHTML = `
      <div style="padding: 1.15rem; background: var(--neutral-surface); border-radius: var(--radius-md); border: 1px solid var(--border-subtle);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.6rem;">
          <div style="display: flex; align-items: center; gap: 0.6rem;">
            ${statusBadge}
            <span style="font-size: 0.9rem; font-weight: 700; color: var(--text-main); font-family: var(--font-mono);">${escapeHtml(check.date)}</span>
          </div>
          <span class="code-tag">${escapeHtml(check.adapter_name)}</span>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: var(--text-muted);">
          <span>Checked: <strong>${escapeHtml(checkedTime)}</strong></span>
          <span>Subjects: <strong>${resultCount}</strong> ${resultBreakdown}</span>
        </div>
        ${check.error_message ? `<div style="margin-top: 0.6rem; font-size: 0.75rem; color: var(--color-danger); background: var(--color-danger-bg); border: 1px solid var(--color-danger-border); padding: 0.4rem 0.65rem; border-radius: var(--radius-sm);">${escapeHtml(check.error_message)}</div>` : ''}
      </div>
    `;
  }

  renderNotificationsFeed() {
    const gcSubtext = document.getElementById('dashboard-gc-status-subtext');
    const gcIcon = document.getElementById('dashboard-gc-status-icon');
    const pipeBadge = document.getElementById('dashboard-pipeline-badge');
    const isDry = this.appSettings ? this.appSettings.dry_run : true;

    if (gcSubtext && gcIcon) {
      if (this.recentNotifications && this.recentNotifications.length > 0) {
        const latest = this.recentNotifications[0];
        gcSubtext.innerText = `Latest: ${latest.subject_code} (${latest.status})`;
        gcIcon.innerText = latest.status === 'SENT' ? '✓' : '⚠️';
        gcIcon.style.color = latest.status === 'SENT' ? 'var(--color-success)' : 'var(--color-warning)';
        if (pipeBadge) {
          pipeBadge.className = 'badge badge-success';
          pipeBadge.innerHTML = '<span class="badge-dot"></span>Active Dispatches';
        }
      } else {
        gcSubtext.innerText = isDry ? 'Safe Mode Active (dispatches suppressed)' : 'Direct faculty delivery armed';
        gcIcon.innerText = isDry ? '🛡️' : '✓';
        gcIcon.style.color = isDry ? 'var(--tertiary)' : 'var(--color-success)';
        if (pipeBadge) {
          pipeBadge.className = 'badge badge-neutral';
          pipeBadge.innerHTML = '<span class="badge-dot"></span>Safe Standby';
        }
      }
    }

    if (!this.els.notificationsFeed) return;
    const notifs = this.recentNotifications;
    if (!notifs || notifs.length === 0) {
      this.els.notificationsFeed.innerHTML = `
        <div style="padding: 1.25rem; text-align: center; color: var(--text-muted); font-size: 0.85rem;">
          No notifications recorded. All recent checks were present or protected by fail-closed rules.
        </div>
      `;
      return;
    }

    let html = '<div class="audit-feed">';
    for (const n of notifs) {
      const isDry = n.dry_run;
      const dryBadge = isDry ? `<span class="badge badge-warning" style="font-size: 0.65rem; padding: 0.15rem 0.4rem;">DRY RUN</span>` : '';
      const dateStr = new Date(n.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

      html += `
        <div class="audit-item ${n.status === 'SENT' ? 'success' : 'warning'}">
          <div>
            <div style="display: flex; align-items: center; gap: 0.4rem;">
              <span class="audit-action">${escapeHtml(n.subject_code)}</span>
              ${dryBadge}
            </div>
            <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.15rem;">
              Recipient: ${escapeHtml(n.recipient_email || 'Unconfigured')} · Status: ${escapeHtml(n.status)}
            </div>
            ${n.error_message ? `<div style="font-size: 0.75rem; color: var(--color-danger); margin-top: 0.25rem;">${escapeHtml(n.error_message)}</div>` : ''}
          </div>
          <span class="audit-time">${escapeHtml(dateStr)}</span>
        </div>
      `;
    }
    html += '</div>';
    this.els.notificationsFeed.innerHTML = html;
  }

  // --- Manual Check Modal Workflows ---
  openRunCheckModal() {
    if (!this.els.modalRunCheck) return;
    
    // Track active element for accessibility focus return
    this.lastActiveElement = document.activeElement;

    // Default target date to today and bound max to today (cannot check future dates)
    const todayStr = this.currentData?.today || new Date().toISOString().split('T')[0];
    if (this.els.inputRunCheckDate) {
      this.els.inputRunCheckDate.value = todayStr;
      this.els.inputRunCheckDate.max = todayStr;
      this.els.inputRunCheckDate.disabled = false;
    }

    // Update Dry Run badge
    const isDryRun = this.appSettings?.dry_run !== false;
    if (this.els.runCheckDryRunText) {
      this.els.runCheckDryRunText.innerText = isDryRun
        ? 'DRY RUN Active (Safety Mode: Zero emails sent)'
        : 'LIVE MODE: Notifications will be sent if unrectified absences occur';
    }
    if (this.els.runCheckDryRunBadge) {
      this.els.runCheckDryRunBadge.className = isDryRun ? 'badge badge-warning' : 'badge badge-danger';
    }

    // Session warning: show advisory box if storage state is missing
    if (this.els.runCheckSessionWarning) {
      const isAuth = this.sessionStatus?.is_authenticated;
      this.els.runCheckSessionWarning.style.display = isAuth ? 'none' : 'flex';
    }

    // Reset progress and result displays
    if (this.els.runCheckProgress) this.els.runCheckProgress.style.display = 'none';
    if (this.els.runCheckResult) {
      this.els.runCheckResult.style.display = 'none';
      this.els.runCheckResult.innerHTML = '';
    }
    if (this.els.btnExecuteRunCheck) {
      this.els.btnExecuteRunCheck.disabled = false;
    }
    if (this.els.btnExecuteRunCheckText) {
      this.els.btnExecuteRunCheckText.innerText = 'Start Check';
    }
    if (this.els.btnCancelRunCheck) {
      this.els.btnCancelRunCheck.disabled = false;
    }
    if (this.els.btnCloseRunCheckModal) {
      this.els.btnCloseRunCheckModal.disabled = false;
    }

    this.els.modalRunCheck.style.display = 'flex';
    setTimeout(() => {
      if (this.els.inputRunCheckDate) this.els.inputRunCheckDate.focus();
    }, 50);
  }

  closeRunCheckModal() {
    if (this.isRunningCheck) return; // Prevent dismissing modal while check is in progress
    if (this.els.modalRunCheck) {
      this.els.modalRunCheck.style.display = 'none';
    }
    if (this.lastActiveElement && typeof this.lastActiveElement.focus === 'function') {
      this.lastActiveElement.focus();
    }
  }

  async executeManualCheck() {
    if (this.isRunningCheck) return;

    const targetDate = this.els.inputRunCheckDate ? this.els.inputRunCheckDate.value : null;
    if (!targetDate) {
      window.dispatchEvent(new CustomEvent('app-alert', {
        detail: { message: 'Please select a target date for the check.', type: 'error' }
      }));
      return;
    }

    const todayStr = this.currentData?.today || new Date().toISOString().split('T')[0];
    if (targetDate > todayStr) {
      window.dispatchEvent(new CustomEvent('app-alert', {
        detail: { message: 'Cannot check attendance for future dates.', type: 'error' }
      }));
      return;
    }

    this.isRunningCheck = true;
    if (this.els.inputRunCheckDate) this.els.inputRunCheckDate.disabled = true;
    if (this.els.btnCancelRunCheck) this.els.btnCancelRunCheck.disabled = true;
    if (this.els.btnCloseRunCheckModal) this.els.btnCloseRunCheckModal.disabled = true;
    if (this.els.btnExecuteRunCheck) this.els.btnExecuteRunCheck.disabled = true;
    if (this.els.btnExecuteRunCheckText) this.els.btnExecuteRunCheckText.innerText = 'Extracting...';
    if (this.els.runCheckProgress) this.els.runCheckProgress.style.display = 'block';
    if (this.els.runCheckResult) {
      this.els.runCheckResult.style.display = 'none';
      this.els.runCheckResult.innerHTML = '';
    }

    try {
      const response = await API.checks.run({ date: targetDate });

      if (this.els.runCheckProgress) this.els.runCheckProgress.style.display = 'none';
      if (this.els.btnExecuteRunCheck) this.els.btnExecuteRunCheck.disabled = false;
      if (this.els.btnExecuteRunCheckText) this.els.btnExecuteRunCheckText.innerText = 'Re-Run Check';

      // Render Check Results inside modal
      if (this.els.runCheckResult) {
        const isSuccess = response.status === 'SUCCESS';
        let decisionsHtml = '';
        if (response.decisions && response.decisions.length > 0) {
          decisionsHtml = response.decisions.map(d => `
            <div style="display:flex; justify-content:space-between; font-size:0.8rem; padding:0.35rem 0; border-bottom:1px solid var(--border-subtle);">
              <span><strong>${escapeHtml(d.subject_code)}</strong> (${escapeHtml(d.status)})</span>
              <span class="badge ${d.action === 'NO_ACTION' ? 'badge-success' : 'badge-warning'}" style="font-size:0.7rem;">
                ${escapeHtml(d.action)} (${escapeHtml(d.reason)})
              </span>
            </div>
          `).join('');
        } else {
          decisionsHtml = '<div style="font-size:0.8rem; color:var(--text-muted);">No decision records returned.</div>';
        }

        this.els.runCheckResult.innerHTML = `
          <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 1rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
              <span style="font-size: 0.9rem; font-weight: 700; color: var(--text-main);">Run Result:</span>
              <span class="badge ${isSuccess ? 'badge-success' : 'badge-danger'}">
                <span class="badge-dot"></span>${escapeHtml(response.status)}
              </span>
            </div>
            <div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.75rem;">
              Run ID: <code style="font-family: var(--font-mono); color: var(--accent-light);">${escapeHtml(response.run_id)}</code>
            </div>
            <div style="margin-top: 0.5rem;">
              <strong style="font-size: 0.8rem; color: var(--text-muted); text-transform: uppercase;">Evaluated Decisions:</strong>
              <div style="margin-top: 0.4rem;">${decisionsHtml}</div>
            </div>
            ${response.error_message ? `<div style="margin-top: 0.75rem; font-size: 0.8rem; color: var(--color-danger);">${escapeHtml(response.error_message)}</div>` : ''}
          </div>
        `;
        this.els.runCheckResult.style.display = 'block';
      }

      window.dispatchEvent(new CustomEvent('app-alert', {
        detail: { message: `Attendance check completed with status: ${response.status}`, type: response.status === 'SUCCESS' ? 'success' : 'error' }
      }));

      // Refresh dashboard background metrics and system header status dynamically
      this.loadData();
      window.dispatchEvent(new CustomEvent('system-status-changed'));

    } catch (err) {
      if (this.els.runCheckProgress) this.els.runCheckProgress.style.display = 'none';
      if (this.els.btnExecuteRunCheck) this.els.btnExecuteRunCheck.disabled = false;
      if (this.els.btnExecuteRunCheckText) this.els.btnExecuteRunCheckText.innerText = 'Retry Check';

      if (this.els.runCheckResult) {
        this.els.runCheckResult.innerHTML = `
          <div style="background: var(--color-danger-bg); border: 1px solid var(--color-danger-border); border-radius: var(--radius-md); padding: 1rem; color: #fca5a5; font-size: 0.85rem;">
            <strong>Check Execution Failed:</strong>
            <p style="margin-top: 0.25rem;">${escapeHtml(err.message || 'Unknown network error')}</p>
          </div>
        `;
        this.els.runCheckResult.style.display = 'block';
      }

      window.dispatchEvent(new CustomEvent('app-alert', {
        detail: { message: `Check failed: ${err.message}`, type: 'error' }
      }));
    } finally {
      this.isRunningCheck = false;
      if (this.els.inputRunCheckDate) this.els.inputRunCheckDate.disabled = false;
      if (this.els.btnCancelRunCheck) this.els.btnCancelRunCheck.disabled = false;
      if (this.els.btnCloseRunCheckModal) this.els.btnCloseRunCheckModal.disabled = false;
    }
  }
}

// Utility to prevent XSS
function escapeHtml(unsafe) {
  if (!unsafe) return '';
  return unsafe
    .toString()
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Utility to parse YYYY-MM-DD in local time to avoid timezone offset shifts
function parseLocalDate(dateStr) {
  if (!dateStr) return new Date();
  if (typeof dateStr === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
    const [y, m, d] = dateStr.split('-').map(Number);
    return new Date(y, m - 1, d);
  }
  return new Date(dateStr);
}
