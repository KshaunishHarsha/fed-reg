"""Tests for boilerplate_pruner.py — HTTP calls are mocked."""
from unittest.mock import MagicMock, patch

import pytest

from boilerplate_pruner import prune, get_body_html_url


def _mock_fr_api(body_html_url: str = "https://example.com/body.html"):
    """Mock the FR API response that returns body_html_url."""
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"body_html_url": body_html_url}
    return mock


def _mock_html_response(html: str):
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.text = html
    return mock


def _make_get(fr_response, html_response):
    def side_effect(url, **kwargs):
        if "federalregister.gov" in url:
            return fr_response
        return html_response
    return side_effect


# ---------------------------------------------------------------------------
# get_body_html_url
# ---------------------------------------------------------------------------

def test_get_body_html_url_returns_url_on_success():
    mock_resp = _mock_fr_api("https://example.com/body.html")
    with patch("boilerplate_pruner.requests.get", return_value=mock_resp):
        url = get_body_html_url("2025-00001")
    assert url == "https://example.com/body.html"


def test_get_body_html_url_returns_none_on_404():
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch("boilerplate_pruner.requests.get", return_value=mock_resp):
        url = get_body_html_url("2025-00001")
    assert url is None


# ---------------------------------------------------------------------------
# URL stripping
# ---------------------------------------------------------------------------

def test_urls_stripped_from_output():
    html = "<p>See https://www.regulations.gov/comment for details on this rule.</p>"
    with patch("boilerplate_pruner.requests.get", side_effect=_make_get(
        _mock_fr_api(), _mock_html_response(html)
    )):
        result = prune("2025-00001")
    assert "http" not in result
    assert "See" in result


# ---------------------------------------------------------------------------
# Noise section removal
# ---------------------------------------------------------------------------

def test_background_section_stripped():
    html = """
    <h2>Background</h2>
    <p>Historical context that should be removed.</p>
    <h2>Summary</h2>
    <p>This rule amends animal welfare enforcement procedures.</p>
    """
    with patch("boilerplate_pruner.requests.get", side_effect=_make_get(
        _mock_fr_api(), _mock_html_response(html)
    )):
        result = prune("2025-00001")
    assert "Historical context" not in result
    assert "animal welfare enforcement" in result


def test_list_of_subjects_stripped():
    html = """
    <h3>List of Subjects</h3>
    <p>Administrative practice and procedure, Animals.</p>
    <h3>Action</h3>
    <p>This proposed rule would update AWA inspection standards.</p>
    """
    with patch("boilerplate_pruner.requests.get", side_effect=_make_get(
        _mock_fr_api(), _mock_html_response(html)
    )):
        result = prune("2025-00001")
    assert "Administrative practice" not in result
    assert "AWA inspection standards" in result


def test_signature_block_stripped():
    html = """
    <h2>Summary</h2>
    <p>This rule updates standards for livestock facilities.</p>
    <h2>Signature</h2>
    <p>Tom Vilsack, Secretary of Agriculture. Date signed: January 15, 2025.</p>
    """
    with patch("boilerplate_pruner.requests.get", side_effect=_make_get(
        _mock_fr_api(), _mock_html_response(html)
    )):
        result = prune("2025-00001")
    assert "Tom Vilsack" not in result
    assert "livestock facilities" in result


# ---------------------------------------------------------------------------
# Empty / failure cases
# ---------------------------------------------------------------------------

def test_returns_empty_string_when_no_body_html_url():
    mock_fr = MagicMock()
    mock_fr.status_code = 404
    with patch("boilerplate_pruner.requests.get", return_value=mock_fr):
        result = prune("2025-00001")
    assert result == ""


def test_returns_empty_string_when_html_fetch_fails():
    mock_html = MagicMock()
    mock_html.raise_for_status.side_effect = Exception("Connection error")
    with patch("boilerplate_pruner.requests.get", side_effect=_make_get(
        _mock_fr_api(), mock_html
    )):
        result = prune("2025-00001")
    assert result == ""


def test_empty_paragraphs_excluded():
    html = "<p></p><p>   </p><p>Real content here.</p>"
    with patch("boilerplate_pruner.requests.get", side_effect=_make_get(
        _mock_fr_api(), _mock_html_response(html)
    )):
        result = prune("2025-00001")
    assert result.strip() == "Real content here."