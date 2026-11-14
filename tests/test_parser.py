import pytest

from birdweather_openapi.parser import parse_documentation


def action(doc, action_id):
    return next(item for item in doc.actions if item.id == action_id)


def test_intro_metadata(mini_doc):
    assert mini_doc.title == "Mini"
    assert mini_doc.api_version == "2"
    assert mini_doc.servers == [("Production", "https://example.test/api/v2")]
    assert mini_doc.contact_email == "help@example.test"
    assert "V2 of the Mini API" in mini_doc.description


def test_actions_are_parsed_in_document_order(mini_doc):
    assert [(a.method, a.path) for a in mini_doc.actions] == [
        ("get", "/api/v2/stations/{token}/birds"),
        ("post", "/api/v2/stations/{token}/birds"),
        ("get", "/api/v2/stations/{token}/birds/{id}"),
        ("get", "/api/v2/birds/{id}"),
        ("post", "/api/v2/stations/{token}/audio"),
    ]
    assert {a.group for a in mini_doc.actions} == {"Birds", "Audio"}
    assert action(mini_doc, "birds-global-get").resource == "Global Bird"


def test_query_names_come_from_the_uri_template(mini_doc):
    assert action(mini_doc, "birds-birds-get").query_names == ["limit", "mode", "extra"]


def test_uri_parameters(mini_doc):
    params = {p.name: p for p in action(mini_doc, "birds-birds-get").params}
    assert params["token"].required and params["token"].type == "string"
    assert not params["limit"].required
    assert (params["limit"].type, params["limit"].example) == ("integer", "10")
    assert "default: 10" in params["limit"].description


def test_body_field_bullets_are_not_part_of_the_description(mini_doc):
    post = action(mini_doc, "birds-birds-post")
    assert post.description == "Adds a bird."
    assert [(f.name, f.type, f.required) for f in post.fields] == [
        ("name", "string", True),
        ("weight", "float", False),
        ("tags", "array", False),
    ]


def test_samples_keep_status_and_content_type(mini_doc):
    get = action(mini_doc, "birds-birds-get")
    assert [r.status for r in get.responses] == ["200", "200"]
    post = action(mini_doc, "birds-birds-post")
    assert post.requests[0].status is None
    assert [r.status for r in post.responses] == ["201", "422"]
    assert post.responses[1].content_type == "application/json"


def test_inline_markup_becomes_markdown(mini_doc):
    assert action(mini_doc, "birds-birds-get").description == "Lists birds with `limit`."


@pytest.mark.parametrize("html", ["<html><body><p>Maintenance</p></body></html>", ""])
def test_unrecognised_page_is_an_error(html):
    with pytest.raises(ValueError, match="No resource groups"):
        parse_documentation(html)


def test_real_page_snapshot(snapshot_html):
    doc = parse_documentation(snapshot_html)
    assert doc.api_version == "1"
    assert doc.servers == [("Production", "https://app.birdweather.com/api/v1")]
    assert len(doc.actions) == 12
    assert ("post", "/api/v1/stations/{token}/detections") in [(a.method, a.path) for a in doc.actions]
