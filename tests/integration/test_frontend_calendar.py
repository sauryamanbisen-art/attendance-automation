"""Integration tests for the frontend calendar shell."""

from fastapi.testclient import TestClient

def test_calendar_html_served(client: TestClient) -> None:
    """Verify the calendar frontend shell is present."""
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.text
    
    # Check for Calendar page container
    assert 'id="page-calendar"' in html
    
    # Check for core calendar elements
    assert 'id="btn-show-add-holiday-modal"' in html
    assert 'id="btn-show-add-exception-modal"' in html
    assert 'id="calendar-holidays-container"' in html
    assert 'id="calendar-exceptions-container"' in html
    
    # Check for calendar modals
    assert 'id="modal-holiday"' in html
    assert 'id="modal-holiday-title"' in html
    assert 'id="form-holiday"' in html
    assert 'id="input-holiday-date"' in html
    
    assert 'id="modal-exception"' in html
    assert 'id="modal-exception-title"' in html
    assert 'id="form-exception"' in html
    assert 'id="input-exception-type"' in html
    assert 'id="input-exception-subject"' in html
    assert 'id="input-exception-date"' in html
    assert 'id="exception-time-container"' in html

def test_static_calendar_js_served(client: TestClient) -> None:
    """Verify static JS calendar files are properly mounted and served."""
    res_js = client.get("/static/js/pages/calendar.js")
    assert res_js.status_code == 200
    assert "export class CalendarController" in res_js.text
    
    # Validate API usage exists
    assert "API.calendar.createHoliday" in res_js.text
    assert "API.calendar.deleteHoliday" in res_js.text
    assert "API.calendar.createException" in res_js.text
    assert "API.calendar.deleteException" in res_js.text
    assert "parseLocalDate" in res_js.text
