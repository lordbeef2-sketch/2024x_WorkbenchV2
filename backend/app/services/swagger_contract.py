from __future__ import annotations

import json
import re
from functools import cached_property
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, quote

from app.models.domain import (
    SwaggerContractManifest,
    SwaggerOperationSpec,
    SwaggerParameterSpec,
    SwaggerRequestBodySpec,
    SwaggerResponseSpec,
    SwaggerSchemaProperty,
    SwaggerSchemaSummary,
)


PATH_PARAM_PATTERN = re.compile(r"{([^}/]+)}")
OPERATION_KEY_PATTERN = re.compile(r"[^a-zA-Z0-9]+")


def _schema_ref(schema: dict[str, Any] | None) -> str | None:
    if not isinstance(schema, dict):
        return None
    ref = schema.get("$ref")
    return str(ref).rsplit("/", 1)[-1] if isinstance(ref, str) else None


def _schema_type(schema: dict[str, Any] | None) -> str:
    if not isinstance(schema, dict):
        return "string"
    if schema.get("$ref"):
        return "object"
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        return schema_type
    if "properties" in schema:
        return "object"
    if "items" in schema:
        return "array"
    return "string"


def _operation_key(method: str, path: str) -> str:
    slug = OPERATION_KEY_PATTERN.sub("_", f"{method.lower()}_{path.strip('/')}").strip("_")
    return slug or method.lower()


