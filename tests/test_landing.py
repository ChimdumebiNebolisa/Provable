from __future__ import annotations


def test_landing_page_shows_mode_selection(client):
    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Provable" in body
    assert "Enter Demo" in body
    assert "/auth/login" in body
