# ruff: noqa: D106,D107
# pylint: disable=too-many-ancestors,abstract-method
"""API serializers for Location Floor Plan."""

from nautobot.apps.api import NautobotModelSerializer
from nautobot.dcim.models import Location, Rack
from rest_framework import serializers

from location_floor_plan.models import LocationMap, LocationPlacement, RackPlacement


class LocationMapSerializer(NautobotModelSerializer):
    """Serializer for location maps."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and "location" in self.fields:
            self.fields["location"].queryset = Location.objects.restrict(request.user, "view")

    class Meta:
        model = LocationMap
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
            self.fields["location_map"].queryset = LocationMap.objects.restrict(request.user, "view")
            self.fields["location"].queryset = Location.objects.restrict(request.user, "view")

    class Meta:
        model = LocationPlacement
        # Keep explicit fields to avoid exposing unintended model/API fields.
        # pylint: disable-next=nb-use-fields-all
        fields = ["id", "url", "display", "location_map", "location", "geometry", "expected_revision"]
        read_only_fields = ["id", "url", "display"]


class RackPlacementSerializer(NautobotModelSerializer):
    """Read-only Phase 2 serializer for rack placements."""

    expected_revision = serializers.IntegerField(write_only=True, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None:
            self.fields["location_map"].queryset = LocationMap.objects.restrict(request.user, "view")
            self.fields["rack"].queryset = Rack.objects.restrict(request.user, "view")

    class Meta:
        model = RackPlacement
        # Keep explicit fields to avoid exposing unintended model/API fields.
        # pylint: disable-next=nb-use-fields-all
        fields = ["id", "url", "display", "location_map", "rack", "x", "y", "width", "height", "expected_revision"]
        read_only_fields = ["id", "url", "display"]


class ResolvedLocationMapSerializer(serializers.Serializer):
    """Serializer for resolver result."""

    requested_location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all())
    location_map = LocationMapSerializer(allow_null=True)
    qualifier = LocationPlacementSerializer(allow_null=True)
    source = serializers.CharField()


class LocationMapSnapshotSerializer(serializers.Serializer):
    """Minimal snapshot payload."""

    map = LocationMapSerializer()
    location_placements = LocationPlacementSerializer(many=True)
    rack_placements = RackPlacementSerializer(many=True)
    stale_location_placements = LocationPlacementSerializer(many=True)
    stale_rack_placements = RackPlacementSerializer(many=True)


class LocationPlacementSnapshotWriteSerializer(serializers.Serializer):
    """Writable location placement snapshot item."""

    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all())
    geometry = serializers.JSONField()

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