class SwaggerContract:
    def __init__(self, path: Path) -> None:
        self.path = path

    @cached_property
    def spec(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    @cached_property
    def operations_by_key(self) -> dict[str, SwaggerOperationSpec]:
        operations: dict[str, SwaggerOperationSpec] = {}
        seen_keys: set[str] = set()
        for path, path_item in sorted(self.spec.get("paths", {}).items()):
            if not isinstance(path_item, dict):
                continue
            path_level_parameters = path_item.get("parameters") if isinstance(path_item.get("parameters"), list) else []
            for method, operation in sorted(path_item.items()):
                if method.lower() not in {"get", "post", "put", "patch", "delete"} or not isinstance(operation, dict):
                    continue
                base_key = _operation_key(method, path)
                key = base_key
                collision_index = 2
                while key in seen_keys:
                    key = f"{base_key}_{collision_index}"
                    collision_index += 1
                seen_keys.add(key)
                parsed = self._parse_operation(key, method.upper(), path, operation, path_level_parameters)
                operations[parsed.key] = parsed
        return operations

    @cached_property
    def schemas(self) -> list[SwaggerSchemaSummary]:
        summaries: list[SwaggerSchemaSummary] = []
        for name, schema in sorted(self.spec.get("components", {}).get("schemas", {}).items()):
            if not isinstance(schema, dict):
                summaries.append(
                    SwaggerSchemaSummary(
                        name=name,
                        schema_type="string",
                        description=str(schema),
                    )
                )
                continue
            required_names = schema.get("required") if isinstance(schema.get("required"), list) else []
            properties: list[SwaggerSchemaProperty] = []
            raw_properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            for property_name, property_schema in sorted(raw_properties.items()):
                if not isinstance(property_schema, dict):
                    property_schema = {}
                properties.append(
                    SwaggerSchemaProperty(
                        name=property_name,
                        schema_type=_schema_type(property_schema),
                        schema_format=property_schema.get("format") if isinstance(property_schema.get("format"), str) else None,
                        schema_ref=_schema_ref(property_schema),
                        description=str(property_schema.get("description") or ""),
                        required=property_name in required_names,
                        enum=property_schema.get("enum") if isinstance(property_schema.get("enum"), list) else [],
                    )
                )
            summaries.append(
                SwaggerSchemaSummary(
                    name=name,
                    schema_type=_schema_type(schema),
                    description=str(schema.get("description") or ""),
                    required=[str(item) for item in required_names],
                    properties=properties,
                )
            )
        return summaries

    def manifest(self) -> SwaggerContractManifest:
        operations = list(self.operations_by_key.values())
        operation_counts: dict[str, int] = {}
        tag_counts: dict[str, int] = {}
        for operation in operations:
            operation_counts[operation.method] = operation_counts.get(operation.method, 0) + 1
            tag_counts[operation.tag] = tag_counts.get(operation.tag, 0) + 1

        info = self.spec.get("info") if isinstance(self.spec.get("info"), dict) else {}
        server_urls = [
            str(server.get("url"))
            for server in self.spec.get("servers", [])
            if isinstance(server, dict) and server.get("url")
        ]
        security_schemes = self.spec.get("components", {}).get("securitySchemes", {})
        warnings = self._warnings()
        return SwaggerContractManifest(
            openapi=str(self.spec.get("openapi") or ""),
            title=str(info.get("title") or ""),
            version=str(info.get("version") or ""),
            server_urls=server_urls,
            security=sorted(str(name) for name in security_schemes),
            operation_counts=dict(sorted(operation_counts.items())),
            tag_counts=dict(sorted(tag_counts.items())),
            operations=operations,
            schemas=self.schemas,
            warnings=warnings,
        )

    def operation(self, operation_key: str) -> SwaggerOperationSpec:
        try:
            return self.operations_by_key[operation_key]
        except KeyError as exc:
            raise KeyError(f"Swagger operation '{operation_key}' is not present in RealSwagger.json.") from exc

    def build_candidate_path(
        self,
        operation_key: str,
        *,
        path_params: dict[str, Any],
        query_params: dict[str, Any],
    ) -> tuple[SwaggerOperationSpec, str]:
        operation = self.operation(operation_key)
        declared_path_params = {parameter.name for parameter in operation.path_parameters}
        missing = [
            parameter.name
            for parameter in operation.path_parameters
            if parameter.required and _empty(path_params.get(parameter.name))
        ]
        if missing:
            raise ValueError(f"Missing required path parameter(s): {', '.join(missing)}")

        undeclared_path = sorted(set(path_params) - declared_path_params)
        if undeclared_path:
            raise ValueError(f"Path parameter(s) are not declared by this operation: {', '.join(undeclared_path)}")

        candidate_path = operation.path
        for parameter_name in declared_path_params:
            if parameter_name in path_params:
                candidate_path = candidate_path.replace(f"{{{parameter_name}}}", quote(str(path_params[parameter_name]), safe=""))

        declared_query_params = {parameter.name for parameter in operation.query_parameters}
        undeclared_query = sorted(key for key, value in query_params.items() if not _empty(value) and key not in declared_query_params)
        if undeclared_query:
            raise ValueError(f"Query parameter(s) are not declared by this operation: {', '.join(undeclared_query)}")

        query_items: list[tuple[str, str]] = []
        for parameter in operation.query_parameters:
            if parameter.name not in query_params:
                continue
            value = query_params.get(parameter.name)
            if _empty(value):
                continue
            if isinstance(value, list):
                query_items.extend((parameter.name, _query_value(item)) for item in value if not _empty(item))
            else:
                query_items.append((parameter.name, _query_value(value)))
        if query_items:
            candidate_path = f"{candidate_path}?{urlencode(query_items, doseq=True)}"
        return operation, candidate_path

    def _parse_operation(
        self,
        key: str,
        method: str,
        path: str,
        operation: dict[str, Any],
        path_level_parameters: list[Any],
    ) -> SwaggerOperationSpec:
        raw_parameters = [
            *(parameter for parameter in path_level_parameters if isinstance(parameter, dict)),
            *(operation.get("parameters") if isinstance(operation.get("parameters"), list) else []),
        ]
        parsed_parameters = [self._parse_parameter(parameter) for parameter in raw_parameters if isinstance(parameter, dict)]
        parameters_by_key = {
            (parameter.location, parameter.name): parameter for parameter in parsed_parameters if parameter is not None
        }
        parameters = list(parameters_by_key.values())
        parameter_names = {(parameter.location, parameter.name) for parameter in parameters}
        for path_parameter in PATH_PARAM_PATTERN.findall(path):
            if ("path", path_parameter) not in parameter_names:
                parameters.append(
                    SwaggerParameterSpec(
                        name=path_parameter,
                        location="path",
                        required=True,
                        schema_type="string",
                        description="Path parameter inferred from RealSwagger.json path template.",
                    )
                )

        request_body = self._parse_request_body(operation.get("requestBody"))
        responses = self._parse_responses(operation.get("responses"))
        form_parameters = [parameter for parameter in parameters if parameter.location == "formData"]
        query_parameters = [parameter for parameter in parameters if parameter.location == "query"]
        supports_download = any(parameter.name == "download" for parameter in query_parameters) or "/artifacts/" in path
        tags = [str(tag) for tag in operation.get("tags", []) if tag]
        return SwaggerOperationSpec(
            key=key,
            method=method,
            path=path,
            tag=tags[0] if tags else "Untagged",
            tags=tags,
            operation_id=operation.get("operationId") if isinstance(operation.get("operationId"), str) else None,
            summary=str(operation.get("summary") or ""),
            description=str(operation.get("description") or ""),
            path_parameters=sorted(
                [parameter for parameter in parameters if parameter.location == "path"], key=lambda item: item.name
            ),
            query_parameters=query_parameters,
            header_parameters=[parameter for parameter in parameters if parameter.location == "header"],
            form_parameters=form_parameters,
            request_body=request_body,
            responses=responses,
            supports_file_upload=any(parameter.is_file for parameter in form_parameters),
            supports_download=supports_download,
            destructive=method in {"POST", "PUT", "PATCH", "DELETE"},
        )

    def _parse_parameter(self, parameter: dict[str, Any]) -> SwaggerParameterSpec | None:
        name = parameter.get("name")
        location = parameter.get("in")
        if not isinstance(name, str) or not isinstance(location, str):
            return None
        schema = parameter.get("schema") if isinstance(parameter.get("schema"), dict) else {}
        schema_type = _schema_type(schema)
        return SwaggerParameterSpec(
            name=name,
            location=location,
            required=bool(parameter.get("required")),
            schema_type=schema_type,
            schema_format=schema.get("format") if isinstance(schema.get("format"), str) else None,
            schema_ref=_schema_ref(schema),
            description=str(parameter.get("description") or ""),
            enum=schema.get("enum") if isinstance(schema.get("enum"), list) else [],
            default=schema.get("default"),
            is_file=schema_type == "file",
        )

    def _parse_request_body(self, request_body: Any) -> SwaggerRequestBodySpec | None:
        if not isinstance(request_body, dict):
            return None
        content = request_body.get("content") if isinstance(request_body.get("content"), dict) else {}
        schema_refs: dict[str, str | None] = {}
        for content_type, media in content.items():
            if isinstance(media, dict):
                schema_refs[str(content_type)] = _schema_ref(media.get("schema") if isinstance(media.get("schema"), dict) else None)
            else:
                schema_refs[str(content_type)] = None
        return SwaggerRequestBodySpec(
            required=bool(request_body.get("required")),
            description=str(request_body.get("description") or ""),
            content_types=list(schema_refs),
            schema_refs=schema_refs,
        )

    def _parse_responses(self, responses: Any) -> list[SwaggerResponseSpec]:
        parsed: list[SwaggerResponseSpec] = []
        if not isinstance(responses, dict):
            return parsed
        for status_code, response in sorted(responses.items(), key=lambda item: str(item[0])):
            if not isinstance(response, dict):
                parsed.append(SwaggerResponseSpec(status_code=str(status_code)))
                continue
            content = response.get("content") if isinstance(response.get("content"), dict) else {}
            content_types = [str(content_type) for content_type in content]
            schema_ref: str | None = None
            for media in content.values():
                if isinstance(media, dict):
                    schema_ref = _schema_ref(media.get("schema") if isinstance(media.get("schema"), dict) else None)
                    if schema_ref:
                        break
            parsed.append(
                SwaggerResponseSpec(
                    status_code=str(status_code),
                    description=str(response.get("description") or ""),
                    content_types=content_types,
                    schema_ref=schema_ref,
                )
            )
        return parsed

    def _warnings(self) -> list[str]:
        warnings: list[str] = []
        for operation in self.operations_by_key.values():
            if any(parameter.location == "formData" for parameter in operation.form_parameters):
                warnings.append(
                    "RealSwagger.json is OpenAPI 3.0 but uses Swagger 2.0-style formData parameters for artifact uploads; these are treated as multipart form file uploads."
                )
                break
        redirect_reads = [
            f"{operation.method} {operation.path}"
            for operation in self.operations_by_key.values()
            if operation.method == "GET" and any(response.status_code in {"301", "307"} for response in operation.responses)
        ]
        if redirect_reads:
            warnings.append(
                "Some read operations declare redirect response codes instead of normal JSON response schemas: "
                + ", ".join(redirect_reads[:6])
                + ("." if len(redirect_reads) <= 6 else f", and {len(redirect_reads) - 6} more.")
            )
        return warnings


def _empty(value: Any) -> bool:
    return value is None or value == ""


def _query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
