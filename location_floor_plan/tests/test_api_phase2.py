"""Phase 2 API route and permission contract tests."""
# pylint: disable=missing-function-docstring,broad-exception-caught

import base64

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from nautobot.dcim.factory import LocationFactory, LocationTypeFactory
from nautobot.dcim.models import Location, Rack
from nautobot.extras.models import Status
from nautobot.users.models import ObjectPermission
from rest_framework import status
from rest_framework.test import APIClient

from location_floor_plan.models import LocationMap, LocationPlacement

RECT = {"type": "rectangle", "x": 1, "y": 1, "width": 10, "height": 10}
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def api_reverse(name, kwargs=None):
    """Reverse the Nautobot plugin API namespace as mounted by Nautobot."""
    candidates = [
        f"plugins-api:location_floor_plan-api:{name}",
        f"plugins-api:location-floor-plan-api:{name}",
        f"plugins-api:location_floor_plan:{name}",
    ]
    for candidate in candidates:
        try:
            return reverse(candidate, kwargs=kwargs)
        except Exception:  # noqa: PERF203
            continue
    raise AssertionError(f"Could not reverse plugin API route {name!r}")


class Phase2APITestCase(TestCase):
    """API behavior for mounted plugin routes."""

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser(username="api-root")
        status_obj, _ = Status.objects.get_or_create(name="Active", defaults={"color": "4caf50"})
        status_obj.content_types.add(ContentType.objects.get_for_model(Location))
        location_type = LocationTypeFactory(nestable=True, parent=None)
        location_type.content_types.add(ContentType.objects.get_for_model(Rack))
        self.root = LocationFactory(location_type=location_type, parent=None, status=status_obj)
        self.child = LocationFactory(location_type=location_type, parent=self.root, status=status_obj)
        self.other = LocationFactory(location_type=location_type, parent=None, status=status_obj)

    def login(self):
        self.client.force_authenticate(self.user)

    def test_actual_plugin_api_routes_are_reachable(self):
        self.login()
        location_map = LocationMap.objects.create(location=self.root, logical_width=100, logical_height=100)
        placement = LocationPlacement.objects.create(location_map=location_map, location=self.child, geometry=RECT)
        routes = [
            api_reverse("locationmap-list"),
            api_reverse("locationmap-detail", {"pk": location_map.pk}),
            api_reverse("locationmap-snapshot", {"pk": location_map.pk}),
            api_reverse("locationplacement-list"),
            api_reverse("locationplacement-detail", {"pk": placement.pk}),
            api_reverse("rackplacement-list"),
            api_reverse("location-resolved-map", {"location_id": self.child.pk}),
            api_reverse("locationmap-descendants", {"pk": location_map.pk}),
            api_reverse("locationmap-available-locations", {"pk": location_map.pk}),
            api_reverse("locationmap-available-racks", {"pk": location_map.pk}),
        ]
        for route in routes:
            with self.subTest(route=route):
                self.assertLess(self.client.get(route).status_code, 500)

    def test_create_requires_creation_token_and_background_is_not_persisted(self):
        self.login()
        url = api_reverse("locationmap-list")
        payload = {"location": self.root.pk, "logical_width": 100, "logical_height": 100, "background": "ignored"}
        self.assertEqual(self.client.post(url, payload, format="json").status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            self.client.post(url, payload, format="json", HTTP_IF_NONE_MATCH='"1"').status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(url, payload, format="json", HTTP_IF_NONE_MATCH="bogus").status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        body_payload = {"location": self.other.pk, "logical_width": 100, "logical_height": 100, "expected_revision": 0}
        body_response = self.client.post(url, body_payload, format="json")
        self.assertEqual(body_response.status_code, status.HTTP_201_CREATED, body_response.content)
        response = self.client.post(url, payload, format="json", HTTP_IF_NONE_MATCH="*")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        location_map = LocationMap.objects.get(location=self.root)
        self.assertFalse(location_map.background)
        self.assertNotIn("background", response.data)

    def test_revision_conflicts_are_409_and_current_revision_increments_once(self):
        self.login()
        location_map = LocationMap.objects.create(location=self.root, logical_width=100, logical_height=100)
        detail = api_reverse("locationmap-detail", {"pk": location_map.pk})
        snapshot = api_reverse("locationmap-snapshot", {"pk": location_map.pk})
        self.assertEqual(
            self.client.patch(detail, {"logical_width": 120}, format="json", HTTP_IF_MATCH='"99"').status_code,
            status.HTTP_409_CONFLICT,
        )
        self.assertEqual(
            self.client.patch(detail, {"logical_width": 120}, format="json", HTTP_IF_MATCH="bogus").status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.patch(detail, {"logical_width": 110, "expected_revision": 1}, format="json").status_code,
            status.HTTP_200_OK,
        )
        location_map.refresh_from_db()
        self.assertEqual(location_map.revision, 2)
        response = self.client.patch(detail, {"logical_width": 120}, format="json", HTTP_IF_MATCH='"2"')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        location_map.refresh_from_db()
        self.assertEqual(location_map.revision, 3)
        self.assertEqual(
            self.client.put(
                snapshot, {"location_placements": [], "rack_placements": []}, format="json", HTTP_IF_MATCH='"1"'
            ).status_code,
            status.HTTP_409_CONFLICT,
        )
        response = self.client.put(
            snapshot, {"location_placements": [], "rack_placements": [], "expected_revision": 3}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        location_map.refresh_from_db()
        self.assertEqual(location_map.revision, 4)
        self.assertEqual(self.client.delete(detail, HTTP_IF_MATCH='"2"').status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(self.client.delete(detail, HTTP_IF_MATCH='"4"').status_code, status.HTTP_204_NO_CONTENT)

    def test_bulk_is_405_and_single_placement_mutations_work(self):
        self.login()
        location_map = LocationMap.objects.create(location=self.root, logical_width=100, logical_height=100)
        placement = LocationPlacement.objects.create(location_map=location_map, location=self.child, geometry=RECT)
        map_list = api_reverse("locationmap-list")
        placement_list = api_reverse("locationplacement-list")
        placement_detail = api_reverse("locationplacement-detail", {"pk": placement.pk})
        self.assertEqual(self.client.put(map_list, [], format="json").status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.patch(map_list, [], format="json").status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.delete(map_list).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            self.client.post(placement_list, [], format="json").status_code, status.HTTP_405_METHOD_NOT_ALLOWED
        )
        self.assertEqual(
            self.client.patch(placement_list, [], format="json").status_code, status.HTTP_405_METHOD_NOT_ALLOWED
        )
        self.assertEqual(self.client.delete(placement_list).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            self.client.patch(placement_detail, {"geometry": RECT}, format="json", HTTP_IF_MATCH='"1"').status_code,
            status.HTTP_200_OK,
        )
        location_map.refresh_from_db()
        self.assertEqual(
            self.client.delete(placement_detail, HTTP_IF_MATCH=str(location_map.revision)).status_code,
            status.HTTP_204_NO_CONTENT,
        )

    def test_background_upload(self):
        self.login()
        location_map = LocationMap.objects.create(location=self.root, logical_width=100, logical_height=100)
        background_url = api_reverse("locationmap-background", {"pk": location_map.pk})
        self.assertEqual(self.client.get(background_url).status_code, status.HTTP_400_BAD_REQUEST)
        png = SimpleUploadedFile(
            "floor.png",
            PNG_1X1,
            content_type="image/png",
        )
        response = self.client.put(background_url, {"background": png}, format="multipart", HTTP_IF_MATCH='"1"')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        location_map.refresh_from_db()
        self.assertEqual(location_map.revision, 2)
        self.assertEqual(self.client.get(background_url).status_code, status.HTTP_200_OK)

    def test_anonymous_and_unprivileged_requests_do_not_leak_records(self):
        location_map = LocationMap.objects.create(location=self.root, logical_width=100, logical_height=100)
        list_url = api_reverse("locationmap-list")
        detail_url = api_reverse("locationmap-detail", {"pk": location_map.pk})
        snapshot_url = api_reverse("locationmap-snapshot", {"pk": location_map.pk})
        resolver_url = api_reverse("location-resolved-map", {"location_id": self.root.pk})
        for url in (list_url, detail_url, snapshot_url, resolver_url):
            with self.subTest(url=url):
                self.assertIn(
                    self.client.get(url).status_code, {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}
                )
        unprivileged = get_user_model().objects.create_user(username="api-unprivileged")
        self.client.force_authenticate(unprivileged)
        for url in (list_url, detail_url, snapshot_url, resolver_url):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)

    def test_authorized_resolver_and_related_permission_restriction(self):
        self.login()
        root_map = LocationMap.objects.create(location=self.root, logical_width=100, logical_height=100)
        LocationPlacement.objects.create(location_map=root_map, location=self.child, geometry=RECT)
        response = self.client.get(api_reverse("location-resolved-map", {"location_id": self.child.pk}))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(str(response.data["map"]["id"]), str(root_map.pk))
        self.assertEqual(response.data["map"]["owner_location"]["id"], str(self.root.pk))
        self.assertTrue(response.data["inherited"])
        self.assertEqual(response.data["focus"]["location"]["id"], str(self.child.pk))
        self.assertEqual(response.data["focus"]["geometry"], RECT)

        constrained = get_user_model().objects.create_user(username="api-constrained")
        location_permission = ObjectPermission.objects.create(
            name="View only root location", actions=["view"], constraints={"pk": str(self.root.pk)}
        )
        location_permission.object_types.add(ContentType.objects.get_for_model(Location))
        location_permission.users.add(constrained)
        map_permission = ObjectPermission.objects.create(
            name="View only root map", actions=["view"], constraints={"location": str(self.root.pk)}
        )
        map_permission.object_types.add(ContentType.objects.get_for_model(LocationMap))
        map_permission.users.add(constrained)
        self.client.force_authenticate(constrained)
        # Constrained object permissions exclude the requested child Location: no disclosure or mutation.
        self.assertEqual(
            self.client.get(api_reverse("location-resolved-map", {"location_id": self.child.pk})).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.put(
                api_reverse("locationmap-snapshot", {"pk": root_map.pk}),
                {"location_placements": [{"location": self.child.pk, "geometry": RECT}], "rack_placements": []},
                format="json",
                HTTP_IF_MATCH='"1"',
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
