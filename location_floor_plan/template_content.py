# pylint: disable=missing-module-docstring,missing-class-docstring,abstract-method
from nautobot.apps.ui import DistinctViewTab, TemplateExtension


class LocationFloorPlanTab(TemplateExtension):
    model = "dcim.location"

    object_detail_tabs = [
        DistinctViewTab(
            tab_id="location-floor-plan",
            label="Floor Plan",
            url_name="plugins:location_floor_plan:location_floor_plan",
            weight=500,
            required_permissions=["location_floor_plan.view_floorplan"],
        )
    ]


template_extensions = [LocationFloorPlanTab]
