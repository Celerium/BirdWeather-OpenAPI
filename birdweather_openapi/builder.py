"""Turn parsed documentation into an OpenAPI 3 document."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from .constants import (
    BINARY_CONTENT_TYPE,
    DEFAULT_SERVER,
    FORM_CONTENT_TYPE,
    JSON_CONTENT_TYPE,
    OPENAPI_VERSION,
    SOURCE_URL,
)
from .parser import PATH_PARAMETER_PATTERN, Action, BodyField, Documentation, Param, Sample
from .schema import infer_schema, load_example, merge_schemas

METHOD_ORDER = ("get", "post", "put", "patch", "delete")
BODY_METHODS = frozenset({"post", "put", "patch", "delete"})
TYPE_ALIASES = {"int": "integer", "float": "number", "double": "number", "bool": "boolean"}
SCHEMA_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object"})
HTTP_STATUS = {
    "200": "OK",
    "201": "Created",
    "202": "Accepted",
    "204": "No Content",
    "400": "Bad Request",
    "401": "Unauthorized",
    "403": "Forbidden",
    "404": "Not Found",
    "422": "Unprocessable Entity",
    "429": "Too Many Requests",
    "500": "Internal Server Error",
}

ENUM_PATTERN = re.compile(r"\[([\w-]+(?:\s*/\s*[\w-]+)+)\]")
DEFAULT_PATTERN = re.compile(r"default:\s*([\w.-]+)\s*[)\]]")
MAXIMUM_PATTERN = re.compile(r"\bmax\s+(\d+)\b")
RANGE_PATTERN = re.compile(r"\((-?[\d.]+)\s*(?:…|\.\.\.)\s*(-?[\d.]+)\)")
# "The audio file should be submitted as the POST body": the body is the raw file, not JSON.
BINARY_BODY_PATTERN = re.compile(r"\b(?:audio|binary|file)\b.*\bas the (?:POST|request) body\b", re.I | re.S)

# Authentication described in the page introduction: stations authenticate with the `{token}` path
# segment, administrators with an API token sent in a header.
SECURITY_SCHEMES = {
    "adminBearer": {
        "type": "http",
        "scheme": "bearer",
        "description": "Administrator API token, sent as `Authorization: Bearer <token>`.",
    },
    "adminToken": {
        "type": "apiKey",
        "in": "header",
        "name": "X-Auth-Token",
        "description": "Administrator API token, sent in the `X-Auth-Token` header.",
    },
}
# `{}` keeps the station token in the URL valid; the schemes allow an administrator token instead.
STATION_SECURITY: list[dict[str, list[str]]] = [{}, {"adminBearer": []}, {"adminToken": []}]


def camel_case(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text)
    return words[0].lower() + "".join(word[:1].upper() + word[1:] for word in words[1:]) if words else ""


def operation_ids(actions: list[Action]) -> dict[str, str]:
    """Stable operationIds: the action name, falling back to resource + name, then the anchor id."""
    candidates = [camel_case(action.name) for action in actions]
    result: dict[str, str] = {}
    for action, candidate in zip(actions, candidates, strict=True):
        if candidates.count(candidate) > 1:
            candidate = camel_case(f"{action.resource} {action.name}")
        result[action.id] = candidate
    names = list(result.values())
    return {
        action_id: name if names.count(name) == 1 else camel_case(action_id)
        for action_id, name in result.items()
    }


def coerce(value: str, schema_type: str) -> Any:
    try:
        if schema_type == "integer":
            return int(value)
        if schema_type == "number":
            return float(value)
    except ValueError:
        return value
    if schema_type == "boolean" and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return value


def schema_type(name: str) -> str:
    base = re.match(r"[a-z]+", name.lower())
    kind = TYPE_ALIASES.get(base.group(0), base.group(0)) if base else "string"
    return kind if kind in SCHEMA_TYPES else "string"


def constrained_schema(kind: str, description: str) -> dict[str, Any]:
    """Build a schema for a documented type, mining the description for enums, defaults and limits."""
    schema: dict[str, Any] = {"type": kind}
    if kind == "array":
        schema["items"] = {}
    enum = ENUM_PATTERN.search(description)
    if kind == "string" and enum and "comma-separated" not in description.lower():
        schema["enum"] = [value.strip() for value in enum.group(1).split("/")]
    default = DEFAULT_PATTERN.search(description)
    if default and kind in ("string", "integer", "number", "boolean"):
        value = coerce(default.group(1), kind)
        if "enum" not in schema or value in schema["enum"]:
            schema["default"] = value
    if kind in ("integer", "number"):
        limit = MAXIMUM_PATTERN.search(description)
        if limit:
            schema["maximum"] = int(limit.group(1))
        span = RANGE_PATTERN.search(description)
        if span:
            schema["minimum"], schema["maximum"] = float(span.group(1)), float(span.group(2))
    return schema


def build_parameters(action: Action) -> list[dict[str, Any]]:
    path_names = PATH_PARAMETER_PATTERN.findall(action.path)
    documented = {param.name: param for param in action.params}
    ordered: list[Param] = [documented.get(name, Param(name=name)) for name in path_names]
    ordered += [param for param in action.params if param.name not in path_names]
    ordered += [Param(name=name) for name in action.query_names if name not in {p.name for p in ordered}]

    parameters: list[dict[str, Any]] = []
    for param in ordered:
        location = "path" if param.name in path_names else "query"
        kind = schema_type(param.type)
        parameter: dict[str, Any] = {
            "name": param.name,
            "in": location,
            "required": location == "path" or param.required,
        }
        if param.description:
            parameter["description"] = param.description
        parameter["schema"] = constrained_schema(kind, param.description)
        if param.example is not None:
            parameter["example"] = coerce(param.example, kind)
        parameters.append(parameter)
    return parameters


def field_schema(body_field: BodyField, example: Any = None) -> dict[str, Any]:
    kind = schema_type(body_field.type)
    schema = constrained_schema(kind, body_field.description)
    if body_field.type.lower() in ("float", "double"):
        schema["format"] = "float"
    if body_field.description:
        schema["description"] = body_field.description
    if example is not None and kind in ("array", "object"):
        inferred = infer_schema(example)
        if inferred.get("type") == kind:
            description = {"description": body_field.description} if body_field.description else {}
            schema = {**inferred, **description}
    return schema


def body_schema(fields: list[BodyField], examples: list[Any]) -> dict[str, Any]:
    example = next((value for value in examples if isinstance(value, dict)), {})
    if not fields:
        return infer_schema(example) if example else {"type": "object"}

    properties = {item.name: field_schema(item, example.get(item.name)) for item in fields}
    for name, value in example.items():
        properties.setdefault(name, infer_schema(value))
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    required = [item.name for item in fields if item.required]
    if required:
        schema["required"] = required
    return schema


def build_request_body(action: Action) -> dict[str, Any] | None:
    if action.method not in BODY_METHODS:
        return None
    if not action.requests and not action.fields:
        if BINARY_BODY_PATTERN.search(action.description):
            return {
                "required": True,
                "content": {BINARY_CONTENT_TYPE: {"schema": {"type": "string", "format": "binary"}}},
            }
        return None

    examples = [value for sample in action.requests if (value := load_example(sample.body)) is not None]
    schema = body_schema(action.fields, examples)
    content_type = action.requests[0].content_type if action.requests else JSON_CONTENT_TYPE

    media: dict[str, Any] = {"schema": schema}
    if examples:
        media["example"] = examples[0]
    content = {content_type: media}
    if content_type == JSON_CONTENT_TYPE:
        # "POST parameters can be passed either as JSON or as HTML encoded form parameters."
        content[FORM_CONTENT_TYPE] = {"schema": schema}
    return {"required": True, "content": content}


def build_response(samples: list[Sample]) -> dict[str, Any]:
    response: dict[str, Any] = {}
    bodies = [(sample, load_example(sample.body)) for sample in samples if sample.body]
    if not bodies:
        return response

    content: dict[str, Any] = {}
    for content_type in dict.fromkeys(sample.content_type for sample, _ in bodies):
        values = [
            value for sample, value in bodies if sample.content_type == content_type and value is not None
        ]
        schema: dict[str, Any] = {}
        for value in values:
            schema = merge_schemas(schema, infer_schema(value))
        media: dict[str, Any] = {"schema": schema}
        if len(values) == 1:
            media["example"] = values[0]
        elif values:
            media["examples"] = {f"example{index}": {"value": value} for index, value in enumerate(values, 1)}
        content[content_type] = media
    response["content"] = content
    return response


def build_responses(action: Action) -> dict[str, Any]:
    grouped: dict[str, list[Sample]] = {}
    for sample in action.responses:
        grouped.setdefault(sample.status or "default", []).append(sample)
    if not grouped:
        return {"default": {"description": "Response not documented."}}

    def sort_key(code: str) -> tuple[int, str]:
        return (0, code) if code.isdigit() else (1, code)

    return {
        code: {"description": HTTP_STATUS.get(code, f"Response {code}"), **build_response(grouped[code])}
        for code in sorted(grouped, key=sort_key)
    }


def build_operation(action: Action, operation_id: str, source_url: str) -> dict[str, Any]:
    operation: dict[str, Any] = {
        "tags": [action.group],
        "summary": action.name,
        "operationId": operation_id,
    }
    if action.description:
        operation["description"] = action.description
    operation["externalDocs"] = {
        "description": "BirdWeather documentation",
        "url": f"{source_url}#{action.id}",
    }
    if "{token}" in action.path:
        operation["security"] = STATION_SECURITY
    parameters = build_parameters(action)
    if parameters:
        operation["parameters"] = parameters
    request_body = build_request_body(action)
    if request_body:
        operation["requestBody"] = request_body
    operation["responses"] = build_responses(action)
    return operation


def build_spec(
    documentation: Documentation, version: str = "", source_url: str = SOURCE_URL
) -> dict[str, Any]:
    servers = documentation.servers or [("Production", DEFAULT_SERVER)]
    base_path = urlparse(servers[0][1]).path.rstrip("/")

    info: dict[str, Any] = {
        "title": f"{documentation.title} REST API",
        "description": (
            f"Unofficial OpenAPI description generated from the [BirdWeather documentation]({source_url}). "
            "It is not published or endorsed by BirdWeather.\n\n" + documentation.description
        ).strip(),
        "version": version,
        "x-source-url": source_url,
    }
    if documentation.contact_email:
        info["contact"] = {"name": "BirdWeather support", "email": documentation.contact_email}

    ids = operation_ids(documentation.actions)
    paths: dict[str, dict[str, Any]] = {}
    for action in documentation.actions:
        path = action.path
        if base_path and path.startswith(f"{base_path}/"):
            path = path.removeprefix(base_path)
        paths.setdefault(path, {})[action.method] = build_operation(action, ids[action.id], source_url)
    for path, item in paths.items():
        paths[path] = {method: item[method] for method in METHOD_ORDER if method in item} | {
            method: operation for method, operation in item.items() if method not in METHOD_ORDER
        }

    groups = dict.fromkeys(action.group for action in documentation.actions)
    return {
        "openapi": OPENAPI_VERSION,
        "info": info,
        "externalDocs": {"description": "BirdWeather API documentation", "url": source_url},
        "servers": [{"url": url, "description": name} for name, url in servers],
        "tags": [{"name": group} for group in groups],
        "paths": paths,
        "components": {"securitySchemes": SECURITY_SCHEMES},
    }
