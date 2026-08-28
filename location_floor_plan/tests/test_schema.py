"""OpenAPI schema generation regression tests."""

from django.test import TestCase
from drf_spectacular.generators import SchemaGenerator


class LocationFloorPlanSchemaTestCase(TestCase):
    """Schema generation tests for Location Floor Plan API views."""

    def test_schema_generation_does_not_introspect_disabled_bulk_actions(self):
        """Regression for Nautobot bulk-delete schema expecting a ListSerializer.child."""
        schema = SchemaGenerator().get_schema(request=None, public=True)

        self.assertIn("paths", schema)
