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
    };

    this.subjects = [];

    this.bindEvents();
  }

  bindEvents() {
    if (this.els.btnRetry) this.els.btnRetry.addEventListener('click', () => this.loadData());
    
    if (this.els.btnShowAddModal) this.els.btnShowAddModal.addEventListener('click', () => this.openModal());
    if (this.els.btnCloseModal) this.els.btnCloseModal.addEventListener('click', () => this.closeModal());
    if (this.els.btnCancelModal) this.els.btnCancelModal.addEventListener('click', () => this.closeModal());
    if (this.els.form) this.els.form.addEventListener('submit', (e) => this.handleSave(e));

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
      this.subjects = await API.subjects.list();
      this.render();
      this.showState('content');
    } catch (err) {
      this.els.errorText.innerText = err.message || 'Unknown error occurred while fetching subjects.';
      this.showState('error');
    }
  }

  render() {
    if (this.subjects.length === 0) {
      this.els.container.innerHTML = `<div style="padding: 2rem; text-align: center; color: var(--text-muted);">No subjects found.</div>`;
      return;
    }

    let html = '';
    for (const sub of this.subjects) {
      const hasProf = !!sub.professor_name;
      const hasEmail = !!sub.professor_email;
      const mappingValid = hasProf && hasEmail;
      
      const badgeClass = mappingValid ? 'badge-success' : 'badge-warning';
      const badgeText = mappingValid ? 'Mapped' : 'No Valid Mapping';

      html += `
        <div class="card" style="margin-bottom: 1rem; padding: 1.25rem;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem;">
            <div>
              <h3 style="color: var(--text-main); font-size: 1.1rem; margin-bottom: 0.25rem;">
                <span style="color: var(--accent-light); margin-right: 0.5rem;">${escapeHtml(sub.code)}</span> 
                ${escapeHtml(sub.name)}
              </h3>
              <span class="badge ${badgeClass}"><span class="badge-dot"></span>${badgeText}</span>
            </div>
            <div style="display: flex; gap: 0.5rem;">
              <button class="btn btn-secondary btn-edit-subject" data-code="${escapeHtml(sub.code)}" style="padding: 0.4rem 0.75rem;">Edit</button>
              <button class="btn btn-danger btn-delete-subject" data-code="${escapeHtml(sub.code)}" style="padding: 0.4rem 0.75rem;">Delete</button>
            </div>
          </div>
          
          <div style="background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 1rem;">
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">
              <div>
                <strong style="display: block; font-size: 0.75rem; text-transform: uppercase; color: var(--text-muted); margin-bottom: 0.25rem;">Professor Name</strong>
                <span style="color: ${hasProf ? 'var(--text-main)' : 'var(--text-subtle)'};">${hasProf ? escapeHtml(sub.professor_name) : 'Not configured'}</span>
              </div>
              <div>
                <strong style="display: block; font-size: 0.75rem; text-transform: uppercase; color: var(--text-muted); margin-bottom: 0.25rem;">Professor Email</strong>
                <span style="color: ${hasEmail ? 'var(--text-main)' : 'var(--text-subtle)'};">${hasEmail ? escapeHtml(sub.professor_email) : 'Not configured'}</span>
              </div>
              <div>
                <strong style="display: block; font-size: 0.75rem; text-transform: uppercase; color: var(--text-muted); margin-bottom: 0.25rem;">Google Chat Space</strong>
                <span style="color: ${sub.google_chat_space ? 'var(--text-main)' : 'var(--text-subtle)'};">${sub.google_chat_space ? escapeHtml(sub.google_chat_space) : 'Not configured'}</span>
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
    
    this.els.modal.style.display = 'flex';
  }

  async handleSave(e) {
    e.preventDefault();
    
    const originalCode = this.els.inputOriginalCode.value;
    
    const payload = {
      code: this.els.inputCode.value.trim(),
      name: this.els.inputName.value.trim(),
      professor_name: this.els.inputProfName.value.trim() || null,
      professor_email: this.els.inputProfEmail.value.trim() || null,
      google_chat_space: this.els.inputChatSpace.value.trim() || null,
    };
    
    // Safety verification check: if you provide name, you must provide email, and vice versa.
    if ((payload.professor_name && !payload.professor_email) || (!payload.professor_name && payload.professor_email)) {
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Professor mapping requires both Name and Email.', type: 'error' }}));
      return;
    }
    
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
