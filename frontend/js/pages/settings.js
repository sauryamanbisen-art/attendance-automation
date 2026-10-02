/**
 * @fileoverview Settings Page Controller
 */

import { API } from '../api.js';

export class SettingsController {
  constructor() {
    this.els = {
      // Containers
      loading: document.getElementById('settings-loading'),
      error: document.getElementById('settings-error'),
      errorText: document.getElementById('settings-error-text'),
      content: document.getElementById('settings-content'),
      
      btnRetry: document.getElementById('btn-retry-settings'),
      
      // Fields
      fAppName: document.getElementById('setting-app-name'),
      fAppEnv: document.getElementById('setting-app-env'),
      fLogLevel: document.getElementById('setting-log-level'),
      fTimezone: document.getElementById('setting-timezone'),
      fDryRun: document.getElementById('setting-dry-run'),
      fDryRunBadge: document.getElementById('setting-dry-run-badge'),
      fDryRunToggle: document.getElementById('setting-dry-run-toggle'),
      fPortalAdapter: document.getElementById('setting-portal-adapter'),
      fPortalHeadless: document.getElementById('setting-portal-headless'),
      fBrowserChannel: document.getElementById('setting-browser-channel'),
      fEmailProvider: document.getElementById('setting-email-provider'),
      fNotificationSender: document.getElementById('setting-notification-sender'),
      fAutoCheck: document.getElementById('setting-auto-check'),
      
      // Session
      sessionStatusBadge: document.getElementById('session-status-badge'),
      sessionStatusText: document.getElementById('session-status-text'),
      sessionHandshake: document.getElementById('setting-session-handshake'),
      storageStateFilename: document.getElementById('setting-storage-state-filename'),
      btnClearSession: document.getElementById('btn-clear-session'),
      
      // Google Chat & Notifications
      gcBadge: document.getElementById('setting-gc-badge'),
      gcSpaceInput: document.getElementById('setting-gc-space-input'),
      btnCopyGcSpace: document.getElementById('btn-copy-gc-space'),
      btnTestPingGchat: document.getElementById('btn-test-ping-gchat'),
    };

    this.providersData = null;
    this.bindEvents();
  }

