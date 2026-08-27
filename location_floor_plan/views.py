# pylint: disable=missing-module-docstring,missing-class-docstring
from django.urls import reverse
from django.middleware.csrf import get_token
from nautobot.core.views import generic
from nautobot.dcim.models import Location
from nautobot.apps.views import ObjectListView

from location_floor_plan.api.filtersets import FloorPlanFilterSet
from location_floor_plan.forms import PlacementPickerForm
from location_floor_plan.models import FloorPlan
from location_floor_plan.tables import FloorPlanTable


class FloorPlanListView(ObjectListView):
    """List locations that own a configured Location Floor Plan map."""

    queryset = FloorPlan.objects.select_related("location")
    filterset = FloorPlanFilterSet
    filterset_class = FloorPlanFilterSet
    table = FloorPlanTable
    action_buttons = ()

    def alter_queryset(self, request):
        """Restrict list to maps and owning locations visible to the current user."""
        return self.queryset.restrict(request.user, "view").filter(
            location__in=Location.objects.restrict(request.user, "view")
        )


class LocationFloorPlanView(generic.ObjectView):
    queryset = Location.objects.all()
    template_name = "location_floor_plan/location_floor_plan.html"

    def get_extra_context(self, request, instance):
        api_resolved_url = reverse(
            "plugins-api:location_floor_plan-api:location-resolved-map", kwargs={"location_id": instance.pk}
        )
        api_map_list_url = reverse("plugins-api:location_floor_plan-api:floorplan-list")
        own_map = FloorPlan.objects.filter(location=instance).first()
        perms = {
            "viewMap": request.user.has_perm("location_floor_plan.view_floorplan"),
            "addMap": request.user.has_perm("location_floor_plan.add_floorplan")
            and request.user.has_perm("dcim.view_location", instance),
            "changeMap": request.user.has_perm("location_floor_plan.change_floorplan", own_map)
            if own_map
            else request.user.has_perm("location_floor_plan.change_floorplan"),
            "deleteMap": request.user.has_perm("location_floor_plan.delete_floorplan", own_map)
            if own_map
            else request.user.has_perm("location_floor_plan.delete_floorplan"),
            "addLocationPlacement": request.user.has_perm("location_floor_plan.add_locationplacement"),
            "changeLocationPlacement": request.user.has_perm("location_floor_plan.change_locationplacement"),
            "deleteLocationPlacement": request.user.has_perm("location_floor_plan.delete_locationplacement"),
            "addRackPlacement": request.user.has_perm("location_floor_plan.add_rackplacement"),
            "changeRackPlacement": request.user.has_perm("location_floor_plan.change_rackplacement"),
            "deleteRackPlacement": request.user.has_perm("location_floor_plan.delete_rackplacement"),
        }

        return {
            "active_tab": "location-floor-plan",
            "has_edit_permission": perms["addMap"] or perms["changeMap"] or perms["deleteMap"],
            "lfp_permissions": perms,
            "api_resolved_url": api_resolved_url,
            "api_map_list_url": api_map_list_url,
            "lfp_csrf_token": str(get_token(request)),
            "placement_picker_form": PlacementPickerForm(),
        }
