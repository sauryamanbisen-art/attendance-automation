/**
 * @fileoverview Timetable Page Controller
 */

import { API } from '../api.js';

export class TimetableController {
  constructor() {
    this.els = {
      loading: document.getElementById('timetable-loading'),
      error: document.getElementById('timetable-error'),
      errorText: document.getElementById('timetable-error-text'),
      content: document.getElementById('timetable-content'),
      daysContainer: document.getElementById('timetable-days-container'),
      btnRetry: document.getElementById('btn-retry-timetable'),
      
      // Modal
      modal: document.getElementById('modal-timetable-slot'),
      modalTitle: document.getElementById('modal-timetable-title'),
      form: document.getElementById('form-timetable-slot'),
      btnShowAddModal: document.getElementById('btn-show-add-slot-modal'),
      btnCloseModal: document.getElementById('btn-close-timetable-modal'),
      btnCancelModal: document.getElementById('btn-cancel-timetable-modal'),
      
      // Form Inputs
      inputId: document.getElementById('input-slot-id'),
      inputSubject: document.getElementById('input-slot-subject'),
      inputWeekday: document.getElementById('input-slot-weekday'),
      inputStart: document.getElementById('input-slot-start'),
      inputEnd: document.getElementById('input-slot-end'),
      inputPeriod: document.getElementById('input-slot-period'),
      inputValidFrom: document.getElementById('input-slot-valid-from'),
      inputValidTo: document.getElementById('input-slot-valid-to'),
    };

    this.subjects = [];
    this.slots = [];
    this.weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

    this.bindEvents();
  }

  bindEvents() {
    if (this.els.btnRetry) {
      this.els.btnRetry.addEventListener('click', () => this.loadData());
    }

    if (this.els.btnShowAddModal) {
      this.els.btnShowAddModal.addEventListener('click', () => this.openModal());
    }

    if (this.els.btnCloseModal) {
      this.els.btnCloseModal.addEventListener('click', () => this.closeModal());
    }

    if (this.els.btnCancelModal) {
      this.els.btnCancelModal.addEventListener('click', () => this.closeModal());
    }

    if (this.els.form) {
      this.els.form.addEventListener('submit', (e) => this.handleSave(e));
    }
    
    // Delegate edit/delete clicks
    if (this.els.daysContainer) {
      this.els.daysContainer.addEventListener('click', (e) => {
        const editBtn = e.target.closest('.btn-edit-slot');
        if (editBtn) {
          const id = parseInt(editBtn.dataset.id, 10);
          this.openEditModal(id);
        }
        
        const deleteBtn = e.target.closest('.btn-delete-slot');
        if (deleteBtn) {
          const id = parseInt(deleteBtn.dataset.id, 10);
          this.handleDelete(id);
        }
      });
    }

    // Keep card heights synchronized on resize
    window.addEventListener('resize', () => this.syncDayCardHeights());
  }

  showState(state) {
    this.els.loading.style.display = state === 'loading' ? 'block' : 'none';
    this.els.error.style.display = state === 'error' ? 'block' : 'none';
    this.els.content.style.display = state === 'content' ? 'block' : 'none';
    if (state === 'content') {
      requestAnimationFrame(() => this.syncDayCardHeights());
    }
  }

  async loadData() {
    this.showState('loading');
    try {
      const [subjects, slots] = await Promise.all([
        API.subjects.list(),
        API.timetable.listSlots()
      ]);
      this.subjects = subjects;
      this.slots = slots;
      
      this.populateSubjectsDropdown();
      this.render();
      
      this.showState('content');
    } catch (err) {
      this.els.errorText.innerText = err.message || 'Unknown error occurred while fetching timetable data.';
      this.showState('error');
    }
  }

  populateSubjectsDropdown() {
    let html = '<option value="">Select a subject...</option>';
    for (const sub of this.subjects) {
      html += `<option value="${sub.id}">${escapeHtml(sub.code)} - ${escapeHtml(sub.name)}</option>`;
    }
    this.els.inputSubject.innerHTML = html;
  }

