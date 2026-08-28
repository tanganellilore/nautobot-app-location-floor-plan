"""Tables for Location Floor Plan UI views."""

import django_tables2 as tables
from django.urls import reverse
from django.utils.html import format_html
from nautobot.apps.tables import BaseTable

from location_floor_plan.models import FloorPlan


class FloorPlanTable(BaseTable):
    """Native Nautobot table for locations that own Location Floor Plan maps."""

    location = tables.Column(
        verbose_name="Location",
        order_by="location__name",
    )
    dimensions = tables.Column(empty_values=(), verbose_name="Dimensions", orderable=False)
    actions = tables.Column(empty_values=(), verbose_name="", orderable=False)

    class Meta(BaseTable.Meta):  # pylint: disable=too-few-public-methods
        """Table configuration."""

        model = FloorPlan
        fields = ("location", "dimensions", "revision", "last_updated", "actions")

    def render_location(self, record):
        """Render location name as a direct link to its floor plan view."""
        url = reverse("plugins:location_floor_plan:location_floor_plan", kwargs={"pk": record.location.pk})
        return format_html('<a href="{}">{}</a>', url, record.location)

    def render_dimensions(self, record):
        """Render logical dimensions compactly."""
        return f"{record.logical_width} × {record.logical_height}"

    def render_actions(self, record):
        """Render a concise link to the existing map view."""
        url = reverse("plugins:location_floor_plan:location_floor_plan", kwargs={"pk": record.location.pk})
        return format_html('<a href="{}" class="btn btn-xs btn-primary">Open Map</a>', url)
