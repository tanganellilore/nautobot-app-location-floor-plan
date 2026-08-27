"""Tests for the native Floor Plan list view."""

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from nautobot.dcim.factory import LocationFactory, LocationTypeFactory
from nautobot.dcim.models import Location, Rack
from nautobot.extras.models import Status

from location_floor_plan.models import FloorPlan, LocationPlacement


class FloorPlanListViewTestCase(TestCase):
    """Floor plan owner list behavior."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="floorplan-list")
        self.client.force_login(self.user)

        status_obj, _ = Status.objects.get_or_create(name="Active", defaults={"color": "4caf50"})
        status_obj.content_types.add(ContentType.objects.get_for_model(Location))
        location_type = LocationTypeFactory(nestable=True, parent=None)
        location_type.content_types.add(ContentType.objects.get_for_model(Rack))

        self.owner = LocationFactory(name="Owner With Map", location_type=location_type, parent=None, status=status_obj)
        self.inherited = LocationFactory(
            name="Inherited Only", location_type=location_type, parent=self.owner, status=status_obj
        )
        self.no_map = LocationFactory(name="No Own Map", location_type=location_type, parent=None, status=status_obj)
        self.floor_plan = FloorPlan.objects.create(location=self.owner, logical_width=100, logical_height=200)
        LocationPlacement.objects.create(
            floor_plan=self.floor_plan,
            location=self.inherited,
            geometry={"type": "rectangle", "x": 1, "y": 1, "width": 10, "height": 10},
        )

    def test_url_reverses_and_lists_only_locations_that_own_maps(self):
        response = self.client.get(reverse("plugins:location_floor_plan:floorplan_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Owner With Map")
        self.assertNotContains(response, "Inherited Only")
        self.assertNotContains(response, "No Own Map")

    def test_location_row_links_to_existing_location_floor_plan_route(self):
        response = self.client.get(reverse("plugins:location_floor_plan:floorplan_list"))
        map_url = reverse("plugins:location_floor_plan:location_floor_plan", kwargs={"pk": self.owner.pk})

        self.assertContains(response, map_url)

    def test_navigation_declares_organization_floor_plan_item(self):
        from location_floor_plan.navigation import menu_items

        organization = menu_items[0]
        group = organization.groups[0]
        item = group.items[0]

        self.assertEqual(organization.name, "Organization")
        self.assertEqual(group.name, "Locations")
        self.assertEqual(item.name, "Floor Plans")
        self.assertEqual(item.link, "plugins:location_floor_plan:floorplan_list")
        self.assertIn("location_floor_plan.view_floorplan", item.permissions)
