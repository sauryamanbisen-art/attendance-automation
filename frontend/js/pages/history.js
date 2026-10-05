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
      inputStatus: document.getElementById('filter-history-status'),
      inputStart: document.getElementById('filter-history-start'),
      inputEnd: document.getElementById('filter-history-end'),
      btnApply: document.getElementById('btn-apply-history-filters'),
      btnClear: document.getElementById('btn-clear-history-filters'),
      
      // Stat Cards & Metadata
      statTracked: document.getElementById('history-stat-tracked'),
      statRate: document.getElementById('history-stat-rate'),
      statMargin: document.getElementById('history-stat-margin'),
      statHealth: document.getElementById('history-stat-health'),
      latestCheckText: document.getElementById('history-latest-check-text'),
      termBadge: document.getElementById('history-term-badge'),

      // Table & Pagination
      tableBody: document.getElementById('history-table-body'),
      paginationInfo: document.getElementById('history-pagination-info'),
      paginationControls: document.getElementById('history-pagination-controls'),
    };

    this.state = {
      subjectsLoaded: false,
      limit: 6, // EXACTLY 6 records per page (Stitch requirement)
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

    if (this.els.inputStatus) {
      this.els.inputStatus.addEventListener('change', () => {
        this.state.offset = 0;
        this.loadData();
      });
    }
    
    if (this.els.btnClear) {
      this.els.btnClear.addEventListener('click', () => {
        if (this.els.inputSubject) this.els.inputSubject.value = '';
        if (this.els.inputStart) this.els.inputStart.value = '';
        if (this.els.inputEnd) this.els.inputEnd.value = '';
        if (this.els.inputStatus) this.els.inputStatus.value = '';
        this.state.offset = 0;
        this.loadData();
      });
    }

    // Quick filter pills (Today, Last 7 Days, This Month, Discrepancies Only)
    const pills = document.querySelectorAll('#page-attendance .filter-pill');
    pills.forEach(pill => {
      pill.addEventListener('click', (e) => {
        pills.forEach(p => p.classList.remove('active'));
        e.currentTarget.classList.add('active');
        const text = e.currentTarget.innerText.trim();
        const now = new Date();
        const todayStr = now.toISOString().split('T')[0];
        
        if (text.includes('Discrepancies')) {
          if (this.els.inputStatus) this.els.inputStatus.value = 'ABSENT';
          if (this.els.inputStart) this.els.inputStart.value = '';
          if (this.els.inputEnd) this.els.inputEnd.value = '';
        } else {
          if (this.els.inputStatus) this.els.inputStatus.value = '';
          if (text.includes('Today')) {
            this.els.inputStart.value = todayStr;
            this.els.inputEnd.value = todayStr;
          } else if (text.includes('Last 7 Days')) {
            const past = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
            this.els.inputStart.value = past.toISOString().split('T')[0];
            this.els.inputEnd.value = todayStr;
          } else if (text.includes('This Month')) {
            const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
            this.els.inputStart.value = firstDay.toISOString().split('T')[0];
            this.els.inputEnd.value = todayStr;
          } else {
            this.els.inputStart.value = '';
            this.els.inputEnd.value = '';
          }
        }
        this.state.offset = 0;
        this.loadData();
      });
    });
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
        let html = '<option value="">All Subjects (6 Courses)</option>';
        for (const sub of subjects) {
          html += `<option value="${sub.code}">${escapeHtml(sub.code)} - ${escapeHtml(sub.name)}</option>`;
        }
        if (this.els.inputSubject) this.els.inputSubject.innerHTML = html;
        this.state.subjectsLoaded = true;
      }
      
      const params = {
        limit: this.state.limit,
        offset: this.state.offset
      };
      
      if (this.els.inputSubject && this.els.inputSubject.value) params.subject_code = this.els.inputSubject.value;
      if (this.els.inputStatus && this.els.inputStatus.value) params.status = this.els.inputStatus.value;
      if (this.els.inputStart && this.els.inputStart.value) params.start_date = this.els.inputStart.value;
      if (this.els.inputEnd && this.els.inputEnd.value) params.end_date = this.els.inputEnd.value;
      
      const data = await API.history.list(params);
      
      this.state.total = data.total;
      this.renderTable(data.items);
      this.updatePagination();

      // Fetch latest check and compute overall dataset stats
      try {
        const [latestCheckRes, summaryRes, settingsRes] = await Promise.allSettled([
          API.checks.getLatest(),
          API.history.getSummary(),
          API.settings.read(),
        ]);
        
        if (this.els.statTracked) {
          this.els.statTracked.innerHTML = `${data.total} <span style="font-size: 0.85rem; font-weight: 500; color: var(--text-muted);">records</span>`;
        }
        
        if (summaryRes.status === 'fulfilled' && summaryRes.value) {
          const sum = summaryRes.value;
          const acad = sum.academic_attendance;
          const autoLogs = sum.automation_logs || {};

          // Development Safety: Never display synthetic attendance information.
          // Real academic attendance is only displayed if verified and extracted from PWIOI portal.
          if (acad && typeof acad.overall_rate === 'number') {
            const rateVal = acad.overall_rate;
            const isSafe = rateVal >= 75.0;
            if (this.els.statRate) {
              this.els.statRate.innerHTML = `${rateVal.toFixed(1)}% <span class="badge ${isSafe ? 'badge-success' : 'badge-danger'}" style="font-size: 0.65rem; vertical-align: middle;">${isSafe ? 'SAFE' : 'AT RISK'}</span>`;
            }
            const rateHint = document.getElementById('history-stat-rate-hint');
            if (rateHint) {
              rateHint.innerText = `Portal verified (${acad.attended_classes || '--'} / ${acad.total_classes || '--'} classes)`;
            }
          } else {
            // Truthful fallback when academic portal sync is pending
            if (this.els.statRate) {
              this.els.statRate.innerHTML = `Awaiting Sync <span class="badge badge-neutral" style="font-size: 0.65rem; vertical-align: middle;">PENDING</span>`;
            }
            const rateHint = document.getElementById('history-stat-rate-hint');
            if (rateHint) {
              rateHint.innerText = `Statutory threshold: >75% (Awaiting portal sync)`;
            }
          }

          if (this.els.statMargin) {
            const checkCount = typeof autoLogs.total_checks === 'number' ? autoLogs.total_checks : 'N/A';
            this.els.statMargin.innerHTML = checkCount !== 'N/A'
              ? `${checkCount} <span style="font-size: 0.85rem; font-weight: 500; color: var(--text-muted);">checks</span>`
              : 'N/A';
          }
          const marginHint = document.getElementById('history-stat-margin-hint');
          if (marginHint && autoLogs.latest_check?.date) {
            marginHint.innerText = `Latest: ${autoLogs.latest_check.date} (${autoLogs.latest_check.status})`;
          }

          // Card 4: Discrepancy Health
          if (this.els.statHealth) {
            const discCount = sum.discrepancies_count || 0;
            this.els.statHealth.innerHTML = `${discCount} <span style="font-size: 0.85rem; font-weight: 500; color: var(--text-muted);">${discCount === 1 ? 'flagged event' : 'flagged events'}</span>`;
          }
        }
        
        if (latestCheckRes.status === 'fulfilled' && latestCheckRes.value && latestCheckRes.value.check) {
          const chk = latestCheckRes.value.check;
          if (this.els.latestCheckText && chk.checked_at) {
            const dt = new Date(chk.checked_at);
            const timeStr = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            const dateStr = dt.toLocaleDateString([], { month: 'short', day: 'numeric' });
            this.els.latestCheckText.innerText = `Latest check: ${dateStr}, ${timeStr} (${chk.status})`;
          }
        } else if (this.els.latestCheckText) {
          this.els.latestCheckText.innerText = 'Latest check: Synchronized';
        }
        
        if (settingsRes.status === 'fulfilled' && settingsRes.value && this.els.termBadge) {
          this.els.termBadge.innerText = settingsRes.value.pwioi_academic_term || 'PWIOI Campus';
        }
      } catch (e) {
        console.debug('Error updating history stats:', e);
      }
      
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
          <td colspan="7" style="text-align: center; padding: 3rem 1.5rem; color: var(--text-muted);">
            No attendance records found matching your filters.
          </td>
        </tr>
      `;
      return;
    }
    
    let html = '';
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      
      // Status Badge
      let statusClass = 'badge-neutral';
      if (item.status === 'PRESENT') statusClass = 'badge-success';
      if (item.status === 'ABSENT') statusClass = 'badge-danger';
      if (item.status === 'UNKNOWN' || item.status === 'NOT_MARKED') statusClass = 'badge-warning';
      
      const statusBadge = `<span class="badge ${statusClass}"><span class="badge-dot"></span>${item.status}</span>`;
      
      // Reliability Index & Mini Progress Bar
      const isReliable = item.is_reliable;
      const reliableBadge = `
        <div>
          <div style="font-size: 0.775rem; font-weight: 600; color: ${isReliable ? 'var(--text-main)' : 'var(--color-warning)'};">
            ${isReliable ? 'High Reliability' : 'Under Review'}
          </div>
          <div style="width: 44px; height: 4px; background: var(--neutral-border); border-radius: 2px; margin-top: 0.25rem; overflow: hidden;">
            <div style="width: ${isReliable ? '100%' : '50%'}; height: 100%; background-color: ${isReliable ? 'var(--primary)' : 'var(--tertiary)'}; border-radius: 2px;"></div>
          </div>
        </div>
      `;
      
      // Context String
      let contextLabel = 'Regular Schedule';
      if (item.is_holiday) contextLabel = '<span style="color: var(--color-warning); font-weight: 600;">Holiday</span>';
      else if (item.is_cancelled) contextLabel = '<span style="color: var(--color-danger); font-weight: 600;">Cancelled</span>';
      else if (item.is_extra) contextLabel = '<span style="color: var(--color-info); font-weight: 600;">Extra Class</span>';
      else if (!item.is_scheduled) contextLabel = '<span style="color: var(--text-muted);">Unscheduled</span>';
      
      // Dispatch Status
      let dispatchStatus = `
        <span style="display: inline-flex; align-items: center; gap: 0.35rem; font-size: 0.775rem; color: var(--text-muted); font-family: var(--font-mono);">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          Sync OK
        </span>
      `;
      if (item.notification_status) {
        if (item.notification_dry_run) {
          dispatchStatus = `<span class="badge badge-warning" style="font-size: 0.68rem;">Dry Run Staged</span>`;
        } else {
          dispatchStatus = `<span class="badge badge-success" style="font-size: 0.68rem;">Verified Alert</span>`;
        }
      }
      
      const d = parseLocalDate(item.check_date).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
      
      // Development Safety: Never expose internal debug data or Python dicts in UI notes
      let notesSnippet = null;
      if (item.notes && typeof item.notes === 'string') {
        const raw = item.notes.trim();
        if (raw.toLowerCase().startsWith('has note')) {
          notesSnippet = raw.toLowerCase().includes('noted') ? 'Has Noted' : 'Has notes';
        } else if (raw.startsWith('{') && raw.endsWith('}')) {
          try {
            const parsed = JSON.parse(raw);
            if (parsed && typeof parsed === 'object') {
              notesSnippet = parsed.reason || parsed.message || parsed.note || null;
            }
          } catch (_) {
            const match = raw.match(/'(?:reason|note|message)'\s*:\s*'([^']+)'/);
            if (match) {
              notesSnippet = match[1];
            }
          }
        } else if (!raw.includes('{') && !raw.includes('retries')) {
          notesSnippet = raw;
        }
      }

      const isCleanNote = notesSnippet === 'Has notes' || notesSnippet === 'Has Noted';
      const noteText = isCleanNote ? notesSnippet : `Note: ${notesSnippet}`;
      const noteHtml = notesSnippet
        ? `<div style="font-size: 0.725rem; color: var(--text-muted); margin-top: 0.15rem; display: flex; align-items: center; gap: 0.25rem;">
            <span>📄 ${escapeHtml(noteText)}</span>
          </div>`
        : '';

      let categoryTag = 'CORE THEORY';
      const subName = (item.subject_name || '').toUpperCase();
      const subCode = (item.subject_code || '').toUpperCase();
      if (subName.includes('LAB') || subName.includes('PRACTICAL') || subCode.includes('LAB')) {
        categoryTag = 'PRACTICAL LAB';
      } else if (subName.includes('PROJECT') || subName.includes('CAPSTONE')) {
        categoryTag = 'PROJECT';
      }

      html += `
        <tr>
          <td>
            <div style="font-weight: 700; color: var(--text-main); font-size: 0.85rem; display: flex; align-items: center; gap: 0.35rem; flex-wrap: wrap;">
              <span>${d}</span>
              <span class="code-tag check-run-tag" style="font-size: 0.65rem; padding: 0.1rem 0.35rem; background: var(--neutral-surface); border: 1px solid var(--border-subtle);">Check #${item.check_id}</span>
            </div>
            ${noteHtml}
          </td>
          <td>
            <div style="display: flex; align-items: center; gap: 0.4rem;">
              <span class="code-tag">${escapeHtml(item.subject_code)}</span>
              <span class="category-tag">${categoryTag}</span>
            </div>
            <div style="font-weight: 600; color: var(--text-main); font-size: 0.85rem; margin-top: 0.2rem;">
              ${escapeHtml(item.subject_name || item.subject_code)}
            </div>
          </td>
          <td>${statusBadge}</td>
          <td>${reliableBadge}</td>
          <td style="font-size: 0.8rem; color: var(--text-body);">${contextLabel}</td>
          <td>${dispatchStatus}</td>
          <td style="text-align: right;">
            <button type="button" class="btn btn-secondary btn-sm" style="padding: 0.25rem 0.65rem; font-size: 0.725rem;" onclick="alert('Audit record: ${escapeHtml(item.subject_code)} on ${escapeHtml(item.check_date)}')">Details</button>
          </td>
        </tr>
      `;
    }
    this.els.tableBody.innerHTML = html;
  }
  
  updatePagination() {
    const limit = this.state.limit;
    const total = this.state.total;
    const offset = this.state.offset;
    const totalPages = Math.ceil(total / limit) || 1;
    const currentPage = Math.floor(offset / limit) + 1;
    
    const start = total === 0 ? 0 : offset + 1;
    const end = Math.min(offset + limit, total);
    
    if (this.els.paginationInfo) {
      this.els.paginationInfo.innerText = `Displaying ${start}–${end} of ${total} records • Rows per page: ${limit}`;
    }
    
    if (this.els.paginationControls) {
      let html = '';
      
      // Previous Page Button
      html += `
        <button type="button" class="pagination-btn" id="btn-history-prev" ${currentPage <= 1 ? 'disabled' : ''} title="Previous Page" aria-label="Previous Page">
          ‹
        </button>
      `;
      
      // Page Number Buttons matching Stitch (1, 2, 3...)
      let startPage = Math.max(1, currentPage - 1);
      let endPage = Math.min(totalPages, startPage + 2);
      if (endPage - startPage < 2) {
        startPage = Math.max(1, endPage - 2);
      }
      
      for (let p = startPage; p <= endPage; p++) {
        const isActive = p === currentPage;
        html += `
          <button type="button" class="pagination-btn ${isActive ? 'active' : ''}" data-page="${p}" aria-current="${isActive ? 'page' : 'false'}">
            ${p}
          </button>
        `;
      }
      
      // Next Page Button
      html += `
        <button type="button" class="pagination-btn" id="btn-history-next" ${currentPage >= totalPages ? 'disabled' : ''} title="Next Page" aria-label="Next Page">
          ›
        </button>
      `;
      
      this.els.paginationControls.innerHTML = html;
      
      // Attach listeners
      const prevBtn = this.els.paginationControls.querySelector('#btn-history-prev');
      if (prevBtn && !prevBtn.disabled) {
        prevBtn.addEventListener('click', () => {
          if (this.state.offset > 0) {
            this.state.offset = Math.max(0, this.state.offset - this.state.limit);
            this.loadData();
          }
        });
      }
      
      const nextBtn = this.els.paginationControls.querySelector('#btn-history-next');
      if (nextBtn && !nextBtn.disabled) {
        nextBtn.addEventListener('click', () => {
          if (this.state.offset + this.state.limit < this.state.total) {
            this.state.offset += this.state.limit;
            this.loadData();
          }
        });
      }
      
      const pageBtns = this.els.paginationControls.querySelectorAll('.pagination-btn[data-page]');
      pageBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
          const targetPage = parseInt(e.currentTarget.getAttribute('data-page'), 10);
          if (targetPage !== currentPage) {
            this.state.offset = (targetPage - 1) * this.state.limit;
            this.loadData();
          }
        });
      });
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
