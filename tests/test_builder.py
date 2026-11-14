import json

import pytest

from birdweather_openapi.builder import build_spec
from birdweather_openapi.parser import parse_documentation


def parameters(spec, path, method):
    return {p["name"]: p for p in spec["paths"][path][method].get("parameters", [])}


def test_top_level_structure(mini_spec):
    assert mini_spec["openapi"] == "3.0.3"
    assert mini_spec["info"]["title"] == "Mini REST API"
    assert mini_spec["info"]["version"] == "2.20260101"
    assert mini_spec["info"]["contact"]["email"] == "help@example.test"
    assert mini_spec["servers"] == [{"url": "https://example.test/api/v2", "description": "Production"}]
    assert [tag["name"] for tag in mini_spec["tags"]] == ["Birds", "Audio"]


def test_paths_are_relative_to_the_server(mini_spec):
    assert set(mini_spec["paths"]) == {
        "/stations/{token}/birds",
        "/stations/{token}/birds/{id}",
        "/birds/{id}",
        "/stations/{token}/audio",
    }


def test_parameters_locations_and_schemas(mini_spec):
    params = parameters(mini_spec, "/stations/{token}/birds", "get")
    assert list(params) == ["token", "limit", "mode", "extra"]
    assert (params["token"]["in"], params["token"]["required"]) == ("path", True)
    assert params["limit"]["in"] == "query" and not params["limit"]["required"]
    assert params["limit"]["schema"] == {"type": "integer", "default": 10, "maximum": 50}
    assert params["limit"]["example"] == 10
    assert params["mode"]["schema"]["enum"] == ["live", "recorded"]
    # Present in the URI template but not documented: still exposed.
    assert params["extra"]["schema"] == {"type": "string"}


def test_enum_is_skipped_for_comma_separated_lists():
    html = (
        '<section class="resource-group"><h2 class="group-heading">G</h2><div class="resource">'
        '<h3 class="resource-heading">R</h3><div id="a" class="action get"><h4 class="action-heading">'
        '<div class="name">N</div><a class="method get">GET</a><code class="uri">/x{?c}</code></h4>'
        '<div class="title"><strong>URI Parameters</strong></div><div class="collapse-content">'
        '<dl class="inner"><dt>c</dt><dd><code>string</code> <span>(optional)</span>'
        "<p>One or a comma-separated list [a / b / c].</p></dd></dl></div></div></div></section>"
    )
    spec = build_spec(parse_documentation(html))
    assert "enum" not in spec["paths"]["/x"]["get"]["parameters"][0]["schema"]


def test_request_body_from_bullets_and_example(mini_spec):
    body = mini_spec["paths"]["/stations/{token}/birds"]["post"]["requestBody"]
    assert body["required"] is True
    assert set(body["content"]) == {"application/json", "application/x-www-form-urlencoded"}
    media = body["content"]["application/json"]
    schema = media["schema"]
    assert schema["required"] == ["name"]
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["weight"]["type"] == "number"
    weight = schema["properties"]["weight"]
    assert (weight["minimum"], weight["maximum"]) == (0.1, 9.5)
    assert schema["properties"]["tags"] == {
        "type": "array",
        "items": {"type": "string"},
        "description": "Free-form tags.",
    }
    assert media["example"]["weight"] == 0.45


def test_binary_upload_body(mini_spec):
    body = mini_spec["paths"]["/stations/{token}/audio"]["post"]["requestBody"]
    assert body["content"] == {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}


def test_get_has_no_request_body(mini_spec):
    assert "requestBody" not in mini_spec["paths"]["/stations/{token}/birds"]["get"]


def test_response_schema_merges_examples_with_the_same_status(mini_spec):
    response = mini_spec["paths"]["/stations/{token}/birds"]["get"]["responses"]["200"]
    media = response["content"]["application/json"]
    assert response["description"] == "OK"
    assert set(media["schema"]["properties"]) == {"success", "birds", "fallback"}
    item = media["schema"]["properties"]["birds"]["items"]["properties"]
    assert item["seenAt"] == {"type": "string", "format": "date-time"}
    assert item["note"] == {"nullable": True}
    assert set(media["examples"]) == {"example1", "example2"}


def test_error_responses(mini_spec):
    responses = mini_spec["paths"]["/stations/{token}/birds"]["post"]["responses"]
    assert list(responses) == ["201", "422"]
    assert responses["422"]["description"] == "Unprocessable Entity"
    error_media = responses["422"]["content"]["application/json"]
    assert error_media["schema"]["properties"]["errors"]["type"] == "object"


def test_operation_without_documented_responses_still_has_one(mini_spec):
    responses = mini_spec["paths"]["/stations/{token}/audio"]["post"]["responses"]
    assert list(responses) == ["default"]


def test_operation_ids_are_unique_and_disambiguated(mini_spec):
    ids = [op["operationId"] for item in mini_spec["paths"].values() for op in item.values()]
    assert len(ids) == len(set(ids))
    assert mini_spec["paths"]["/stations/{token}/birds"]["get"]["operationId"] == "listBirds"
    assert mini_spec["paths"]["/stations/{token}/birds/{id}"]["get"]["operationId"] == "birdInfo"
    assert mini_spec["paths"]["/birds/{id}"]["get"]["operationId"] == "globalBirdInfo"


def test_station_endpoints_also_accept_admin_tokens(mini_spec):
    station = mini_spec["paths"]["/stations/{token}/birds"]["get"]
    assert station["security"] == [{}, {"adminBearer": []}, {"adminToken": []}]
    assert "security" not in mini_spec["paths"]["/birds/{id}"]["get"]
    assert set(mini_spec["components"]["securitySchemes"]) == {"adminBearer", "adminToken"}


def test_build_is_deterministic(mini_doc):
    assert json.dumps(build_spec(mini_doc)) == json.dumps(build_spec(mini_doc))


def test_real_snapshot_builds_a_valid_openapi_document(snapshot_html):
    validator = pytest.importorskip("openapi_spec_validator")
    spec = build_spec(parse_documentation(snapshot_html), version="1.20260101")
    assert len([m for item in spec["paths"].values() for m in item]) == 12
    validator.validate(spec)


def test_real_snapshot_details(snapshot_html):
    spec = build_spec(parse_documentation(snapshot_html))
    species = spec["paths"]["/stations/{token}/species"]["get"]
    assert {p["name"] for p in species["parameters"]} >= {"token", "period", "sort", "order", "speciesId"}
    config = spec["paths"]["/stations/{token}/config"]["post"]["requestBody"]["content"]["application/json"]
    assert config["example"]["minConfidence"] == 0.45
    assert spec["paths"]["/stations/{token}/soundscapes"]["post"]["requestBody"]["content"].keys() == {
        "application/octet-stream"
    }