  render() {
    // Group slots by weekday
    const grouped = {};
    for (let i = 0; i < 7; i++) {
      grouped[i] = [];
    }
    
    for (const slot of this.slots) {
      if (grouped[slot.weekday] !== undefined) {
        grouped[slot.weekday].push(slot);
      }
    }
    
    // Sort slots within each day by start time
    for (let i = 0; i < 7; i++) {
      grouped[i].sort((a, b) => a.start_time.localeCompare(b.start_time));
    }

    const todayWeekday = (new Date().getDay() + 6) % 7; // Convert JS 0=Sun to 0=Mon

    // Display Monday through Saturday (6 days), or 7 if Sunday has slots
    const daysToRender = (grouped[6] && grouped[6].length > 0) ? 7 : 6;

    let html = '';
    for (let i = 0; i < daysToRender; i++) {
      const daySlots = grouped[i];
      const isToday = i === todayWeekday;
      
      html += `
        <div class="timetable-day-card" data-day="${i}">
          <div class="timetable-day-header">
            <div class="timetable-day-title-wrap">
              <h3 class="timetable-day-title">${this.weekdays[i]}</h3>
              ${isToday ? '<span class="timetable-today-badge">TODAY</span>' : ''}
            </div>
            <span class="timetable-day-count">${daySlots.length} class${daySlots.length === 1 ? '' : 'es'}</span>
          </div>
          <div class="timetable-day-body">
      `;

      if (daySlots.length === 0) {
        html += `
          <div class="timetable-empty-state">
            <svg class="timetable-empty-icon" width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <rect x="3" y="4" width="18" height="18" rx="3" ry="3"/>
              <line x1="16" y1="2" x2="16" y2="6"/>
              <line x1="8" y1="2" x2="8" y2="6"/>
              <line x1="3" y1="10" x2="21" y2="10"/>
            </svg>
            <div class="timetable-empty-title">No classes scheduled</div>
            <div class="timetable-empty-desc">${i === 5 ? 'Enjoy your free day!' : 'No classes for this day'}</div>
          </div>
        `;
      } else {
        html += `<div class="timetable-slots-list">`;
        for (const slot of daySlots) {
          const subject = this.subjects.find(s => s.id === slot.subject_id);
          const subjName = subject ? subject.code : 'Unknown';
          const subjFullName = subject ? subject.name : '';
          
          html += `
            <div class="timetable-slot-card">
              <div class="timetable-slot-top-row">
                <span class="timetable-code-badge">${escapeHtml(subjName)}</span>
                <div class="timetable-slot-actions">
                  <button type="button" class="timetable-btn-action timetable-btn-edit btn-edit-slot" data-id="${slot.id}" aria-label="Edit ${escapeHtml(subjName)} class" title="Edit Class">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                    </svg>
                    <span>Edit</span>
                  </button>
                  <button type="button" class="timetable-btn-action timetable-btn-delete btn-delete-slot" data-id="${slot.id}" aria-label="Delete ${escapeHtml(subjName)} class" title="Delete Class">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <polyline points="3 6 5 6 21 6"/>
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                    </svg>
                    <span>Delete</span>
                  </button>
                </div>
              </div>

              ${subjFullName ? `<div class="timetable-slot-name">${escapeHtml(subjFullName)}</div>` : ''}

              <div class="timetable-slot-meta">
                <div class="timetable-slot-time">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <circle cx="12" cy="12" r="10"/>
                    <polyline points="12 6 12 12 16 14"/>
                  </svg>
                  <span>${slot.start_time.slice(0, 5)} - ${slot.end_time.slice(0, 5)}</span>
                </div>

                ${slot.period_name ? `
                  <div class="timetable-slot-period">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
                      <circle cx="12" cy="10" r="3"/>
                    </svg>
                    <span>${escapeHtml(slot.period_name)}</span>
                  </div>
                ` : ''}

                ${slot.valid_from || slot.valid_to ? `
                  <div class="timetable-slot-validity">
                    Valid: ${slot.valid_from ? slot.valid_from : 'Start'} to ${slot.valid_to ? slot.valid_to : 'End'}
                  </div>
                ` : ''}
              </div>
            </div>
          `;
        }
        html += `</div>`;
      }

      html += `
          </div>
        </div>
      `;
    }

    this.els.daysContainer.innerHTML = html;
    requestAnimationFrame(() => this.syncDayCardHeights());
  }

