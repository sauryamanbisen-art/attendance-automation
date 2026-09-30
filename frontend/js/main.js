/**
 * @fileoverview Main Application Shell & Router
 */

import { API } from './api.js';
import { DashboardController } from './pages/dashboard.js';
import { TimetableController } from './pages/timetable.js';
import { CalendarController } from './pages/calendar.js';
import { SubjectsController } from './pages/subjects.js';
import { HistoryController } from './pages/history.js';
import { SettingsController } from './pages/settings.js';

class AppRouter {
  constructor() {
    this.routes = ['dashboard', 'timetable', 'calendar', 'subjects', 'attendance', 'settings'];
    this.currentRoute = 'dashboard';
    this.controllers = {
      dashboard: new DashboardController(),
      timetable: new TimetableController(),
      calendar: new CalendarController(),
      subjects: new SubjectsController(),
      attendance: new HistoryController(),
      settings: new SettingsController()
    };
    
    this.els = {
      sidebar: document.getElementById('app-sidebar'),
      navItems: document.querySelectorAll('.nav-item'),
      pageViews: document.querySelectorAll('.page-view'),
      mobileToggle: document.getElementById('mobile-menu-btn'),
      sidebarCloseBtn: document.getElementById('sidebar-close-btn'),
      sidebarBackdrop: document.getElementById('sidebar-backdrop'),
      headerTitle: document.getElementById('header-title'),
      headerStatus: document.getElementById('header-status'),
      
      alertBanner: document.getElementById('alert-banner'),
      alertText: document.getElementById('alert-text'),
      alertIcon: document.getElementById('alert-icon'),
      alertCloseBtn: document.getElementById('alert-close-btn')
    };

    this.alertTimeout = null;
    this.init();
  }

