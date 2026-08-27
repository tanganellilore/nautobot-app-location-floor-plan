# ruff: noqa: D101,D106
# pylint: disable=missing-class-docstring
"""FilterSets for Location Floor Plan API."""

from nautobot.apps.filters import NautobotFilterSet

from location_floor_plan.models import FloorPlan, LocationPlacement, RackPlacement


class FloorPlanFilterSet(NautobotFilterSet):
    class Meta:
        model = FloorPlan
        # Keep filters explicit; __all__ could expose unintended fields.
        # pylint: disable-next=nb-use-fields-all
        fields = ["id", "location"]


class LocationPlacementFilterSet(NautobotFilterSet):
    class Meta:
        model = LocationPlacement
        # Keep filters explicit; __all__ could expose unintended fields.
        # pylint: disable-next=nb-use-fields-all
        fields = ["id", "floor_plan", "location"]


class RackPlacementFilterSet(NautobotFilterSet):
    class Meta:
        model = RackPlacement
        # Keep filters explicit; __all__ could expose unintended fields.
        # pylint: disable-next=nb-use-fields-all
        fields = ["id", "floor_plan", "rack"]
