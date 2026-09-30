/**
 * @fileoverview Calendar Page Controller
 */

import { API } from '../api.js';

export class CalendarController {
  constructor() {
    this.els = {
      loading: document.getElementById('calendar-loading'),
      error: document.getElementById('calendar-error'),
      errorText: document.getElementById('calendar-error-text'),
      content: document.getElementById('calendar-content'),
      
      btnRetry: document.getElementById('btn-retry-calendar'),
      holidaysContainer: document.getElementById('calendar-holidays-container'),
      exceptionsContainer: document.getElementById('calendar-exceptions-container'),
      
      // Holiday Modal
      modalHoliday: document.getElementById('modal-holiday'),
      formHoliday: document.getElementById('form-holiday'),
      btnShowHolidayModal: document.getElementById('btn-show-add-holiday-modal'),
      btnCloseHoliday: document.getElementById('btn-close-holiday-modal'),
      btnCancelHoliday: document.getElementById('btn-cancel-holiday-modal'),
      inputHolidayDate: document.getElementById('input-holiday-date'),
      inputHolidayDesc: document.getElementById('input-holiday-desc'),

      // Exception Modal
      modalException: document.getElementById('modal-exception'),
      formException: document.getElementById('form-exception'),
      btnShowExceptionModal: document.getElementById('btn-show-add-exception-modal'),
      btnCloseException: document.getElementById('btn-close-exception-modal'),
      btnCancelException: document.getElementById('btn-cancel-exception-modal'),
      
      inputExcType: document.getElementById('input-exception-type'),
      inputExcSubject: document.getElementById('input-exception-subject'),
      inputExcDate: document.getElementById('input-exception-date'),
      inputExcStart: document.getElementById('input-exception-start'),
      inputExcEnd: document.getElementById('input-exception-end'),
      inputExcDesc: document.getElementById('input-exception-desc'),
      excTimeContainer: document.getElementById('exception-time-container'),
    };

    this.subjects = [];
    this.holidays = [];
    this.exceptions = [];

    this.bindEvents();
  }

  bindEvents() {
    if (this.els.btnRetry) this.els.btnRetry.addEventListener('click', () => this.loadData());

    // Holiday Modal Events
    if (this.els.btnShowHolidayModal) this.els.btnShowHolidayModal.addEventListener('click', () => this.openHolidayModal());
    if (this.els.btnCloseHoliday) this.els.btnCloseHoliday.addEventListener('click', () => this.closeModals());
    if (this.els.btnCancelHoliday) this.els.btnCancelHoliday.addEventListener('click', () => this.closeModals());
    if (this.els.formHoliday) this.els.formHoliday.addEventListener('submit', (e) => this.handleSaveHoliday(e));

    // Exception Modal Events
    if (this.els.btnShowExceptionModal) this.els.btnShowExceptionModal.addEventListener('click', () => this.openExceptionModal());
    if (this.els.btnCloseException) this.els.btnCloseException.addEventListener('click', () => this.closeModals());
    if (this.els.btnCancelException) this.els.btnCancelException.addEventListener('click', () => this.closeModals());
    if (this.els.formException) this.els.formException.addEventListener('submit', (e) => this.handleSaveException(e));
    
    // Toggle time inputs based on Exception Type
    if (this.els.inputExcType) {
      this.els.inputExcType.addEventListener('change', (e) => {
        if (e.target.value === 'EXTRA') {
          this.els.excTimeContainer.style.display = 'block';
          this.els.inputExcStart.required = true;
          this.els.inputExcEnd.required = true;
        } else {
          this.els.excTimeContainer.style.display = 'none';
          this.els.inputExcStart.required = false;
          this.els.inputExcEnd.required = false;
        }
      });
    }

    // Delegation for delete buttons
    if (this.els.content) {
      this.els.content.addEventListener('click', (e) => {
        const delHolidayBtn = e.target.closest('.btn-delete-holiday');
        if (delHolidayBtn) {
          this.handleDeleteHoliday(parseInt(delHolidayBtn.dataset.id, 10));
        }

        const delExceptionBtn = e.target.closest('.btn-delete-exception');
        if (delExceptionBtn) {
          this.handleDeleteException(parseInt(delExceptionBtn.dataset.id, 10));
        }
      });
    }
  }

