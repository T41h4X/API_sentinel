"""
Tests for api_sentinel.inferencer — infer_json_schema function
"""

import pytest
from api_sentinel.inferencer import infer_json_schema, infer_multi_json_schema, SchemaInferencer


class TestInferJsonSchema:
    """Tests for the standalone infer_json_schema function."""

    def test_simple_object(self):
        """Infer schema from a flat dictionary."""
        payload = {"name": "Alice", "age": 30, "active": True}
        schema = infer_json_schema(payload)

        assert schema["type"] == "object"
        assert "properties" in schema
        assert schema["properties"]["name"] == {"type": "string"}
        assert schema["properties"]["age"] == {"type": "integer"}
        assert schema["properties"]["active"] == {"type": "boolean"}
        # genson marks all observed keys as required
        assert set(schema["required"]) == {"name", "age", "active"}

    def test_nested_object(self):
        """Infer schema from a nested dictionary."""
        payload = {
            "user": {
                "id": 1,
                "profile": {
                    "bio": "Hello world",
                    "verified": False,
                }
            }
        }
        schema = infer_json_schema(payload)

        assert schema["type"] == "object"
        user_schema = schema["properties"]["user"]
        assert user_schema["type"] == "object"
        profile_schema = user_schema["properties"]["profile"]
        assert profile_schema["type"] == "object"
        assert profile_schema["properties"]["bio"] == {"type": "string"}
        assert profile_schema["properties"]["verified"] == {"type": "boolean"}

    def test_array_of_objects(self):
        """Infer schema from a list of objects."""
        payload = [
            {"id": 1, "title": "First"},
            {"id": 2, "title": "Second"},
        ]
        schema = infer_json_schema(payload)

        assert schema["type"] == "array"
        assert "items" in schema
        items_schema = schema["items"]
        assert items_schema["type"] == "object"
        assert items_schema["properties"]["id"] == {"type": "integer"}
        assert items_schema["properties"]["title"] == {"type": "string"}

    def test_empty_object(self):
        """Infer schema from an empty dictionary."""
        schema = infer_json_schema({})
        assert schema["type"] == "object"

    def test_empty_array(self):
        """Infer schema from an empty list."""
        schema = infer_json_schema([])
        assert schema["type"] == "array"

    def test_mixed_types_in_array(self):
        """Infer schema from a list with mixed-type items."""
        payload = [1, "hello", 3.14, True]
        schema = infer_json_schema(payload)
        assert schema["type"] == "array"
        # genson should produce an anyOf or broader type for mixed items
        assert "items" in schema

    def test_null_payload(self):
        """Handle None payload gracefully."""
        schema = infer_json_schema(None)
        assert schema == {"type": "null"}

    def test_no_dollar_schema_in_output(self):
        """Ensure $schema meta-attribute is stripped from output."""
        payload = {"key": "value"}
        schema = infer_json_schema(payload)
        assert "$schema" not in schema

    def test_complex_real_world_payload(self):
        """Infer schema from a realistic API response payload."""
        payload = {
            "id": 42,
            "name": "Alice Wonderland",
            "email": "alice@example.com",
            "role": "admin",
            "created_at": "2026-08-01T00:00:00Z",
            "metadata": {
                "login_count": 150,
                "last_ip": "192.168.1.1",
            }
        }
        schema = infer_json_schema(payload)

        assert schema["type"] == "object"
        props = schema["properties"]
        assert props["id"] == {"type": "integer"}
        assert props["name"] == {"type": "string"}
        assert props["email"] == {"type": "string"}
        assert props["role"] == {"type": "string"}
        assert props["created_at"] == {"type": "string"}
        assert props["metadata"]["type"] == "object"
        assert props["metadata"]["properties"]["login_count"] == {"type": "integer"}
        assert props["metadata"]["properties"]["last_ip"] == {"type": "string"}

    def test_array_with_nested_objects(self):
        """Infer schema from a list containing nested objects."""
        payload = [
            {
                "id": 1,
                "tags": ["python", "api"],
                "author": {"name": "Bob", "verified": True}
            }
        ]
        schema = infer_json_schema(payload)

        assert schema["type"] == "array"
        item = schema["items"]
        assert item["type"] == "object"
        assert item["properties"]["tags"]["type"] == "array"
        assert item["properties"]["author"]["type"] == "object"


class TestSchemaInferencerClass:
    """Tests for the SchemaInferencer class (preserved from original)."""

    def test_infer_schema_dict(self):
        inferencer = SchemaInferencer()
        schema = inferencer.infer_schema({"name": "test", "count": 5})
        assert schema["type"] == "object"
        assert "$schema" not in schema

    def test_infer_schema_none(self):
        inferencer = SchemaInferencer()
        schema = inferencer.infer_schema(None)
        assert schema == {"type": "null"}

    def test_infer_schema_list(self):
        inferencer = SchemaInferencer()
        schema = inferencer.infer_schema([1, 2, 3])
        assert schema["type"] == "array"
        assert "$schema" not in schema

    def test_infer_multi_json_schema(self):
        payloads = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob", "bio": "Software developer"},
            {"id": 3, "name": "Charlie", "email": "charlie@example.com"},
        ]
        schema = infer_multi_json_schema(payloads)
        assert schema["type"] == "object"
        assert "id" in schema["properties"]
        assert "name" in schema["properties"]
        assert "bio" in schema["properties"]
        assert "email" in schema["properties"]
        assert schema["properties"]["id"]["type"] == "integer"
        assert schema["properties"]["name"]["type"] == "string"

    def test_cumulative_observations_and_field_stats(self):
        tracker = SchemaInferencer()
        assert tracker.observation_count == 0
        assert tracker.get_schema() == {}

        # 1st observation
        tracker.add_observation({"id": 101, "role": "admin", "bio": "Hello"})
        # 2nd observation: bio is null, age is added
        tracker.add_observation({"id": 102, "role": "user", "bio": None, "age": 25})
        # 3rd observation: role as integer (mixed type), no bio
        tracker.add_observation({"id": 103, "role": 123})

        assert tracker.observation_count == 3
        stats = tracker.get_field_stats()

        # Check 'id'
        id_stats = stats["$.id"]
        assert id_stats["occurrence_count"] == 3
        assert id_stats["occurrence_rate"] == 1.0
        assert id_stats["types"] == {"integer": 3}
        assert not id_stats["nullable"]

        # Check 'bio'
        bio_stats = stats["$.bio"]
        assert bio_stats["occurrence_count"] == 2
        assert bio_stats["occurrence_rate"] == round(2 / 3, 4)
        assert bio_stats["nullable"] is True
        assert bio_stats["null_count"] == 1

        # Check 'role' (mixed types: string and integer)
        role_stats = stats["$.role"]
        assert role_stats["occurrence_count"] == 3
        assert role_stats["types"]["string"] == 2
        assert role_stats["types"]["integer"] == 1
        assert role_stats["type_frequencies"]["string"] == round(2 / 3, 4)
        assert role_stats["type_frequencies"]["integer"] == round(1 / 3, 4)

        # Check reset
        tracker.reset()
        assert tracker.observation_count == 0
        assert tracker.get_schema() == {}
        assert tracker.get_field_stats() == {}