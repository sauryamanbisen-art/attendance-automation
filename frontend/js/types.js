/**
 * @fileoverview Frontend Type Definitions matching Backend FastAPI Schemas
 * Used for IDE intellisense and JSDoc type checking.
 */

/**
 * @typedef {Object} SubjectResponse
 * @property {number} id
 * @property {string} code
 * @property {string} name
 * @property {string|null} professor_name
 * @property {string|null} professor_email
 * @property {string|null} google_chat_space
 * @property {boolean|null} [is_active]
 */

/**
 * @typedef {Object} SubjectResultItem
 * @property {string} subject_code
 * @property {string} status - PRESENT, ABSENT, UNKNOWN, NOT_MARKED
 * @property {string|null} raw_status
 * @property {boolean} is_reliable
 */

/**
 * @typedef {Object} DashboardResponse
 * @property {string} today - ISO Date string (YYYY-MM-DD)
 * @property {boolean} is_holiday
 * @property {boolean} is_confirmed
 * @property {SubjectResponse[]} expected_classes
 * @property {SubjectResultItem[]} attendance_records
 */

/**
 * @typedef {Object} TimetableSlotResponse
 * @property {number} id
 * @property {number} subject_id
 * @property {number} weekday
 * @property {string} start_time
 * @property {string} end_time
 * @property {string|null} period_name
 * @property {string|null} valid_from
 * @property {string|null} valid_to
 */

/**
 * @typedef {Object} HolidayResponse
 * @property {number} id
 * @property {string} date
 * @property {string} description
 */

/**
 * @typedef {Object} ClassExceptionResponse
 * @property {number} id
 * @property {number} subject_id
 * @property {string} date
 * @property {string} exception_type - CANCELLED | EXTRA
 * @property {string|null} start_time
 * @property {string|null} end_time
 * @property {string|null} description
 */

// Export an empty object to make this an ES Module
export {};
