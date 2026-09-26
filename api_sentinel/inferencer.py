"""
API Sentinel - Schema Inferencer
Generates and normalizes JSON Schemas from runtime payloads using genson.
"""

from collections import defaultdict
from typing import Any, Dict, List, Optional, Union
from genson import SchemaBuilder


def infer_json_schema(payload: Union[dict, list]) -> dict:
    """
    Infer a JSON Schema from a raw runtime JSON HTTP body (dict or list).

    Uses the genson library's SchemaBuilder to automatically convert
    arbitrary Python data structures into standard JSON Schema dictionaries.
    """
    if payload is None:
        return {"type": "null"}

    builder = SchemaBuilder()
    builder.add_object(payload)
    schema = builder.to_schema()

    # Strip the $schema meta-attribute for cleaner comparison with OpenAPI schemas
    schema.pop("$schema", None)

    return schema


def infer_multi_json_schema(payloads: List[Union[dict, list]]) -> dict:
    """
    Infer a merged JSON Schema from a collection of runtime payloads.
    """
    if not payloads:
        return {"type": "null"}

    builder = SchemaBuilder()
    for payload in payloads:
        if payload is not None:
            builder.add_object(payload)
        else:
            builder.add_object(None)

    schema = builder.to_schema()
    schema.pop("$schema", None)
    return schema


class SchemaInferencer:
    """
    Infers and tracks JSON Schemas and field statistics from runtime payload objects.
    Supports both single-shot schema inference and cumulative multi-observation tracking.
    """

    def __init__(self, schema_uri: str | None = None):
        self.schema_uri = schema_uri
        self._builder = SchemaBuilder(schema_uri=self.schema_uri)
        self.observation_count = 0
        self._field_counts: Dict[str, int] = defaultdict(int)
        self._field_types: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._field_nulls: Dict[str, int] = defaultdict(int)

    def infer_schema(self, data: Any) -> Dict[str, Any]:
        """
        Infer a JSON Schema from a single Python data structure (dict, list, etc.).
        """
        if data is None:
            return {"type": "null"}

        builder = SchemaBuilder(schema_uri=self.schema_uri)
        builder.add_object(data)
        schema = builder.to_schema()
        return self.normalize_schema(schema)

    def add_observation(self, data: Any) -> Dict[str, Any]:
        """
        Record a new runtime observation into the cumulative state.
        Updates cumulative schema, field occurrence counts, and type distributions.
        """
        self.observation_count += 1
        if data is not None:
            self._builder.add_object(data)
            self._record_field_stats(data, prefix="$")
        else:
            self._builder.add_object(None)
            self._field_types["$"]["null"] += 1
            self._field_nulls["$"] += 1

        return self.get_schema()

    def get_schema(self) -> Dict[str, Any]:
        """
        Get the current normalized JSON Schema inferred from all observed payloads.
        """
        if self.observation_count == 0:
            return {}
        schema = self._builder.to_schema()
        return self.normalize_schema(schema)

    def get_field_stats(self) -> Dict[str, Any]:
        """
        Returns field occurrence, type distribution, and nullable statistics
        across all recorded observations.
        """
        stats: Dict[str, Any] = {}
        total = max(self.observation_count, 1)

        for path, count in self._field_counts.items():
            type_counts = dict(self._field_types[path])
            type_freq = {t: round(c / total, 4) for t, c in type_counts.items()}
            null_count = self._field_nulls.get(path, 0)

            stats[path] = {
                "occurrence_count": count,
                "occurrence_rate": round(count / total, 4),
                "types": type_counts,
                "type_frequencies": type_freq,
                "nullable": null_count > 0,
                "null_count": null_count,
                "null_rate": round(null_count / total, 4),
            }

        return stats

    def reset(self) -> None:
        """Reset all observations and cumulative statistics."""
        self._builder = SchemaBuilder(schema_uri=self.schema_uri)
        self.observation_count = 0
        self._field_counts.clear()
        self._field_types.clear()
        self._field_nulls.clear()

    def _record_field_stats(self, obj: Any, prefix: str = "$") -> None:
        """Recursively track field occurrences, types, and nulls."""
        self._field_counts[prefix] += 1
        t_name = self._determine_type(obj)
        self._field_types[prefix][t_name] += 1

        if obj is None:
            self._field_nulls[prefix] += 1
            return

        if isinstance(obj, dict):
            for k, v in obj.items():
                child_path = f"{prefix}.{k}"
                self._record_field_stats(v, child_path)
        elif isinstance(obj, list):
            for item in obj:
                child_path = f"{prefix}[]"
                self._record_field_stats(item, child_path)

    @staticmethod
    def _determine_type(val: Any) -> str:
        if val is None:
            return "null"
        if isinstance(val, bool):
            return "boolean"
        if isinstance(val, int):
            return "integer"
        if isinstance(val, float):
            return "number"
        if isinstance(val, str):
            return "string"
        if isinstance(val, list):
            return "array"
        if isinstance(val, dict):
            return "object"
        return "unknown"

    @staticmethod
    def normalize_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean up and normalize inferred schema for OpenAPI comparison.
        Strips meta attributes like $schema if present.
        """
        normalized = dict(schema)
        normalized.pop("$schema", None)
        return normalized