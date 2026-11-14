import copy

from birdweather_openapi.builder import build_spec
from birdweather_openapi.diff import diff_specs, operations, render_markdown


def test_identical_specs_have_no_diff(mini_spec):
    assert diff_specs(mini_spec, copy.deepcopy(mini_spec)).is_empty


def test_initial_spec_marks_everything_as_added(mini_spec):
    diff = diff_specs(None, mini_spec)
    assert len(diff.added) == len(operations(mini_spec)) == 5
    assert "GET /stations/{token}/birds" in diff.added


def test_added_and_removed_endpoints(mini_spec):
    new = copy.deepcopy(mini_spec)
    del new["paths"]["/birds/{id}"]
    new["paths"]["/new"] = {"get": {"responses": {"200": {"description": "OK"}}}}
    diff = diff_specs(mini_spec, new)
    assert diff.added == ["GET /new"]
    assert diff.removed == ["GET /birds/{id}"]


def test_parameter_and_response_field_changes(mini_spec):
    new = copy.deepcopy(mini_spec)
    operation = new["paths"]["/stations/{token}/birds"]["get"]
    operation["parameters"].append(
        {"name": "region", "in": "query", "required": False, "schema": {"type": "string"}}
    )
    operation["parameters"][1]["schema"]["type"] = "string"
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    schema["properties"]["total"] = {"type": "integer"}
    del schema["properties"]["fallback"]

    changes = diff_specs(mini_spec, new).changed["GET /stations/{token}/birds"]
    assert "parameter added: `region` (query, optional)" in changes
    assert "parameter `limit` (query): type `integer` → `string`" in changes
    assert "response `200` field added: `total` (optional)" in changes
    assert "response `200` field removed: `fallback`" in changes


def test_body_field_changes(mini_spec):
    new = copy.deepcopy(mini_spec)
    schema = new["paths"]["/stations/{token}/birds"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    schema["properties"]["colour"] = {"type": "string"}
    schema["required"].append("colour")
    changes = diff_specs(mini_spec, new).changed["POST /stations/{token}/birds"]
    assert "body field added: `colour` (required)" in changes


def test_description_only_change_is_reported(mini_spec):
    new = copy.deepcopy(mini_spec)
    new["paths"]["/birds/{id}"]["get"]["description"] = "Now documented."
    assert diff_specs(mini_spec, new).changed["GET /birds/{id}"] == ["description changed"]


def test_non_path_changes_are_listed_as_other(mini_spec):
    new = copy.deepcopy(mini_spec)
    new["servers"][0]["url"] = "https://example.test/api/v3"
    assert diff_specs(mini_spec, new).other == ["servers"]


def test_render_markdown(mini_spec):
    new = copy.deepcopy(mini_spec)
    del new["paths"]["/birds/{id}"]
    text = render_markdown(diff_specs(mini_spec, new))
    assert "### Removed endpoints" in text and "- `GET /birds/{id}`" in text


def test_changed_documentation_is_detected_end_to_end(mini_doc):
    before = build_spec(mini_doc)
    mini_doc.actions[0].params[1].description = "Different text."
    assert diff_specs(before, build_spec(mini_doc)).changed
