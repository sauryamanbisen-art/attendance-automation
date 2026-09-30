/**
 * @fileoverview Centralized API Client Layer
 */

/**
 * Custom Error for API failures
 */
export class ApiError extends Error {
  /**
   * @param {string} message 
   * @param {number} status 
   * @param {any} data 
   */
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
    this.name = 'ApiError';
  }
}

/**
 * Base fetch wrapper with standardized error handling
 * @param {string} endpoint 
 * @param {RequestInit} [options={}]
 * @returns {Promise<any>}
 */
async function apiClient(endpoint, options = {}) {
  const defaultHeaders = {
    'Content-Type': 'application/json',
  };

  const config = {
    ...options,
    headers: {
      ...defaultHeaders,
      ...options.headers,
    },
  };

  try {
    const response = await fetch(`/api${endpoint}`, config);
    if (!response.ok) {
      let errData;
      try {
        errData = await response.json();
      } catch (e) {
        errData = { detail: response.statusText };
      }
      throw new ApiError(errData.detail || 'API request failed', response.status, errData);
    }
    
    // For 204 No Content
    if (response.status === 204) {
      return null;
    }
    
    return await response.json();
  } catch (error) {
    console.error(`API Error on ${endpoint}:`, error);
    throw error;
  }
}

export const API = {
  dashboard: {
    /**
     * @returns {Promise<import('./types.js').DashboardResponse>}
     */
    async getToday() {
      return apiClient('/dashboard/today');
    },
  },
  confirmations: {
    /**
     * @param {string} date 
     * @param {string} [note]
     */
    async confirm(date, note) {
      return apiClient('/confirmations', {
        method: 'POST',
        body: JSON.stringify({ date, note }),
      });
    },
  },
  timetable: {
    /**
     * @returns {Promise<import('./types.js').TimetableSlotResponse[]>}
     */
    async listSlots() {
      return apiClient('/timetable/');
    },
    /**
     * @param {Object} data 
     * @returns {Promise<import('./types.js').TimetableSlotResponse>}
     */
    async createSlot(data) {
      return apiClient('/timetable/', {
        method: 'POST',
        body: JSON.stringify(data),
      });
    },
    /**
     * @param {number} slotId 
     * @param {Object} data 
     * @returns {Promise<import('./types.js').TimetableSlotResponse>}
     */
    async updateSlot(slotId, data) {
      return apiClient(`/timetable/${slotId}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      });
    },
    /**
     * @param {number} slotId 
     */
    async deleteSlot(slotId) {
      return apiClient(`/timetable/${slotId}`, { method: 'DELETE' });
    }
  },
  subjects: {
    /**
     * @returns {Promise<import('./types.js').SubjectResponse[]>}
     */
    async list() {
      return apiClient('/subjects');
    },
    /**
     * @param {Object} data 
     * @returns {Promise<import('./types.js').SubjectResponse>}
     */
    async create(data) {
      return apiClient('/subjects', {
        method: 'POST',
        body: JSON.stringify(data),
      });
    },
    /**
     * @param {string} code 
     * @param {Object} data 
     * @returns {Promise<import('./types.js').SubjectResponse>}
     */
    async update(code, data) {
      return apiClient(`/subjects/${code}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      });
    },
    /**
     * @param {string} code 
     */
    async delete(code) {
      return apiClient(`/subjects/${code}`, { method: 'DELETE' });
    }
  },
  calendar: {
    /**
     * @returns {Promise<import('./types.js').HolidayResponse[]>}
     */
    async listHolidays() {
      return apiClient('/calendar/holidays');
    },
    /**
     * @param {Object} data 
     * @returns {Promise<import('./types.js').HolidayResponse>}
     */
    async createHoliday(data) {
      return apiClient('/calendar/holidays', {
        method: 'POST',
        body: JSON.stringify(data),
      });
    },
    /**
     * @param {number} holidayId 
     */
    async deleteHoliday(holidayId) {
      return apiClient(`/calendar/holidays/${holidayId}`, { method: 'DELETE' });
    },
    /**
     * @returns {Promise<import('./types.js').ClassExceptionResponse[]>}
     */
    async listExceptions() {
      return apiClient('/calendar/exceptions');
    },
    /**
     * @param {Object} data 
     * @returns {Promise<import('./types.js').ClassExceptionResponse>}
     */
    async createException(data) {
      return apiClient('/calendar/exceptions', {
        method: 'POST',
        body: JSON.stringify(data),
      });
    },
    /**
     * @param {number} exceptionId 
     */
    async deleteException(exceptionId) {
      return apiClient(`/calendar/exceptions/${exceptionId}`, { method: 'DELETE' });
    }
  },
  history: {
    /**
     * @param {Object} [params] 
     * @param {string} [params.start_date]
     * @param {string} [params.end_date]
     * @param {string} [params.subject_code]
     * @param {number} [params.limit=50]
     * @param {number} [params.offset=0]
     */
    async list(params = {}) {
      const query = new URLSearchParams();
      if (params.start_date) query.append('start_date', params.start_date);
      if (params.end_date) query.append('end_date', params.end_date);
      if (params.subject_code) query.append('subject_code', params.subject_code);
      if (params.limit) query.append('limit', params.limit);
      if (params.offset !== undefined) query.append('offset', params.offset);
      
      const qs = query.toString();
      return apiClient(`/history${qs ? '?' + qs : ''}`);
    }
  },
  settings: {
    async read() {
      return apiClient('/settings');
    },
    async getSessionStatus() {
      return apiClient('/settings/session');
    },
    async clearSession() {
      return apiClient('/settings/session', { method: 'DELETE' });
    }
  },
  notifications: {
    async getProviders() {
      return apiClient('/notifications/providers');
    },
    async disconnectProvider(providerId) {
      return apiClient(`/notifications/${providerId}/authorization`, { method: 'DELETE' });
    }
  }
};
