/**
 * @fileoverview Main Application Shell & Router
 */

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
      
      alertBanner: document.getElementById('alert-banner'),
      alertText: document.getElementById('alert-text'),
      alertIcon: document.getElementById('alert-icon'),
      alertCloseBtn: document.getElementById('alert-close-btn')
    };

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
    if (this.els.alertCloseBtn) {
      this.els.alertCloseBtn.addEventListener('click', () => {
        this.els.alertBanner.style.display = 'none';
      });
    }

    // Initial load: respect URL hash if present
    const hash = window.location.hash ? window.location.hash.replace('#', '').split('?')[0] : '';
    const initialRoute = this.routes.includes(hash) ? hash : 'dashboard';
    this.navigate(initialRoute);
  }

  navigate(route) {
    if (!this.routes.includes(route)) return;
    this.currentRoute = route;

    // Update Sidebar UI
    this.els.navItems.forEach(item => {
      if (item.getAttribute('data-route') === route) {
        item.classList.add('active');
        this.els.headerTitle.innerText = item.innerText.trim().replace(/^[^a-zA-Z]+/, ''); 
      } else {
        item.classList.remove('active');
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
    this.els.alertText.innerText = message;
    
    // Reset classes
    this.els.alertBanner.className = 'alert-banner show';
    this.els.alertBanner.classList.add(type);
    this.els.alertBanner.style.display = 'flex';
    
    if (type === 'success') this.els.alertIcon.innerText = '✅';
    else if (type === 'error') this.els.alertIcon.innerText = '⚠️';
    else this.els.alertIcon.innerText = 'ℹ️';
    
    // Auto-hide after 5 seconds
    setTimeout(() => {
      this.els.alertBanner.style.display = 'none';
    }, 5000);
  }
}

// Bootstrap Application
document.addEventListener('DOMContentLoaded', () => {
  window.App = new AppRouter();
});
