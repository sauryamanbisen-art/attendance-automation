/**
 * @fileoverview Attendance History Page Controller
 */

import { API } from '../api.js';

export class HistoryController {
  constructor() {
    this.els = {
      loading: document.getElementById('history-loading'),
      error: document.getElementById('history-error'),
      errorText: document.getElementById('history-error-text'),
      content: document.getElementById('history-content'),
      
      btnRetry: document.getElementById('btn-retry-history'),
      
      // Filters
      inputSubject: document.getElementById('filter-history-subject'),
      inputStart: document.getElementById('filter-history-start'),
      inputEnd: document.getElementById('filter-history-end'),
      btnApply: document.getElementById('btn-apply-history-filters'),
      btnClear: document.getElementById('btn-clear-history-filters'),
      
      // Table & Pagination
      tableBody: document.getElementById('history-table-body'),
      paginationInfo: document.getElementById('history-pagination-info'),
      btnPrev: document.getElementById('btn-history-prev'),
      btnNext: document.getElementById('btn-history-next'),
    };

    this.state = {
      subjectsLoaded: false,
      limit: 20,
      offset: 0,
      total: 0,
    };

    this.bindEvents();
  }

  bindEvents() {
    if (this.els.btnRetry) {
      this.els.btnRetry.addEventListener('click', () => this.loadData());
    }
    
    if (this.els.btnApply) {
      this.els.btnApply.addEventListener('click', () => {
        this.state.offset = 0; // reset pagination on filter change
        this.loadData();
      });
    }
    
    if (this.els.btnClear) {
      this.els.btnClear.addEventListener('click', () => {
        this.els.inputSubject.value = '';
        this.els.inputStart.value = '';
        this.els.inputEnd.value = '';
        this.state.offset = 0;
        this.loadData();
      });
    }
    
    if (this.els.btnPrev) {
      this.els.btnPrev.addEventListener('click', () => {
        if (this.state.offset > 0) {
          this.state.offset = Math.max(0, this.state.offset - this.state.limit);
          this.loadData();
        }
      });
    }
    
    if (this.els.btnNext) {
      this.els.btnNext.addEventListener('click', () => {
        if (this.state.offset + this.state.limit < this.state.total) {
          this.state.offset += this.state.limit;
          this.loadData();
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
      if (!this.state.subjectsLoaded) {
        const subjects = await API.subjects.list();
        let html = '<option value="">All Subjects</option>';
        for (const sub of subjects) {
          html += `<option value="${sub.code}">${escapeHtml(sub.code)} - ${escapeHtml(sub.name)}</option>`;
        }
        this.els.inputSubject.innerHTML = html;
        this.state.subjectsLoaded = true;
      }
      
      const params = {
        limit: this.state.limit,
        offset: this.state.offset
      };
      
      if (this.els.inputSubject.value) params.subject_code = this.els.inputSubject.value;
      if (this.els.inputStart.value) params.start_date = this.els.inputStart.value;
      if (this.els.inputEnd.value) params.end_date = this.els.inputEnd.value;
      
      const data = await API.history.list(params);
      
      this.state.total = data.total;
      this.renderTable(data.items);
      this.updatePagination();
      
      this.showState('content');
    } catch (err) {
      this.els.errorText.innerText = err.message || 'Unknown error occurred while fetching history data.';
      this.showState('error');
    }
  }

  renderTable(items) {
    if (items.length === 0) {
      this.els.tableBody.innerHTML = `
        <tr>
          <td colspan="6" style="text-align: center; padding: 2rem; color: var(--text-muted);">
            No attendance records found matching your filters.
          </td>
        </tr>
      `;
      return;
    }
    
    let html = '';
    for (const item of items) {
      
      // Status Badge
      let statusClass = 'badge-secondary';
      if (item.status === 'PRESENT') statusClass = 'badge-success';
      if (item.status === 'ABSENT') statusClass = 'badge-danger';
      if (item.status === 'UNKNOWN' || item.status === 'NOT_MARKED') statusClass = 'badge-warning';
      
      const statusBadge = `<span class="badge ${statusClass}">${item.status}</span>`;
      
      // Reliability Badge
      const reliableBadge = item.is_reliable 
        ? `<span class="badge badge-success">High</span>` 
        : `<span class="badge badge-warning" title="Extraction failed or fallback mechanism triggered">Low</span>`;
      
      // Context String
      const contexts = [];
      if (item.is_holiday) contexts.push('<span style="color: var(--color-warning);">Holiday</span>');
      if (item.is_cancelled) contexts.push('<span style="color: var(--color-danger);">Cancelled</span>');
      if (item.is_extra) contexts.push('<span style="color: var(--color-info);">Extra Class</span>');
      if (contexts.length === 0) {
        contexts.push(item.is_scheduled ? '<span style="color: var(--text-muted);">Scheduled</span>' : '<span style="color: var(--text-muted);">Unscheduled</span>');
      }
      
      // Notification String
      let notifStr = '<span style="color: var(--text-subtle);">-</span>';
      if (item.notification_status) {
        if (item.notification_dry_run) {
          notifStr = `<span class="badge badge-secondary" title="Dry Run: Email generated but intercepted">DRY RUN</span>`;
        } else {
          notifStr = `<span class="badge badge-info">${item.notification_status.toUpperCase()}</span>`;
        }
      }
      
      const d = parseLocalDate(item.check_date).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
      
      html += `
        <tr>
          <td>
            <strong>${d}</strong>
            ${item.notes ? `<div style="font-size: 0.75rem; color: var(--text-subtle); margin-top: 0.25rem;" title="${escapeHtml(item.notes)}">Has notes</div>` : ''}
          </td>
          <td>
            <strong style="color: var(--text-main);">${escapeHtml(item.subject_code)}</strong>
            ${item.subject_name ? `<div style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(item.subject_name)}</div>` : ''}
          </td>
          <td>${statusBadge}</td>
          <td>${reliableBadge}</td>
          <td>${contexts.join(', ')}</td>
          <td>${notifStr}</td>
        </tr>
      `;
    }
    this.els.tableBody.innerHTML = html;
  }
  
  updatePagination() {
    const start = Math.min(this.state.offset + 1, this.state.total);
    const end = Math.min(this.state.offset + this.state.limit, this.state.total);
    
    if (this.state.total === 0) {
      this.els.paginationInfo.innerText = `Showing 0 items`;
    } else {
      this.els.paginationInfo.innerText = `Showing ${start}-${end} of ${this.state.total} items`;
    }
    
    this.els.btnPrev.disabled = this.state.offset === 0;
    this.els.btnNext.disabled = this.state.offset + this.state.limit >= this.state.total;
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
