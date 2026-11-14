from birdweather_openapi.schema import infer_schema, load_example, merge_schemas


def test_load_example_plain_json():
    assert load_example('{"a": 1}') == {"a": 1}


def test_load_example_repairs_ellipsis_and_leading_zero():
    text = '{\n  "min": 045,\n  "items": [\n    {\n      ...\n    },\n    {\n      ...\n    }\n  ]\n}'
    assert load_example(text) == {"min": 0.45, "items": [{}, {}]}


def test_load_example_gives_up_on_garbage():
    assert load_example("not json at all") is None
    assert load_example("   ") is None


def test_infer_scalars():
    assert infer_schema(True) == {"type": "boolean"}
    assert infer_schema(3) == {"type": "integer"}
    assert infer_schema(3.5) == {"type": "number"}
    assert infer_schema("2022-11-17T16:48:10.986-08:00") == {"type": "string", "format": "date-time"}
    assert infer_schema("2023-06-18") == {"type": "string"}
    assert infer_schema(None) == {"nullable": True}


def test_infer_nested_object_and_array():
    schema = infer_schema({"a": [1, 2.5], "b": {"c": "x"}, "d": {}})
    assert schema["properties"]["a"] == {"type": "array", "items": {"type": "number"}}
    assert schema["properties"]["b"]["properties"]["c"] == {"type": "string"}
    assert schema["properties"]["d"] == {"type": "object"}


def test_merge_null_with_typed_makes_it_nullable():
    assert merge_schemas({"nullable": True}, {"type": "string"}) == {"type": "string", "nullable": True}
    assert merge_schemas({"type": "string"}, {"nullable": True}) == {"type": "string", "nullable": True}


def test_merge_objects_unions_properties():
    merged = merge_schemas(
        {"type": "object", "properties": {"a": {"type": "integer"}}},
        {"type": "object", "properties": {"b": {"type": "string"}}},
    )
    assert set(merged["properties"]) == {"a", "b"}


def test_merge_empty_array_items_with_populated_items():
    merged = merge_schemas(infer_schema([]), infer_schema([{"id": 1}]))
    assert merged["items"]["properties"]["id"] == {"type": "integer"}
