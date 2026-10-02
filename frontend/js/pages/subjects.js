/**
 * @fileoverview Subjects Page Controller
 */

import { API } from '../api.js';

export class SubjectsController {
  constructor() {
    this.els = {
      loading: document.getElementById('subjects-loading'),
      error: document.getElementById('subjects-error'),
      errorText: document.getElementById('subjects-error-text'),
      content: document.getElementById('subjects-content'),
      
      btnRetry: document.getElementById('btn-retry-subjects'),
      container: document.getElementById('subjects-container'),
      
      // Modal
      modal: document.getElementById('modal-subject'),
      modalTitle: document.getElementById('modal-subject-title'),
      form: document.getElementById('form-subject'),
      btnShowAddModal: document.getElementById('btn-show-add-subject-modal'),
      btnCloseModal: document.getElementById('btn-close-subject-modal'),
      btnCancelModal: document.getElementById('btn-cancel-subject-modal'),
      
      // Form Inputs
      inputOriginalCode: document.getElementById('input-subject-original-code'),
      inputCode: document.getElementById('input-subject-code'),
      inputName: document.getElementById('input-subject-name'),
      inputProfName: document.getElementById('input-prof-name'),
      inputProfEmail: document.getElementById('input-prof-email'),
      inputChatSpace: document.getElementById('input-chat-space'),
      btnDiscoverChatSpace: document.getElementById('btn-discover-chat-space'),
      inputProfActive: document.getElementById('input-prof-active'),
      
      // Search & Filters
      searchInput: document.getElementById('search-subjects-input'),
      filterPills: document.querySelectorAll('#subjects-filter-pills .filter-pill'),
    };

    this.subjects = [];
    this.appSettings = null;
    this.historyItems = [];
    this.activeFilter = 'all';
    this.searchQuery = '';

    this.bindEvents();
  }