  showState(state) {
    this.els.loading.style.display = state === 'loading' ? 'block' : 'none';
    this.els.error.style.display = state === 'error' ? 'block' : 'none';
    this.els.content.style.display = state === 'content' ? 'block' : 'none';
  }

  async loadData() {
    this.showState('loading');
    try {
      const [subjects, holidays, exceptions] = await Promise.all([
        API.subjects.list(),
        API.calendar.listHolidays(),
        API.calendar.listExceptions()
      ]);
      
      this.subjects = subjects;
      
      // Sort upcoming
      this.holidays = holidays.sort((a, b) => a.date.localeCompare(b.date));
      this.exceptions = exceptions.sort((a, b) => a.date.localeCompare(b.date));
      
      this.populateSubjectsDropdown();
      this.render();
      
      this.showState('content');
    } catch (err) {
      this.els.errorText.innerText = err.message || 'Unknown error occurred while fetching calendar data.';
      this.showState('error');
    }
  }

  populateSubjectsDropdown() {
    let html = '<option value="">Select a subject...</option>';
    for (const sub of this.subjects) {
      html += `<option value="${sub.id}">${escapeHtml(sub.code)} - ${escapeHtml(sub.name)}</option>`;
    }
    this.els.inputExcSubject.innerHTML = html;
  }

  render() {
    // Render Holidays
    if (this.holidays.length === 0) {
      this.els.holidaysContainer.innerHTML = `<div style="padding: 1.5rem; text-align: center; color: var(--text-muted); font-size: 0.9rem;">No holidays scheduled.</div>`;
    } else {
      let html = '<div class="table-responsive"><table class="data-table"><tbody>';
      for (const h of this.holidays) {
        const d = parseLocalDate(h.date).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
        html += `
          <tr>
            <td>
              <strong>${escapeHtml(h.description)}</strong>
              <div style="font-size:0.8rem; color:var(--text-muted);">${d}</div>
            </td>
            <td style="text-align:right;">
              <button class="btn-delete-holiday" data-id="${h.id}" style="background:none; border:none; color:var(--color-danger); cursor:pointer;" title="Delete">🗑️</button>
            </td>
          </tr>
        `;
      }
      html += '</tbody></table></div>';
      this.els.holidaysContainer.innerHTML = html;
    }

    // Render Exceptions
    if (this.exceptions.length === 0) {
      this.els.exceptionsContainer.innerHTML = `<div style="padding: 1.5rem; text-align: center; color: var(--text-muted); font-size: 0.9rem;">No class exceptions scheduled.</div>`;
    } else {
      let html = '<div style="display:flex; flex-direction:column; gap:0.75rem; padding: 1.25rem;">';
      for (const exc of this.exceptions) {
        const subject = this.subjects.find(s => s.id === exc.subject_id);
        const subjName = subject ? subject.code : 'Unknown';
        const isCancelled = exc.exception_type === 'CANCELLED';
        
        const badgeClass = isCancelled ? 'badge-danger' : 'badge-info';
        const badgeText = isCancelled ? 'CANCELLED' : 'EXTRA CLASS';
        
        const d = parseLocalDate(exc.date).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
        
        html += `
          <div style="background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 1rem;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem;">
              <div>
                <strong style="color: var(--text-main); font-size: 0.95rem;">${escapeHtml(subjName)}</strong>
                <span class="badge ${badgeClass}" style="margin-left: 0.5rem; font-size: 0.6rem;">${badgeText}</span>
              </div>
              <button class="btn-delete-exception" data-id="${exc.id}" style="background:none; border:none; color:var(--color-danger); cursor:pointer;" title="Delete">🗑️</button>
            </div>
            
            <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.25rem;">
              <span aria-hidden="true">📅</span> ${d}
            </div>
            
            ${!isCancelled && exc.start_time && exc.end_time ? `
              <div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.25rem;">
                <span aria-hidden="true">⏱️</span> ${exc.start_time.slice(0, 5)} - ${exc.end_time.slice(0, 5)}
              </div>
            ` : ''}
            
            ${exc.description ? `<div style="font-size: 0.8rem; color: var(--text-subtle); margin-top: 0.5rem; border-top: 1px dashed var(--border-subtle); padding-top: 0.5rem;">${escapeHtml(exc.description)}</div>` : ''}
          </div>
        `;
      }
      html += '</div>';
      this.els.exceptionsContainer.innerHTML = html;
    }
  }