  syncDayCardHeights() {
    if (!this.els.daysContainer) return;
    const cards = this.els.daysContainer.querySelectorAll('.timetable-day-card');
    if (!cards.length) return;

    // Reset inline min-height first to compute natural layout heights
    cards.forEach(card => {
      card.style.minHeight = '';
    });

    // In multi-column views (> 640px), synchronize card heights to the tallest
    if (window.innerWidth > 640) {
      let maxHeight = 0;
      cards.forEach(card => {
        const h = card.getBoundingClientRect().height;
        if (h > maxHeight) maxHeight = h;
      });

      if (maxHeight > 0) {
        cards.forEach(card => {
          card.style.minHeight = `${Math.ceil(maxHeight)}px`;
        });
      }
    }
  }

  openModal() {
    this.els.modalTitle.innerText = 'Add Class';
    this.els.form.reset();
    this.els.inputId.value = '';
    this.els.modal.style.display = 'flex';
  }

  openEditModal(id) {
    const slot = this.slots.find(s => s.id === id);
    if (!slot) return;
    
    this.els.modalTitle.innerText = 'Edit Class';
    this.els.form.reset();
    
    this.els.inputId.value = slot.id;
    this.els.inputSubject.value = slot.subject_id;
    this.els.inputWeekday.value = slot.weekday;
    this.els.inputStart.value = slot.start_time.slice(0, 5); // HTML time input needs HH:MM
    this.els.inputEnd.value = slot.end_time.slice(0, 5);
    this.els.inputPeriod.value = slot.period_name || '';
    this.els.inputValidFrom.value = slot.valid_from || '';
    this.els.inputValidTo.value = slot.valid_to || '';
    
    this.els.modal.style.display = 'flex';
  }

  closeModal() {
    this.els.modal.style.display = 'none';
  }

  async handleSave(e) {
    e.preventDefault();
    
    const id = this.els.inputId.value;
    const payload = {
      subject_id: parseInt(this.els.inputSubject.value, 10),
      weekday: parseInt(this.els.inputWeekday.value, 10),
      start_time: this.els.inputStart.value + ':00', // Backend expects time with seconds usually or parseable HH:MM
      end_time: this.els.inputEnd.value + ':00',
      period_name: this.els.inputPeriod.value.trim() || null,
      valid_from: this.els.inputValidFrom.value || null,
      valid_to: this.els.inputValidTo.value || null,
    };
    
    try {
      const submitBtn = this.els.form.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      submitBtn.innerText = 'Saving...';
      
      if (id) {
        await API.timetable.updateSlot(parseInt(id, 10), payload);
        window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Class updated successfully', type: 'success' }}));
      } else {
        await API.timetable.createSlot(payload);
        window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Class created successfully', type: 'success' }}));
      }
      
      this.closeModal();
      await this.loadData();
    } catch (err) {
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: `Validation Error: ${err.message}`, type: 'error' }}));
    } finally {
      const submitBtn = this.els.form.querySelector('button[type="submit"]');
      submitBtn.disabled = false;
      submitBtn.innerText = 'Save Class';
    }
  }

  async handleDelete(id) {
    if (!confirm('Are you sure you want to delete this class? This will affect attendance scheduling.')) {
      return;
    }
    
    try {
      await API.timetable.deleteSlot(id);
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Class deleted successfully', type: 'success' }}));
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
