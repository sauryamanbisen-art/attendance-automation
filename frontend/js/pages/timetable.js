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
  }

  showState(state) {
    this.els.loading.style.display = state === 'loading' ? 'block' : 'none';
    this.els.error.style.display = state === 'error' ? 'block' : 'none';
    this.els.content.style.display = state === 'content' ? 'block' : 'none';
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

    let html = '';
    for (let i = 0; i < 7; i++) {
      const daySlots = grouped[i];
      const isToday = i === todayWeekday;
      
      html += `
        <div class="card" style="padding: 1rem; border-top: ${isToday ? '3px solid var(--accent-primary)' : '1px solid var(--border-subtle)'}; background: ${isToday ? 'var(--bg-card-elevated)' : 'var(--bg-card)'}">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; padding-bottom: 0.5rem; border-bottom: 1px solid var(--border-subtle);">
            <h3 class="card-title" style="font-size: 1rem; color: ${isToday ? 'var(--text-main)' : 'var(--text-muted)'}">
              ${this.weekdays[i]} ${isToday ? '<span class="badge badge-success" style="margin-left: 0.5rem; font-size: 0.6rem;">TODAY</span>' : ''}
            </h3>
            <span style="font-size: 0.75rem; color: var(--text-subtle);">${daySlots.length} class${daySlots.length === 1 ? '' : 'es'}</span>
          </div>
      `;

      if (daySlots.length === 0) {
        html += `<div style="text-align: center; color: var(--text-subtle); font-size: 0.8rem; padding: 1rem 0;">No classes scheduled</div>`;
      } else {
        html += `<div style="display: flex; flex-direction: column; gap: 0.75rem;">`;
        for (const slot of daySlots) {
          const subject = this.subjects.find(s => s.id === slot.subject_id);
          const subjName = subject ? subject.code : 'Unknown';
          
          html += `
            <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 0.75rem;">
              <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem;">
                <strong style="color: var(--text-main); font-size: 0.9rem;">${escapeHtml(subjName)}</strong>
                <div style="display: flex; gap: 0.25rem;">
                  <button class="btn-edit-slot" data-id="${slot.id}" style="background:none; border:none; color:var(--text-muted); cursor:pointer; padding: 0.2rem;" title="Edit">✏️</button>
                  <button class="btn-delete-slot" data-id="${slot.id}" style="background:none; border:none; color:var(--color-danger); cursor:pointer; padding: 0.2rem;" title="Delete">🗑️</button>
                </div>
              </div>
              
              <div style="font-size: 0.8rem; color: var(--text-muted); display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.25rem;">
                <span aria-hidden="true">⏱️</span> ${slot.start_time.slice(0, 5)} - ${slot.end_time.slice(0, 5)}
              </div>
              
              ${slot.period_name ? `<div style="font-size: 0.75rem; color: var(--text-subtle);">📍 ${escapeHtml(slot.period_name)}</div>` : ''}
              ${slot.valid_from || slot.valid_to ? `
                <div style="font-size: 0.7rem; margin-top: 0.4rem; color: var(--color-warning);">
                  Valid: ${slot.valid_from ? slot.valid_from : 'Start'} to ${slot.valid_to ? slot.valid_to : 'End'}
                </div>
              ` : ''}
            </div>
          `;
        }
        html += `</div>`;
      }
      
      html += `</div>`;
    }
    
    this.els.daysContainer.innerHTML = html;
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