  init() {
    // Setup Navigation
    this.els.navItems.forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const route = item.getAttribute('data-route');
        if (route) this.navigate(route);
      });
    });

    // Setup Mobile Menu Toggle, Close Button, and Backdrop
    if (this.els.mobileToggle) {
      this.els.mobileToggle.addEventListener('click', () => {
        const isOpen = this.els.sidebar.classList.toggle('open');
        if (this.els.sidebarBackdrop) {
          this.els.sidebarBackdrop.classList.toggle('open', isOpen);
        }
      });
    }

    if (this.els.sidebarCloseBtn) {
      this.els.sidebarCloseBtn.addEventListener('click', () => {
        this.els.sidebar.classList.remove('open');
        if (this.els.sidebarBackdrop) {
          this.els.sidebarBackdrop.classList.remove('open');
        }
      });
    }

    if (this.els.sidebarBackdrop) {
      this.els.sidebarBackdrop.addEventListener('click', () => {
        this.els.sidebar.classList.remove('open');
        this.els.sidebarBackdrop.classList.remove('open');
      });
    }

    // Setup Global Alerts
    window.addEventListener('app-alert', (e) => this.showAlert(e.detail.message, e.detail.type));
    window.addEventListener('system-status-changed', () => this.loadSystemStatus());
    if (this.els.alertCloseBtn) {
      this.els.alertCloseBtn.addEventListener('click', () => {
        this.els.alertBanner.style.display = 'none';
      });
    }

    // Dismiss secondary modals safely on backdrop click
    document.addEventListener('click', (e) => {
      if (e.target && e.target.classList && e.target.classList.contains('modal-overlay')) {
        // If modal-run-check, DashboardController handles its own safety check (cannot close while running)
        if (e.target.id === 'modal-run-check') return;
        e.target.style.display = 'none';
      }
    });

    // Dismiss secondary modals safely on Escape key
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        const secondaryModals = document.querySelectorAll(
          '#modal-timetable-slot, #modal-holiday, #modal-exception, #modal-subject'
        );
        secondaryModals.forEach(m => {
          if (m && m.style.display !== 'none') {
            m.style.display = 'none';
          }
        });
      }
    });

    // Handle browser back/forward and hash changes
    window.addEventListener('hashchange', () => {
      const hash = window.location.hash ? window.location.hash.replace('#', '').split('?')[0] : '';
      if (this.routes.includes(hash) && hash !== this.currentRoute) {
        this.navigate(hash);
      }
    });

    // Load header status bar (DRY_RUN, Session readiness, Health)
    this.loadSystemStatus();

    // Initial load: respect URL hash if present
    const hash = window.location.hash ? window.location.hash.replace('#', '').split('?')[0] : '';
    const initialRoute = this.routes.includes(hash) ? hash : 'dashboard';
    this.navigate(initialRoute);
  }

  async loadSystemStatus() {
    if (!this.els.headerStatus) return;
    try {
      const [health, settings, session] = await Promise.allSettled([
        API.health.get(),
        API.settings.read(),
        API.settings.getSessionStatus(),
      ]);

      const isDryRun = settings.status === 'fulfilled' ? settings.value.dry_run : true;
      const isOnline = health.status === 'fulfilled' && health.value.status === 'ok';
      const adapter = settings.status === 'fulfilled' ? settings.value.portal_adapter.toUpperCase() : 'PORTAL';
      const hasSession = session.status === 'fulfilled' && session.value.is_authenticated;

      const dryRunBadge = isDryRun 
        ? `<span class="badge badge-warning" title="Dry Run is active - no emails will be sent"><span class="badge-dot pulse"></span>DRY RUN (Safe Mode)</span>`
        : `<span class="badge badge-danger" title="Live Mode - email sending enabled"><span class="badge-dot pulse"></span>LIVE (Sending Active)</span>`;

      const healthBadge = isOnline
        ? `<span class="badge badge-success"><span class="badge-dot"></span>Online</span>`
        : `<span class="badge badge-danger"><span class="badge-dot"></span>Offline</span>`;

      const sessionBadge = hasSession
        ? `<span class="badge badge-success" title="Authenticated portal session found"><span class="badge-dot"></span>${adapter} Ready</span>`
        : `<span class="badge badge-neutral" title="No storage state found"><span class="badge-dot"></span>${adapter} Unauth</span>`;

      this.els.headerStatus.innerHTML = `${dryRunBadge}${healthBadge}${sessionBadge}`;
    } catch (e) {
      console.debug('Could not load header status:', e);
    }
  }

  navigate(route) {
    if (!this.routes.includes(route)) return;
    this.currentRoute = route;

    // Synchronize URL hash without scroll jumps
    if (window.location.hash !== `#${route}`) {
      window.history.replaceState(null, '', `#${route}`);
    }

    // Update Sidebar UI & Accessibility
    this.els.navItems.forEach(item => {
      const isMatch = item.getAttribute('data-route') === route;
      if (isMatch) {
        item.classList.add('active');
        item.setAttribute('aria-selected', 'true');
        this.els.headerTitle.innerText = item.innerText.trim().replace(/^[^a-zA-Z]+/, ''); 
      } else {
        item.classList.remove('active');
        item.setAttribute('aria-selected', 'false');
      }
    });

    // Close mobile menu and backdrop
    this.els.sidebar.classList.remove('open');
    if (this.els.sidebarBackdrop) {
      this.els.sidebarBackdrop.classList.remove('open');
    }

    // Update Page Views
    this.els.pageViews.forEach(view => {
      if (view.id === `page-${route}`) {
        view.classList.add('active');
      } else {
        view.classList.remove('active');
      }
    });

    // Trigger Controller Logic
    if (this.controllers[route] && typeof this.controllers[route].loadData === 'function') {
      this.controllers[route].loadData();
    }
  }

  showAlert(message, type = 'info') {
    if (this.alertTimeout) {
      clearTimeout(this.alertTimeout);
      this.alertTimeout = null;
    }

    this.els.alertText.innerText = message;
    
    // Reset classes
    this.els.alertBanner.className = 'alert-banner show';
    this.els.alertBanner.classList.add(type);
    this.els.alertBanner.style.display = 'flex';
    
    if (type === 'success') this.els.alertIcon.innerText = '✅';
    else if (type === 'error') this.els.alertIcon.innerText = '⚠️';
    else this.els.alertIcon.innerText = 'ℹ️';
    
    // Auto-hide after 5 seconds
    this.alertTimeout = setTimeout(() => {
      this.els.alertBanner.style.display = 'none';
      this.alertTimeout = null;
    }, 5000);
  }
}

// Bootstrap Application
document.addEventListener('DOMContentLoaded', () => {
  window.App = new AppRouter();
});
