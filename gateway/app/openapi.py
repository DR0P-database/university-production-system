from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

import httpx
from fastapi.openapi.utils import get_openapi

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def _rewrite_references(value: Any, references: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {
            key: references.get(item, item)
            if key == "$ref"
            else _rewrite_references(item, references)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite_references(item, references) for item in value]
    return value


def _prefix_components(
    service: str, schema: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    components = schema.get("components", {})
    renamed: dict[str, dict[str, Any]] = {}
    references: dict[str, str] = {}

    for component_type, definitions in components.items():
        if not isinstance(definitions, dict) or component_type == "securitySchemes":
            continue
        renamed[component_type] = {}
        for name in definitions:
            prefixed_name = f"{service}_{name}"
            references[f"#/components/{component_type}/{name}"] = (
                f"#/components/{component_type}/{prefixed_name}"
            )

    for component_type, definitions in components.items():
        if not isinstance(definitions, dict) or component_type == "securitySchemes":
            continue
        for name, definition in definitions.items():
            renamed[component_type][f"{service}_{name}"] = _rewrite_references(
                definition, references
            )

    return renamed, references


def merge_openapi_schemas(
    gateway_routes: list[Any], service_schemas: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Merge internal service contracts into the public gateway contract."""
    merged = get_openapi(
        title="University API Gateway",
        version="1.0.0",
        description="Unified API for the university system",
        routes=gateway_routes,
    )
    merged.setdefault("components", {})["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }

    tags: dict[str, dict[str, Any]] = {
        tag["name"]: tag for tag in merged.get("tags", [])
    }
    for service, original_schema in service_schemas.items():
        schema = deepcopy(original_schema)
        components, references = _prefix_components(service, schema)
        paths = _rewrite_references(schema.get("paths", {}), references)

        for path, path_item in paths.items():
            if not path.startswith(f"/api/v1/{service}"):
                continue
            if path in merged["paths"]:
                raise ValueError(f"Duplicate OpenAPI path: {path}")
            for method, operation in path_item.items():
                if method not in HTTP_METHODS or not isinstance(operation, dict):
                    continue
                operation.setdefault("security", [{"BearerAuth": []}])
                if "operationId" in operation:
                    operation["operationId"] = f"{service}_{operation['operationId']}"
                operation["x-service"] = service
            merged["paths"][path] = path_item

        for component_type, definitions in components.items():
            merged["components"].setdefault(component_type, {}).update(definitions)
        for tag in schema.get("tags", []):
            tags.setdefault(tag["name"], tag)

    if tags:
        merged["tags"] = list(tags.values())
    return merged


async def fetch_service_schemas(
    client: httpx.AsyncClient, service_urls: dict[str, str]
) -> dict[str, dict[str, Any]]:
    async def fetch(service: str, base_url: str) -> tuple[str, dict[str, Any]]:
        response = await client.get(f"{base_url}/openapi.json")
        response.raise_for_status()
        return service, response.json()

    results = await asyncio.gather(
        *(fetch(service, base_url) for service, base_url in service_urls.items())
    )
    return dict(results)
