"""Integration tests for the frontend timetable shell."""

from fastapi.testclient import TestClient

def test_timetable_html_served(client: TestClient) -> None:
    """Verify the timetable frontend shell is present."""
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.text
    
    # Check for Timetable page container
    assert 'id="page-timetable"' in html
    
    # Check for core timetable elements
    assert 'id="btn-show-add-slot-modal"' in html
    assert 'id="timetable-days-container"' in html
    
    # Check for timetable modal
    assert 'id="modal-timetable-slot"' in html
    assert 'id="form-timetable-slot"' in html
    assert 'id="input-slot-subject"' in html
    assert 'id="input-slot-weekday"' in html
    assert 'id="input-slot-start"' in html
    assert 'id="input-slot-end"' in html
    
    # Check that external stylesheet is linked and no internal style tags in timetable
    assert 'href="/static/css/timetable.css"' in html
    timetable_section = html[html.find('id="page-timetable"'):html.find('id="page-calendar"')]
    assert '<style' not in timetable_section

def test_static_timetable_js_served(client: TestClient) -> None:
    """Verify static JS timetable files are properly mounted and served."""
    res_js = client.get("/static/js/pages/timetable.js")
    assert res_js.status_code == 200
    assert "export class TimetableController" in res_js.text
    
    # Validate API usage exists
    assert "API.timetable.createSlot" in res_js.text
    assert "API.timetable.updateSlot" in res_js.text
    assert "API.timetable.deleteSlot" in res_js.text

def test_static_timetable_css_served(client: TestClient) -> None:
    """Verify static timetable.css is properly mounted and served."""
    res_css = client.get("/static/css/timetable.css")
    assert res_css.status_code == 200
    assert ".timetable-grid" in res_css.text
    assert ".timetable-day-card" in res_css.text
    assert ".timetable-slot-card" in res_css.text

