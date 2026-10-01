"""Integration tests for the frontend subjects shell."""

from fastapi.testclient import TestClient

def test_subjects_html_served(client: TestClient) -> None:
    """Verify the subjects frontend shell is present."""
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.text
    
    # Check for Subjects page container
    assert 'id="page-subjects"' in html
    
    # Check for core subjects elements
    assert 'id="btn-show-add-subject-modal"' in html
    assert 'id="subjects-container"' in html
    
    # Check for subject modal
    assert 'id="modal-subject"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'id="form-subject"' in html
    assert 'id="input-subject-code"' in html
    assert 'id="input-subject-name"' in html
    assert 'id="input-prof-name"' in html
    assert 'id="input-prof-email"' in html
    assert 'id="input-chat-space"' in html
    assert 'id="input-prof-active"' in html

def test_static_subjects_js_served(client: TestClient) -> None:
    """Verify static JS subjects files are properly mounted and served."""
    res_js = client.get("/static/js/pages/subjects.js")
    assert res_js.status_code == 200
    assert "export class SubjectsController" in res_js.text
    
    # Validate API usage exists
    assert "API.subjects.list" in res_js.text
    assert "API.subjects.create" in res_js.text
    assert "API.subjects.update" in res_js.text
    assert "API.subjects.delete" in res_js.text