  bindEvents() {
    if (this.els.btnRetry) this.els.btnRetry.addEventListener('click', () => this.loadData());
    
    if (this.els.btnShowAddModal) this.els.btnShowAddModal.addEventListener('click', () => this.openModal());
    if (this.els.btnCloseModal) this.els.btnCloseModal.addEventListener('click', () => this.closeModal());
    if (this.els.btnCancelModal) this.els.btnCancelModal.addEventListener('click', () => this.closeModal());
    if (this.els.btnDiscoverChatSpace) this.els.btnDiscoverChatSpace.addEventListener('click', () => this.handleDiscoverChatSpace());
    if (this.els.form) this.els.form.addEventListener('submit', (e) => this.handleSave(e));

    // Search input
    if (this.els.searchInput) {
      this.els.searchInput.addEventListener('input', (e) => {
        this.searchQuery = e.target.value.toLowerCase().trim();
        this.render();
      });
    }

    // Filter pills
    if (this.els.filterPills) {
      this.els.filterPills.forEach(pill => {
        pill.addEventListener('click', (e) => {
          this.els.filterPills.forEach(p => p.classList.remove('active'));
          e.currentTarget.classList.add('active');
          this.activeFilter = e.currentTarget.getAttribute('data-filter') || 'all';
          this.render();
        });
      });
    }

    // Delegation for edit/delete buttons
    if (this.els.container) {
      this.els.container.addEventListener('click', (e) => {
        const editBtn = e.target.closest('.btn-edit-subject');
        if (editBtn) {
          this.openEditModal(editBtn.dataset.code);
        }

        const deleteBtn = e.target.closest('.btn-delete-subject');
        if (deleteBtn) {
          this.handleDelete(deleteBtn.dataset.code);
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
      const [subjectsRes, settingsRes, summaryRes] = await Promise.allSettled([
        API.subjects.list(),
        API.settings.read(),
        API.history.getSummary()
      ]);

      this.subjects = subjectsRes.status === 'fulfilled' ? subjectsRes.value : [];
      this.appSettings = settingsRes.status === 'fulfilled' ? settingsRes.value : null;
      this.summary = summaryRes.status === 'fulfilled' ? summaryRes.value : null;

      this.render();
      this.showState('content');
    } catch (err) {
      this.els.errorText.innerText = err.message || 'Unknown error occurred while fetching subjects.';
      this.showState('error');
    }
  }

  render() {
    // 1. Calculate real stats
    const totalSubjects = this.subjects.length;
    const mapped = this.subjects.filter(s => s.professor_name && s.professor_email).length;
    const unmapped = totalSubjects - mapped;
    const spacesCount = this.subjects.filter(s => !!s.google_chat_space).length;
    const isDry = this.appSettings ? this.appSettings.dry_run : true;

    // Development Safety: Never display synthetic attendance information.
    // Authoritative academic attendance from PWIOI portal extraction.
    const acad = this.summary?.academic_attendance;
    const overallRate = (acad && typeof acad.overall_rate === 'number')
      ? `${acad.overall_rate.toFixed(1)}%`
      : 'Awaiting Sync';

    // 2. Update Top Stat Cards
    const countEl = document.getElementById('stat-subject-count');
    if (countEl) countEl.innerText = `${totalSubjects} Courses`;

    const mappedHint = document.getElementById('stat-subject-mapped-hint');
    if (mappedHint) mappedHint.innerText = mapped === totalSubjects ? '✔ All Mapped' : `${mapped} of ${totalSubjects} Mapped`;

    const liveBadge = document.getElementById('subjects-channels-live-badge');
    if (liveBadge) liveBadge.innerHTML = `<span class="badge-dot"></span>${mapped} Active Channels`;

    const avgRateEl = document.getElementById('stat-subject-avg-rate');
    if (avgRateEl) {
      avgRateEl.innerText = overallRate;
    }

    const spacesEl = document.getElementById('stat-subject-spaces');
    if (spacesEl) spacesEl.innerText = `${spacesCount} Validated`;

    const sandboxEl = document.getElementById('stat-subject-sandbox');
    if (sandboxEl) sandboxEl.innerText = isDry ? 'Safe Mode' : 'Live Active';

    // 3. Filter list
    let filtered = this.subjects.filter(sub => {
      const isMapped = !!(sub.professor_name && sub.professor_email);
      if (this.activeFilter === 'mapped' && !isMapped) return false;
      if (this.activeFilter === 'unmapped' && isMapped) return false;

      if (this.searchQuery) {
        const q = this.searchQuery;
        const matchCode = (sub.code || '').toLowerCase().includes(q);
        const matchName = (sub.name || '').toLowerCase().includes(q);
        const matchProf = (sub.professor_name || '').toLowerCase().includes(q);
        const matchSpace = (sub.google_chat_space || '').toLowerCase().includes(q);
        if (!matchCode && !matchName && !matchProf && !matchSpace) return false;
      }
      return true;
    });

    if (filtered.length === 0) {
      this.els.container.innerHTML = `<div style="padding: 3rem 1.5rem; text-align: center; color: var(--text-muted); background: var(--neutral-white); border-radius: var(--radius-lg); border: 1px solid var(--border-medium);">No subjects found matching your criteria.</div>`;
      return;
    }

    let html = '';
    for (let i = 0; i < filtered.length; i++) {
      const sub = filtered[i];
      const hasProf = !!sub.professor_name;
      const hasEmail = !!sub.professor_email;
      const hasSpace = !!sub.google_chat_space;
      const mappingValid = hasProf && hasEmail;
      const isActive = sub.is_active !== false;
      
      let badgeClass = 'badge-warning';
      let badgeText = 'No Valid Mapping';
      if (mappingValid) {
        if (isActive) {
          badgeClass = 'badge-success';
          badgeText = 'Mapped & Active';
        } else {
          badgeClass = 'badge-neutral';
          badgeText = 'Notifications Disabled';
        }
      }

      // Development Safety: Never display synthetic attendance information.
      // Standings must come from authoritative PWIOI portal extraction or truthful "Awaiting Sync".
      let standingPercentText = 'Awaiting Sync';
      let standingSubtext = 'Awaiting portal sync';
      let isSafe = true;
      let hasPortalData = false;

      if (typeof sub.academic_rate === 'number') {
        standingPercentText = `${sub.academic_rate.toFixed(1)}%`;
        if (sub.attended_classes !== null && sub.total_classes !== null) {
          standingSubtext = `${sub.attended_classes} of ${sub.total_classes} classes attended`;
        } else {
          standingSubtext = 'Portal verified attendance';
        }
        isSafe = sub.academic_rate >= 75.0;
        hasPortalData = true;
      }

      html += `
        <div class="subject-card">
          <div class="subject-card-header">
            <div class="subject-card-title-group">
              <span class="code-tag">${escapeHtml(sub.code)}</span>
              <h3 style="font-size: 1.05rem; font-weight: 700; color: var(--text-main); margin: 0;">${escapeHtml(sub.name)}</h3>
              <span class="badge ${badgeClass}"><span class="badge-dot"></span>${badgeText}</span>
            </div>
            <div style="display: flex; align-items: center; gap: 0.65rem;">
              <button type="button" class="btn btn-primary btn-sm btn-edit-subject" data-code="${escapeHtml(sub.code)}">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>
                </svg>
                <span>Edit Mapping</span>
              </button>
              <button type="button" class="btn-icon-round btn-delete-subject" data-code="${escapeHtml(sub.code)}" title="Delete Subject" style="color: var(--color-danger); border-color: var(--tertiary-border);">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                </svg>
              </button>
            </div>
          </div>
          
          <div class="subject-card-grid">
            <!-- Column 1: Instructor Contact -->
            <div>
              <div class="subject-grid-col-label">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/></svg>
                <span>Instructor Contact</span>
              </div>
              <div style="display: flex; align-items: center; gap: 0.75rem;">
                <div style="width: 34px; height: 34px; border-radius: 50%; background-color: var(--neutral-light); border: 1px solid var(--border-medium); display: flex; align-items: center; justify-content: center; font-size: 0.9rem; flex-shrink: 0;">
                  🎓
                </div>
                <div>
                  <div style="font-weight: 700; color: var(--text-main); font-size: 0.9rem;">
                    ${hasProf ? escapeHtml(sub.professor_name) : 'Not configured'}
                  </div>
                  <div style="font-size: 0.775rem; color: var(--text-muted);">
                    ${hasEmail ? escapeHtml(sub.professor_email) : 'No email specified'}
                  </div>
                </div>
              </div>
            </div>

            <!-- Column 2: Google Chat Destination -->
            <div>
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem;">
                <div class="subject-grid-col-label" style="margin-bottom: 0;">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                  <span>Google Chat Destination</span>
                </div>
                <span style="font-size: 0.72rem; color: ${hasSpace ? 'var(--color-success)' : 'var(--text-muted)'}; font-weight: 600;">
                  ${hasSpace ? '✓ Space Configured &amp; Verified' : '○ Unconfigured'}
                </span>
              </div>
              
              <div class="subject-chat-box">
                <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-right: 0.5rem;">
                  ${hasSpace ? escapeHtml(sub.google_chat_space) : 'No Google Chat space assigned'}
                </span>
                ${hasSpace ? `
                  <button type="button" style="background: none; border: none; cursor: pointer; color: var(--neutral-subtle); padding: 0.15rem;" onclick="navigator.clipboard.writeText('${escapeHtml(sub.google_chat_space)}'); alert('Copied space destination.');" title="Copy Space ID">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                  </button>
                ` : ''}
              </div>

              <div style="display: flex; align-items: center; gap: 0.4rem; font-size: 0.725rem; color: var(--text-muted);">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                <span>Auto-notify on discrepancy before 5:00 PM IST cutoff</span>
              </div>
            </div>

            <!-- Column 3: Verified Standing -->
            <div>
              <div class="subject-grid-col-label">
                <span>Verified Standing</span>
              </div>
              <div class="subject-standing-box">
                <div>
                  <div class="subject-standing-rate">${standingPercentText}</div>
                  <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.2rem;">
                    ${standingSubtext}
                  </div>
                </div>
                <div class="subject-check-circle" style="${!hasPortalData ? 'background-color: var(--neutral-light); color: var(--text-muted); border-color: var(--border-medium);' : (!isSafe ? 'background-color: var(--tertiary-light); color: var(--tertiary); border-color: var(--tertiary-border);' : '')}" title="${!hasPortalData ? 'Awaiting portal synchronization' : (isSafe ? 'Standing verified safe' : 'Attendance below threshold')}">
                  ${!hasPortalData ? '⏳' : (isSafe ? '✓' : '!')}
                </div>
              </div>
            </div>
          </div>
        </div>
      `;
    }
    
    this.els.container.innerHTML = html;
  }

  closeModal() {
    this.els.modal.style.display = 'none';
  }

  openModal() {
    this.els.modalTitle.innerText = 'Add Subject';
    this.els.form.reset();
    this.els.inputOriginalCode.value = '';
    if (this.els.inputProfActive) {
      this.els.inputProfActive.checked = true;
    }
    this.els.modal.style.display = 'flex';
  }

  openEditModal(code) {
    const sub = this.subjects.find(s => s.code === code);
    if (!sub) return;
    
    this.els.modalTitle.innerText = 'Edit Subject';
    this.els.form.reset();
    
    this.els.inputOriginalCode.value = sub.code;
    this.els.inputCode.value = sub.code;
    this.els.inputName.value = sub.name;
    this.els.inputProfName.value = sub.professor_name || '';
    this.els.inputProfEmail.value = sub.professor_email || '';
    this.els.inputChatSpace.value = sub.google_chat_space || '';
    if (this.els.inputProfActive) {
      this.els.inputProfActive.checked = sub.is_active !== false;
    }
    
    this.els.modal.style.display = 'flex';
  }

  async handleDiscoverChatSpace() {
    const profEmail = this.els.inputProfEmail ? this.els.inputProfEmail.value.trim() : '';
    if (!profEmail) {
      window.dispatchEvent(new CustomEvent('app-alert', {
        detail: { message: 'Please enter a professor email first to discover their Google Chat DM space.', type: 'warning' }
      }));
      if (this.els.inputProfEmail) this.els.inputProfEmail.focus();
      return;
    }

    const emailRegex = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
    if (!emailRegex.test(profEmail)) {
      window.dispatchEvent(new CustomEvent('app-alert', {
        detail: { message: 'Please enter a valid professor email address.', type: 'error' }
      }));
      return;
    }

    const googleChatApi = (API && API.googleChat) || (typeof window !== 'undefined' && window.API && window.API.googleChat);
    if (!googleChatApi || typeof googleChatApi.discoverDm !== 'function') {
      window.dispatchEvent(new CustomEvent('app-alert', {
        detail: { message: 'Google Chat API client is not initialized.', type: 'error' }
      }));
      return;
    }

    const originalBtnText = this.els.btnDiscoverChatSpace.innerText;
    this.els.btnDiscoverChatSpace.disabled = true;
    this.els.btnDiscoverChatSpace.innerText = 'Discovering...';
    this.els.btnDiscoverChatSpace.setAttribute('aria-busy', 'true');

    try {
      const subjectCode = this.els.inputCode ? this.els.inputCode.value.trim() : null;
      const res = await googleChatApi.discoverDm(profEmail, subjectCode || null);
      if (res && res.space) {
        this.els.inputChatSpace.value = res.space;
        window.dispatchEvent(new CustomEvent('app-alert', {
          detail: { message: res.message || `Discovered Google Chat space: ${res.space}`, type: 'success' }
        }));
      }
    } catch (err) {
      let errMsg = err.message || 'Failed to discover Google Chat DM space.';
      if (err.status === 401) {
        errMsg = (err.message && err.message.toLowerCase().includes('connected'))
          ? err.message
          : 'Google Chat OAuth is not connected or token expired. Please connect Google Chat in Settings.';
      } else if (err.status === 403) {
        errMsg = (err.message && err.message.toLowerCase().includes('permission'))
          ? err.message
          : 'Google Chat permission denied. The connected account requires chat.spaces.readonly scope.';
      } else if (err.status === 404) {
        errMsg = (err.message && err.message.toLowerCase().includes('direct message'))
          ? err.message
          : 'No direct message space exists with this professor. A direct message conversation must be initiated first in Google Chat.';
      } else if (err.status === 429) {
        errMsg = 'Google Chat API rate limit exceeded. Please wait a moment before trying again.';
      } else if (err.status === 502) {
        errMsg = (err.message && err.message.toLowerCase().includes('google chat api'))
          ? err.message
          : 'Google Chat API service unavailable. Please try again later.';
      }

      window.dispatchEvent(new CustomEvent('app-alert', {
        detail: { message: errMsg, type: 'error' }
      }));
    } finally {
      this.els.btnDiscoverChatSpace.disabled = false;
      this.els.btnDiscoverChatSpace.innerText = originalBtnText;
      this.els.btnDiscoverChatSpace.removeAttribute('aria-busy');
    }
  }

  async handleSave(e) {
    e.preventDefault();
    
    const originalCode = this.els.inputOriginalCode.value;
    
    const code = this.els.inputCode.value.trim();
    const name = this.els.inputName.value.trim();
    const profName = this.els.inputProfName.value.trim() || null;
    const profEmail = this.els.inputProfEmail.value.trim() || null;
    const chatSpace = this.els.inputChatSpace.value.trim() || null;
    const isActive = this.els.inputProfActive ? this.els.inputProfActive.checked : true;

    if (!code || !name) {
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Subject Code and Subject Name are required.', type: 'error' }}));
      return;
    }

    // Safety verification check: if you provide name, you must provide email, and vice versa.
    if ((profName && !profEmail) || (!profName && profEmail)) {
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Professor mapping requires both Name and Email.', type: 'error' }}));
      return;
    }

    // Email format validation
    const emailRegex = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
    if (profEmail && !emailRegex.test(profEmail)) {
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Please enter a valid professor email address.', type: 'error' }}));
      return;
    }

    // Chat space format validation (no whitespace allowed)
    if (chatSpace && /\s/.test(chatSpace)) {
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Google Chat space resource name cannot contain spaces.', type: 'error' }}));
      return;
    }

    const payload = {
      code,
      name,
      professor_name: profName,
      professor_email: profEmail,
      google_chat_space: chatSpace,
      is_active: isActive,
    };
    
    try {
      const submitBtn = this.els.form.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      submitBtn.innerText = 'Saving...';
      
      if (originalCode) {
        await API.subjects.update(originalCode, payload);
        window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Subject updated successfully', type: 'success' }}));
      } else {
        await API.subjects.create(payload);
        window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Subject created successfully', type: 'success' }}));
      }
      
      this.closeModal();
      await this.loadData();
    } catch (err) {
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: `Validation Error: ${err.message}`, type: 'error' }}));
    } finally {
      const submitBtn = this.els.form.querySelector('button[type="submit"]');
      submitBtn.disabled = false;
      submitBtn.innerText = 'Save Subject';
    }
  }

  async handleDelete(code) {
    if (!confirm('Are you sure you want to delete this subject? This will permanently delete any associated professor mapping, classes, and exceptions!')) {
      return;
    }
    
    try {
      await API.subjects.delete(code);
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Subject deleted successfully', type: 'success' }}));
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