  bindEvents() {
    if (this.els.btnRetry) {
      this.els.btnRetry.addEventListener('click', () => this.loadData());
    }
    
    if (this.els.btnClearSession) {
      this.els.btnClearSession.addEventListener('click', () => this.clearSession());
    }

    if (this.els.btnCopyGcSpace && this.els.gcSpaceInput) {
      this.els.btnCopyGcSpace.addEventListener('click', () => {
        const val = this.els.gcSpaceInput.value;
        if (navigator.clipboard && val) {
          navigator.clipboard.writeText(val);
          window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Copied destination to clipboard.', type: 'info' } }));
        }
      });
    }

    if (this.els.btnTestPingGchat) {
      this.els.btnTestPingGchat.addEventListener('click', () => {
        const gc = this.providersData?.providers?.find(p => p.id === 'google_chat');
        if (gc && gc.connected) {
          window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Google Chat provider is connected and ready.', type: 'success' } }));
        } else if (gc && gc.is_configured) {
          window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Google Chat credentials are set in .env. Click "Connect" below to authenticate.', type: 'info' } }));
        } else {
          window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Safe Sandbox active: Notifications are simulated locally. Set Google Chat credentials in .env to connect.', type: 'info' } }));
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
    this.checkOAuthCallbackAlerts();
    this.showState('loading');
    try {
      const [settings, session, providers] = await Promise.all([
        API.settings.read(),
        API.settings.getSessionStatus(),
        API.notifications.getProviders()
      ]);
      
      this.providersData = providers;
      this.renderSettings(settings);
      this.renderSession(session, settings);
      this.renderProviders(providers);
      
      this.showState('content');
    } catch (err) {
      this.els.errorText.innerText = err.message || 'Unknown error occurred while fetching settings.';
      this.showState('error');
    }
  }

  checkOAuthCallbackAlerts() {
    let paramsStr = window.location.search;
    if (!paramsStr && window.location.hash.includes('?')) {
      paramsStr = window.location.hash.substring(window.location.hash.indexOf('?'));
    }
    if (paramsStr) {
      const urlParams = new URLSearchParams(paramsStr);
      if (urlParams.get('oauth_success')) {
        const prov = urlParams.get('oauth_success');
        const provName = prov === 'gmail' ? 'Gmail' : 'Google Chat';
        window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: `Successfully connected ${provName} provider.`, type: 'success' }}));
        window.history.replaceState({}, document.title, window.location.pathname + '#settings');
      } else if (urlParams.get('oauth_error')) {
        window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'OAuth authorization was cancelled or failed.', type: 'error' }}));
        window.history.replaceState({}, document.title, window.location.pathname + '#settings');
      }
    }
  }

  renderSettings(settings) {
    if (this.els.fAppName) this.els.fAppName.innerText = settings.app_name;
    if (this.els.fAppEnv) this.els.fAppEnv.innerText = settings.app_env;
    if (this.els.fLogLevel) this.els.fLogLevel.innerText = settings.log_level;
    if (this.els.fTimezone) this.els.fTimezone.innerText = `${settings.timezone} (IST +05:30)`;
    if (this.els.fDryRun) {
      this.els.fDryRun.innerHTML = settings.dry_run 
        ? '<span class="badge badge-warning">Enabled (Safe Mode)</span>'
        : '<span class="badge badge-danger">Disabled (Active Mode)</span>';
    }
    if (this.els.fDryRunBadge) {
      this.els.fDryRunBadge.className = settings.dry_run ? 'badge badge-warning' : 'badge badge-danger';
      this.els.fDryRunBadge.innerText = settings.dry_run ? 'Safe Sandbox' : 'Live Active';
    }
    if (this.els.fDryRunToggle) {
      this.els.fDryRunToggle.checked = !!settings.dry_run;
    }
      
    if (this.els.fPortalAdapter) this.els.fPortalAdapter.innerText = `${settings.portal_adapter.toUpperCase()} Adapter`;
    if (this.els.fPortalHeadless) this.els.fPortalHeadless.innerText = settings.portal_headless ? 'Headless Chrome' : 'Headed Chrome UI';
    if (this.els.fBrowserChannel) this.els.fBrowserChannel.innerText = settings.portal_browser_channel || 'Chromium Stable';
    if (this.els.fEmailProvider) this.els.fEmailProvider.innerText = settings.email_provider.toUpperCase();
    if (this.els.fNotificationSender) {
      const email = (settings.notification_sender_email && !settings.notification_sender_email.includes('example.edu'))
        ? settings.notification_sender_email
        : ((this.session && this.session.student_email) ? this.session.student_email : 'Not configured (.env)');
      this.els.fNotificationSender.innerText = email;
    }
    if (this.els.fAutoCheck) this.els.fAutoCheck.innerText = 'Post-lecture check (5:00 PM IST cutoff)';
  }
  
  renderProviders(data) {
    const container = document.getElementById('notification-providers-list');
    if (!container) return;
    
    const gc = data.providers.find(p => p.id === 'google_chat');
    if (this.els.gcBadge) {
      if (gc && gc.connected) {
        this.els.gcBadge.className = 'badge badge-success';
        this.els.gcBadge.innerHTML = '<span class="badge-dot"></span>Connected';
      } else if (gc && gc.is_configured) {
        this.els.gcBadge.className = 'badge badge-warning';
        this.els.gcBadge.innerText = 'Disconnected';
      } else {
        this.els.gcBadge.className = 'badge badge-neutral';
        this.els.gcBadge.innerText = 'Not Configured';
      }
    }

    if (this.els.gcSpaceInput) {
      if (gc && gc.account_identifier) {
        this.els.gcSpaceInput.value = gc.account_identifier;
      } else if (gc && gc.is_configured) {
        this.els.gcSpaceInput.value = 'OAuth Direct Message Routing';
      } else {
        this.els.gcSpaceInput.value = 'Configured via .env / OAuth';
      }
    }
    
    container.innerHTML = '';
    
    data.providers.forEach(provider => {
      const card = document.createElement('div');
      card.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 0.4rem 0.75rem; background: var(--neutral-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); margin-top: 0.35rem;';
      
      let statusHtml = '';
      let actionHtml = '';
      
      if (!provider.is_configured) {
        statusHtml = '<span class="badge badge-neutral" style="font-size: 0.65rem; padding: 0.15rem 0.45rem;">Not Configured</span>';
        actionHtml = '<span style="font-size: 0.72rem; color: var(--text-muted);">Set in .env</span>';
      } else if (provider.connected) {
        statusHtml = '<span class="badge badge-success" style="font-size: 0.65rem; padding: 0.15rem 0.45rem;"><span class="badge-dot"></span>Connected</span>';
        actionHtml = `<button class="btn btn-secondary btn-sm" style="font-size: 0.7rem; padding: 0.2rem 0.5rem;" onclick="window.App.controllers.settings.disconnectProvider('${escapeHtml(provider.id)}')">Disconnect</button>`;
      } else {
        statusHtml = '<span class="badge badge-warning" style="font-size: 0.65rem; padding: 0.15rem 0.45rem;">Disconnected</span>';
        actionHtml = `<a class="btn btn-primary btn-sm" style="font-size: 0.7rem; padding: 0.2rem 0.5rem;" href="${escapeHtml(provider.auth_url)}">Connect</a>`;
      }
      
      card.innerHTML = `
        <div style="display: flex; align-items: center; gap: 0.5rem;">
          <strong style="font-size: 0.785rem; color: var(--text-main);">${escapeHtml(provider.name)}</strong>
          ${statusHtml}
        </div>
        <div>
          ${actionHtml}
        </div>
      `;
      
      container.appendChild(card);
    });
  }

  async disconnectProvider(providerId) {
    if (!confirm('Are you sure you want to revoke local authorization for this provider? Notifications via this provider will fail until reconnected.')) {
      return;
    }
    
    try {
      await API.notifications.disconnectProvider(providerId);
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Provider disconnected locally', type: 'success' }}));
      await this.loadData();
    } catch (err) {
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: `Failed to disconnect: ${err.message}`, type: 'error' }}));
    }
  }
  
  renderSession(session, settings) {
    this.session = session;
    const filename = settings ? `${(settings.portal_adapter || 'pwioi').toLowerCase()}_session.json` : 'pwioi_session.json';
    if (this.els.storageStateFilename) {
      this.els.storageStateFilename.innerText = filename;
    }

    if (session.is_authenticated) {
      this.els.sessionStatusBadge.className = 'badge badge-success';
      this.els.sessionStatusBadge.innerText = 'AUTHENTICATED';
      const userTag = session.student_name ? ` (User: ${session.student_name})` : '';
      this.els.sessionStatusText.innerText = `Storage state file found (${filename}). Session is valid${userTag}.`;
      if (this.els.sessionHandshake) this.els.sessionHandshake.innerText = session.student_email || 'Storage State Active';
      this.els.btnClearSession.disabled = false;
    } else {
      this.els.sessionStatusBadge.className = 'badge badge-warning';
      this.els.sessionStatusBadge.innerText = 'UNAUTHENTICATED';
      this.els.sessionStatusText.innerText = `No session file found (${filename}). Authentication required via CLI/Browser.`;
      if (this.els.sessionHandshake) this.els.sessionHandshake.innerText = 'Session Required';
      this.els.btnClearSession.disabled = true;
    }
  }

  async clearSession() {
    if (!confirm('Are you sure you want to clear the active portal session? Future attendance extractions will fail until you sign in again.')) {
      return;
    }
    
    try {
      this.els.btnClearSession.disabled = true;
      this.els.btnClearSession.innerText = 'Clearing...';
      
      await API.settings.clearSession();
      
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: 'Session securely cleared', type: 'success' }}));
      await this.loadData();
    } catch (err) {
      window.dispatchEvent(new CustomEvent('app-alert', { detail: { message: `Failed to clear session: ${err.message}`, type: 'error' }}));
    } finally {
      this.els.btnClearSession.innerText = 'Clear Session';
    }
  }
}

// Utility to prevent XSS
function escapeHtml(unsafe) {
  if (!unsafe) return '';
  return unsafe
    .toString()
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
