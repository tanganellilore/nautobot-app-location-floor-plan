# ruff: noqa: D106,D107
# pylint: disable=too-many-ancestors,abstract-method
"""API serializers for Location Floor Plan."""

import re

from django.core.validators import RegexValidator
from nautobot.apps.api import NautobotModelSerializer
from nautobot.dcim.models import Location, Rack
from rest_framework import serializers

from location_floor_plan.models import FloorPlan, LocationPlacement, LocationStyle, RackPlacement, RackStyle

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class HexColorField(serializers.CharField):
    """Strict 6-digit hex color field."""

    default_error_messages = {"invalid": "Enter a valid hex color (e.g. #RRGGBB)."}

    def __init__(self, **kwargs):
        kwargs.setdefault("allow_null", True)
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)
        self.validators.append(RegexValidator(HEX_COLOR_RE, "Enter a valid hex color (e.g. #RRGGBB)."))

    def to_internal_value(self, data):
        """Accept null without running the hex validator."""
        if data is None and self.allow_null:
            return None
        return super().to_internal_value(data)


class FloorPlanSerializer(NautobotModelSerializer):
    """Serializer for floor plans."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and "location" in self.fields:
            self.fields["location"].queryset = Location.objects.restrict(request.user, "view")

    class Meta:
        model = FloorPlan
        # Keep explicit fields to avoid exposing unintended model/API fields.
        # pylint: disable-next=nb-use-fields-all
        fields = ["id", "url", "display", "location", "logical_width", "logical_height", "revision"]
        read_only_fields = ["id", "url", "display", "revision"]


class LocationPlacementSerializer(NautobotModelSerializer):
    """Read-only Phase 2 serializer for location placements."""

    expected_revision = serializers.IntegerField(write_only=True, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None:
            self.fields["floor_plan"].queryset = FloorPlan.objects.restrict(request.user, "view")
            self.fields["location"].queryset = Location.objects.restrict(request.user, "view")

    class Meta:
        model = LocationPlacement
        # Keep explicit fields to avoid exposing unintended model/API fields.
        # pylint: disable-next=nb-use-fields-all
        fields = ["id", "url", "display", "floor_plan", "location", "geometry", "color", "expected_revision"]
        read_only_fields = ["id", "url", "display"]


class RackPlacementSerializer(NautobotModelSerializer):
    """Read-only Phase 2 serializer for rack placements."""

    expected_revision = serializers.IntegerField(write_only=True, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None:
            self.fields["floor_plan"].queryset = FloorPlan.objects.restrict(request.user, "view")
            self.fields["rack"].queryset = Rack.objects.restrict(request.user, "view")

    class Meta:
        model = RackPlacement
        # Keep explicit fields to avoid exposing unintended model/API fields.
        # pylint: disable-next=nb-use-fields-all
        fields = [
            "id",
            "url",
            "display",
            "floor_plan",
            "rack",
            "x",
            "y",
            "width",
            "height",
            "color",
            "expected_revision",
        ]
        read_only_fields = ["id", "url", "display"]


class ResolvedFloorPlanSerializer(serializers.Serializer):
    """Serializer for resolver result."""

    requested_location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all())
    floor_plan = FloorPlanSerializer(allow_null=True)
    qualifier = LocationPlacementSerializer(allow_null=True)
    source = serializers.CharField()


class FloorPlanSnapshotSerializer(serializers.Serializer):
    """Minimal snapshot payload."""

    map = FloorPlanSerializer()
    location_placements = LocationPlacementSerializer(many=True)
    rack_placements = RackPlacementSerializer(many=True)
    stale_location_placements = LocationPlacementSerializer(many=True)
    stale_rack_placements = RackPlacementSerializer(many=True)


class LocationPlacementSnapshotWriteSerializer(serializers.Serializer):
    """Writable location placement snapshot item."""

    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all())
    geometry = serializers.JSONField()
    color = HexColorField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None:
            self.fields["location"].queryset = Location.objects.restrict(request.user, "view")


class RackPlacementSnapshotWriteSerializer(serializers.Serializer):
    """Writable rack placement snapshot item."""

    rack = serializers.PrimaryKeyRelatedField(queryset=Rack.objects.all())
    x = serializers.IntegerField(min_value=0)
    y = serializers.IntegerField(min_value=0)
    width = serializers.IntegerField(min_value=1)
    height = serializers.IntegerField(min_value=1)
    color = HexColorField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None:
            self.fields["rack"].queryset = Rack.objects.restrict(request.user, "view")


class SnapshotWriteSerializer(serializers.Serializer):
    """Writable complete snapshot."""

    expected_revision = serializers.IntegerField(required=False)
    location_placements = LocationPlacementSnapshotWriteSerializer(many=True)
    rack_placements = RackPlacementSnapshotWriteSerializer(many=True)
    delete_stale_ids = serializers.ListField(child=serializers.UUIDField(), required=False)


class LocationStyleSerializer(serializers.ModelSerializer):
    """Serializer for persistent Location style."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None:
            self.fields["location"].queryset = Location.objects.restrict(request.user, "view")

    class Meta:
        model = LocationStyle
        # pylint: disable-next=nb-use-fields-all
        fields = ["id", "location", "color"]


class RackStyleSerializer(serializers.ModelSerializer):
    """Serializer for persistent Rack style."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None:
            self.fields["rack"].queryset = Rack.objects.restrict(request.user, "view")

    class Meta:
        model = RackStyle
        # pylint: disable-next=nb-use-fields-all
        fields = ["id", "rack", "color"]