  closeModals() {
    this.els.modalHoliday.style.display = 'none';
    this.els.modalException.style.display = 'none';
  }

  openHolidayModal() {
    this.els.formHoliday.reset();
    this.els.modalHoliday.style.display = 'flex';
  }

  openExceptionModal() {
    this.els.formException.reset();
    
    // Reset toggle state
    this.els.excTimeContainer.style.display = 'none';
    this.els.inputExcStart.required = false;
    this.els.inputExcEnd.required = false;
    
    this.els.modalException.style.display = 'flex';
  }

  async handleSaveHoliday(e) {
    e.preventDefault();
    const payload = {
      date: this.els.inputHolidayDate.value,
      description: this.els.inputHolidayDesc.value.trim(),
    };
    
    try {
      const submitBtn = this.els.formHoliday.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      submitBtn.innerText = 'Saving...';
      
      await API.calendar.createHoliday(payload);
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Holiday created successfully', type: 'success' }}));
      
      this.closeModals();
      await this.loadData();
    } catch (err) {
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: `Validation Error: ${err.message}`, type: 'error' }}));
    } finally {
      const submitBtn = this.els.formHoliday.querySelector('button[type="submit"]');
      submitBtn.disabled = false;
      submitBtn.innerText = 'Save Holiday';
    }
  }

  async handleSaveException(e) {
    e.preventDefault();
    const type = this.els.inputExcType.value;
    const payload = {
      subject_id: parseInt(this.els.inputExcSubject.value, 10),
      date: this.els.inputExcDate.value,
      exception_type: type,
      description: this.els.inputExcDesc.value.trim() || null,
    };
    
    if (type === 'EXTRA') {
      payload.start_time = this.els.inputExcStart.value + ':00';
      payload.end_time = this.els.inputExcEnd.value + ':00';
    }
    
    try {
      const submitBtn = this.els.formException.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      submitBtn.innerText = 'Saving...';
      
      await API.calendar.createException(payload);
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Exception created successfully', type: 'success' }}));
      
      this.closeModals();
      await this.loadData();
    } catch (err) {
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: `Validation Error: ${err.message}`, type: 'error' }}));
    } finally {
      const submitBtn = this.els.formException.querySelector('button[type="submit"]');
      submitBtn.disabled = false;
      submitBtn.innerText = 'Save Exception';
    }
  }

  async handleDeleteHoliday(id) {
    if (!confirm('Are you sure you want to delete this holiday? Classes will be expected as normal.')) return;
    try {
      await API.calendar.deleteHoliday(id);
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Holiday deleted successfully', type: 'success' }}));
      await this.loadData();
    } catch (err) {
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: `Failed to delete: ${err.message}`, type: 'error' }}));
    }
  }
  
  async handleDeleteException(id) {
    if (!confirm('Are you sure you want to delete this exception?')) return;
    try {
      await API.calendar.deleteException(id);
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Exception deleted successfully', type: 'success' }}));
      await this.loadData();
    } catch (err) {
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: `Failed to delete: ${err.message}`, type: 'error' }}));
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
