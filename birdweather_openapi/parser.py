"""Parse the Aglio-rendered API Blueprint page at https://app.birdweather.com/api/v1."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

from .constants import JSON_CONTENT_TYPE

FIELD_PATTERN = re.compile(
    r"^(?P<name>[\w.\[\]-]+)\s*\((?P<type>\w+)(?:\s*,\s*(?P<flags>[^)]*))?\)\s*-\s*(?P<description>.*)$",
    re.DOTALL,
)
SERVER_PATTERN = re.compile(r"^\s*(?P<name>[\w ]+?)\s*:\s*(?P<url>https?://\S+?)\s*$")
API_VERSION_PATTERN = re.compile(r"\bV(\d+)\b")
QUERY_TEMPLATE_PATTERN = re.compile(r"\{\?([^}]*)\}")
PATH_PARAMETER_PATTERN = re.compile(r"\{(\w+)\}")
WHITESPACE = re.compile(r"[ \t\r\n\xa0]+")


@dataclass
class Param:
    name: str
    type: str = "string"
    required: bool = False
    example: str | None = None
    description: str = ""


@dataclass
class BodyField:
    name: str
    type: str = "string"
    required: bool = False
    description: str = ""


@dataclass
class Sample:
    """A documented request or response example."""

    status: str | None
    content_type: str = JSON_CONTENT_TYPE
    body: str = ""


@dataclass
class Action:
    id: str
    name: str
    method: str
    uri: str
    group: str
    resource: str
    description: str = ""
    params: list[Param] = field(default_factory=list)
    fields: list[BodyField] = field(default_factory=list)
    requests: list[Sample] = field(default_factory=list)
    responses: list[Sample] = field(default_factory=list)

    @property
    def path(self) -> str:
        return QUERY_TEMPLATE_PATTERN.sub("", self.uri)

    @property
    def query_names(self) -> list[str]:
        match = QUERY_TEMPLATE_PATTERN.search(self.uri)
        return [name.strip() for name in match.group(1).split(",") if name.strip()] if match else []


@dataclass
class Documentation:
    title: str
    description: str
    api_version: str | None = None
    servers: list[tuple[str, str]] = field(default_factory=list)
    contact_email: str | None = None
    actions: list[Action] = field(default_factory=list)


def normalize(text: str) -> str:
    return WHITESPACE.sub(" ", text).strip()


def inline_markdown(node: Tag) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif not isinstance(child, Tag):
            continue
        elif child.name == "code":
            parts.append(f"`{child.get_text()}`")
        elif child.name == "a":
            text, href = inline_markdown(child), str(child.get("href") or "")
            parts.append(text if not href or href.startswith("#") else f"[{text}]({href})")
        elif child.name in ("strong", "b"):
            parts.append(f"**{inline_markdown(child)}**")
        elif child.name in ("em", "i"):
            parts.append(f"*{inline_markdown(child)}*")
        else:
            parts.append(inline_markdown(child))
    return normalize("".join(parts))


def block_markdown(tag: Tag) -> str:
    if tag.name in ("ul", "ol"):
        return "\n".join(f"- {inline_markdown(item)}" for item in tag.find_all("li", recursive=False))
    return inline_markdown(tag)


def heading_text(tag: Tag) -> str:
    """Heading text without the trailing permalink anchor."""
    return normalize("".join(str(child) for child in tag.children if isinstance(child, NavigableString)))


def parse_field_list(tag: Tag) -> list[BodyField] | None:
    """Parse `name (type, required) - description` bullets; None if the list is something else."""
    items = tag.find_all("li", recursive=False)
    fields: list[BodyField] = []
    for item in items:
        match = FIELD_PATTERN.match(inline_markdown(item))
        if not match:
            return None
        flags = [flag.strip().lower() for flag in (match.group("flags") or "").split(",")]
        fields.append(
            BodyField(
                name=match.group("name"),
                type=match.group("type").lower(),
                required="required" in flags,
                description=match.group("description").strip(),
            )
        )
    return fields or None


def parse_params(definition_list: Tag) -> list[Param]:
    params: list[Param] = []
    for term in definition_list.find_all("dt"):
        detail = term.find_next_sibling("dd")
        if detail is None:
            continue
        type_tag = detail.find("code")
        example = detail.select_one("span.example > span")
        description = detail.find("p")
        params.append(
            Param(
                name=normalize(term.get_text()),
                type=normalize(type_tag.get_text()).lower() if type_tag else "string",
                required=detail.select_one("span.required") is not None,
                example=normalize(example.get_text()) if example else None,
                description=inline_markdown(description) if description else "",
            )
        )
    return params


def parse_sample(content: Tag, status: str | None) -> Sample:
    sample = Sample(status=status)
    for heading in content.find_all("h5"):
        pre = heading.find_next_sibling("pre")
        if pre is None:
            continue
        label = normalize(heading.get_text()).lower()
        text = pre.get_text().replace("\xa0", " ")
        if label == "headers":
            match = re.search(r"^content-type\s*:\s*([^\s;]+)", text, re.IGNORECASE | re.MULTILINE)
            if match:
                sample.content_type = match.group(1).lower()
        elif label == "body":
            sample.body = text.strip()
    return sample


def parse_action(tag: Tag, group: str, resource: str) -> Action:
    heading = tag.select_one("h4.action-heading")
    if heading is None:
        raise ValueError(f"Action {tag.get('id')} has no heading.")
    method_tag, uri_tag = heading.select_one(".method"), heading.select_one("code.uri")
    name_tag = heading.select_one(".name")
    if method_tag is None or uri_tag is None:
        raise ValueError(f"Action {tag.get('id')} is missing its method or URI.")

    uri = normalize(uri_tag.get_text())
    action = Action(
        id=str(tag.get("id")),
        name=normalize(name_tag.get_text()) if name_tag else "",
        method=normalize(method_tag.get_text()).lower(),
        uri=uri,
        group=group,
        resource=resource,
    )
    action.name = action.name or f"{action.method.upper()} {action.path}"

    description: list[str] = []
    for child in tag.find_all(recursive=False):
        if child is heading:
            continue
        if child.name in ("h4", "div"):
            break
        if child.name == "ul":
            fields = parse_field_list(child)
            if fields:
                action.fields.extend(fields)
                continue
        if child.name in ("p", "ul", "ol"):
            description.append(block_markdown(child))
    action.description = "\n\n".join(part for part in description if part)

    for title in tag.find_all("div", class_="title", recursive=False):
        strong = title.find("strong")
        content = title.find_next_sibling("div", class_="collapse-content")
        if strong is None or content is None:
            continue
        label = normalize(strong.get_text())
        if label.lower() == "uri parameters":
            dl = content.find("dl")
            action.params = parse_params(dl) if dl else []
        elif label.lower().startswith("request"):
            action.requests.append(parse_sample(content, None))
        elif label.lower().startswith("response"):
            status = label.split(" ", 1)[1].strip() if " " in label else None
            action.responses.append(parse_sample(content, status))
    return action


def parse_intro(content: Tag) -> tuple[str, list[tuple[str, str]], str | None]:
    paragraphs: list[str] = []
    servers: list[tuple[str, str]] = []
    email: str | None = None
    for child in content.find_all(recursive=False):
        if child.name == "section":
            break
        if child.name not in ("p", "ul", "ol"):
            continue
        paragraphs.append(block_markdown(child))
        if child.name == "ul":
            for item in child.find_all("li", recursive=False):
                match = SERVER_PATTERN.match(normalize(item.get_text()))
                if match:
                    servers.append((match.group("name"), match.group("url").rstrip("/")))
        for link in child.find_all("a", href=True):
            href = str(link["href"])
            if href.startswith("mailto:") and email is None:
                email = href.removeprefix("mailto:")
    return "\n\n".join(paragraphs), servers, email


def parse_documentation(html: str) -> Documentation:
    soup = BeautifulSoup(html, "html.parser")
    sections = soup.select("section.resource-group")
    if not sections:
        raise ValueError("No resource groups found; the documentation layout may have changed.")

    first = sections[0]
    content = first.parent if isinstance(first.parent, Tag) else soup
    title_tag = soup.find("h1")
    description, servers, email = parse_intro(content)
    version_match = API_VERSION_PATTERN.search(description)

    documentation = Documentation(
        title=normalize(title_tag.get_text()) if title_tag else "BirdWeather",
        description=description,
        api_version=version_match.group(1) if version_match else None,
        servers=servers,
        contact_email=email,
    )
    for section in sections:
        group_tag = section.find("h2")
        group = heading_text(group_tag) if group_tag else str(section.get("id", ""))
        for resource_tag in section.find_all("div", class_="resource"):
            resource_heading = resource_tag.find("h3")
            resource = heading_text(resource_heading) if resource_heading else group
            for action_tag in resource_tag.find_all("div", class_="action"):
                documentation.actions.append(parse_action(action_tag, group, resource))

    if not documentation.actions:
        raise ValueError("No actions found; the documentation layout may have changed.")
    return documentation
