/**
 * @fileoverview Dashboard Page Controller
 */

import { API } from '../api.js';

export class DashboardController {
  constructor() {
    this.els = {
      loading: document.getElementById('dashboard-loading'),
      error: document.getElementById('dashboard-error'),
      errorText: document.getElementById('dashboard-error-text'),
      content: document.getElementById('dashboard-content'),
      
      heroCard: document.getElementById('dashboard-hero-card'),
      heroDateBadge: document.getElementById('hero-date-text'),
      heroStatusBadge: document.getElementById('hero-status-badge'),
      heroTitle: document.getElementById('hero-title'),
      heroDesc: document.getElementById('hero-desc'),
      heroNoteContainer: document.getElementById('hero-note-container'),
      inputConfirmNote: document.getElementById('input-confirm-note'),
      btnConfirm: document.getElementById('btn-confirm-attendance'),
      btnConfirmText: document.getElementById('btn-confirm-text'),
      
      holidayCard: document.getElementById('dashboard-holiday-card'),
      expectedClasses: document.getElementById('dashboard-expected-classes'),
      attendanceRecords: document.getElementById('dashboard-attendance-records'),
      
      btnRetry: document.getElementById('btn-retry-dashboard')
    };

    if (this.els.btnRetry) {
      this.els.btnRetry.addEventListener('click', () => this.loadData());
    }
    if (this.els.btnConfirm) {
      this.els.btnConfirm.addEventListener('click', () => this.handleConfirmation());
    }
  }

  async loadData() {
    this.showState('loading');
    try {
      const data = await API.dashboard.getToday();
      this.render(data);
      this.showState('content');
    } catch (err) {
      this.els.errorText.innerText = err.message || 'Unknown error occurred while fetching dashboard data.';
      this.showState('error');
    }
  }

  showState(state) {
    this.els.loading.style.display = state === 'loading' ? 'block' : 'none';
    this.els.error.style.display = state === 'error' ? 'block' : 'none';
    this.els.content.style.display = state === 'content' ? 'block' : 'none';
  }

  /**
   * @param {import('../types.js').DashboardResponse} data 
   */
  render(data) {
    this.currentData = data;
    
    // 1. Date
    const d = new Date(data.today);
    this.els.heroDateBadge.innerText = d.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
    
    // 2. Confirmation Status
    this.renderConfirmationStatus(data.is_confirmed);
    
    // 3. Holiday Status
    if (data.is_holiday) {
      this.els.holidayCard.style.display = 'block';
    } else {
      this.els.holidayCard.style.display = 'none';
    }
    
    // 4. Expected Classes
    this.renderExpectedClasses(data.expected_classes);
    
    // 5. Attendance Records
    this.renderAttendanceRecords(data.attendance_records);
  }

  renderConfirmationStatus(isConfirmed) {
    if (isConfirmed) {
      this.els.heroCard.classList.add('confirmed');
      this.els.heroStatusBadge.className = 'badge badge-success';
      this.els.heroStatusBadge.innerHTML = '<span class="badge-dot"></span>Confirmed for Today';
      this.els.heroTitle.innerText = 'Attendance Confirmed';
      this.els.heroDesc.innerText = 'Your attendance has been recorded. The automated scheduler will safely verify portal records after the cutoff time.';
      
      this.els.btnConfirm.disabled = true;
      this.els.btnConfirm.classList.add('btn-confirmed');
      this.els.btnConfirmText.innerText = '✓ Confirmed';
      this.els.heroNoteContainer.style.display = 'none';
    } else {
      this.els.heroCard.classList.remove('confirmed');
      this.els.heroStatusBadge.className = 'badge badge-warning';
      this.els.heroStatusBadge.innerHTML = '<span class="badge-dot pulse"></span>Awaiting Confirmation';
      this.els.heroTitle.innerText = 'Did you attend college today?';
      this.els.heroDesc.innerText = 'Mark your attendance so the automated scheduler knows to verify your portal records after the cutoff time. Unconfirmed days are skipped for safety.';
      
      this.els.btnConfirm.disabled = false;
      this.els.btnConfirm.classList.remove('btn-confirmed');
      this.els.btnConfirmText.innerText = 'I WENT TO COLLEGE';
      this.els.heroNoteContainer.style.display = 'block';
    }
  }

  async handleConfirmation() {
    this.els.btnConfirm.disabled = true;
    this.els.btnConfirmText.innerText = 'Confirming...';
    
    const note = this.els.inputConfirmNote.value.trim();
    const today = this.currentData ? this.currentData.today : new Date().toISOString().split('T')[0];
    
    try {
      await API.confirmations.confirm(today, note || undefined);
      this.renderConfirmationStatus(true);
      
      // Dispatch global alert
      window.dispatchEvent(new CustomEvent('app-alert', { 
        detail: { message: 'Attendance confirmed successfully!', type: 'success' } 
      }));
    } catch (err) {
      window.dispatchEvent(new CustomEvent('app-alert', { 
        detail: { message: `Failed to confirm: ${err.message}`, type: 'error' } 
      }));
      this.els.btnConfirm.disabled = false;
      this.els.btnConfirmText.innerText = 'I WENT TO COLLEGE';
    }
  }

  /**
   * @param {import('../types.js').SubjectResponse[]} classes 
   */
  renderExpectedClasses(classes) {
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
      html += `
        <tr>
          <td>
            <strong>${escapeHtml(c.code)}</strong>
            <div style="font-size:0.8rem; color:var(--text-muted);">${escapeHtml(c.name)}</div>
          </td>
          <td style="text-align:right;">
            ${escapeHtml(c.professor_name || 'No Instructor')}
          </td>
        </tr>
      `;
    }
    html += '</tbody></table></div>';
    this.els.expectedClasses.innerHTML = html;
  }

  /**
   * @param {import('../types.js').SubjectResultItem[]} records 
   */
  renderAttendanceRecords(records) {
    if (!records || records.length === 0) {
      this.els.attendanceRecords.innerHTML = `
        <div style="padding: 1.5rem; text-align: center; color: var(--text-muted); font-size: 0.9rem;">
          No portal records extracted for today yet.
        </div>
      `;
      return;
    }
    
    let html = '<div class="table-responsive"><table class="data-table"><tbody>';
    for (const r of records) {
      let badgeClass = 'badge-neutral';
      let statusStr = 'Unknown';
      
      if (r.status === 'PRESENT') { badgeClass = 'badge-success'; statusStr = 'Present'; }
      else if (r.status === 'ABSENT') { badgeClass = 'badge-danger'; statusStr = 'Absent'; }
      else if (r.status === 'NOT_MARKED') { badgeClass = 'badge-warning'; statusStr = 'Not Marked'; }
      
      html += `
        <tr>
          <td>
            <strong>${escapeHtml(r.subject_code)}</strong>
          </td>
          <td style="text-align:right;">
            <span class="badge ${badgeClass}"><span class="badge-dot"></span>${statusStr}</span>
          </td>
        </tr>
      `;
    }
    html += '</tbody></table></div>';
    this.els.attendanceRecords.innerHTML = html;
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
