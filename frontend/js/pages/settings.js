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
      fPortalAdapter: document.getElementById('setting-portal-adapter'),
      fPortalHeadless: document.getElementById('setting-portal-headless'),
      fBrowserChannel: document.getElementById('setting-browser-channel'),
      fEmailProvider: document.getElementById('setting-email-provider'),
      fNotificationSender: document.getElementById('setting-notification-sender'),
      
      // Session
      sessionStatusBadge: document.getElementById('session-status-badge'),
      sessionStatusText: document.getElementById('session-status-text'),
      btnClearSession: document.getElementById('btn-clear-session'),
    };

    this.bindEvents();
  }

  bindEvents() {
    if (this.els.btnRetry) {
      this.els.btnRetry.addEventListener('click', () => this.loadData());
    }
    
    if (this.els.btnClearSession) {
      this.els.btnClearSession.addEventListener('click', () => this.clearSession());
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
      
      this.renderSettings(settings);
      this.renderSession(session);
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
    this.els.fAppName.innerText = settings.app_name;
    this.els.fAppEnv.innerText = settings.app_env;
    this.els.fLogLevel.innerText = settings.log_level;
    this.els.fTimezone.innerText = settings.timezone;
    this.els.fDryRun.innerHTML = settings.dry_run 
      ? '<span class="badge badge-warning">Enabled (Safe Mode)</span>'
      : '<span class="badge badge-danger">Disabled (Active Mode)</span>';
      
    this.els.fPortalAdapter.innerText = settings.portal_adapter.toUpperCase();
    this.els.fPortalHeadless.innerText = settings.portal_headless ? 'Headless' : 'Headed UI';
    this.els.fBrowserChannel.innerText = settings.portal_browser_channel || 'Bundled Chromium';
    this.els.fEmailProvider.innerText = settings.email_provider;
    this.els.fNotificationSender.innerText = settings.notification_sender_email;
  }
  
  renderProviders(data) {
    const container = document.getElementById('notification-providers-list');
    if (!container) return;
    
    container.innerHTML = '';
    
    data.providers.forEach(provider => {
      const card = document.createElement('div');
      card.style.cssText = 'background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-subtle); padding: 1rem; border-radius: var(--radius-sm); margin-bottom: 1rem;';
      
      let statusHtml = '';
      let actionHtml = '';
      
      if (!provider.is_configured) {
        statusHtml = '<span class="badge badge-neutral">Not Configured</span>';
        actionHtml = '<p style="font-size: 0.8rem; color: var(--text-muted); margin: 0;">Missing Client ID/Secret in .env</p>';
      } else if (provider.connected) {
        statusHtml = '<span class="badge badge-success">Connected</span>';
        actionHtml = `<button class="btn btn-danger btn-sm" onclick="window.App.controllers.settings.disconnectProvider('${provider.id}')">Disconnect</button>`;
      } else {
        statusHtml = '<span class="badge badge-warning">Disconnected</span>';
        actionHtml = `<a class="btn btn-primary btn-sm" href="${provider.auth_url}">Connect</a>`;
      }

      let accountHtml = '';
      if (provider.connected && provider.account_identifier) {
        accountHtml = `<div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.25rem;">Account: <span style="color: var(--text-main); font-weight: 500;">${provider.account_identifier}</span></div>`;
      }
      
      card.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
          <div>
            <strong>${provider.name}</strong>
            ${accountHtml}
          </div>
          ${statusHtml}
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <p style="font-size: 0.85rem; color: var(--text-subtle); margin: 0;">OAuth Authorization</p>
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
  
  renderSession(session) {
    if (session.is_authenticated) {
      this.els.sessionStatusBadge.className = 'badge badge-success';
      this.els.sessionStatusBadge.innerText = 'AUTHENTICATED';
      this.els.sessionStatusText.innerText = 'Storage state file found. Session is valid.';
      this.els.btnClearSession.disabled = false;
    } else {
      this.els.sessionStatusBadge.className = 'badge badge-warning';
      this.els.sessionStatusBadge.innerText = 'UNAUTHENTICATED';
      this.els.sessionStatusText.innerText = 'No session file found. Authentication required via CLI/Browser.';
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
