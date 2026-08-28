"""Floor plan model, resolver, and service contract tests."""
# pylint: disable=missing-function-docstring,missing-class-docstring,too-many-locals

import threading
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from PIL import Image
from nautobot.dcim.factory import LocationFactory, LocationTypeFactory, RackFactory
from nautobot.dcim.models import Location, Rack
from nautobot.extras.models import Status
from nautobot.users.models import ObjectPermission

from location_floor_plan.models import FloorPlan, LocationPlacement, RackPlacement
from location_floor_plan.services import (
    RevisionConflict,
    available_descendants,
    create_floor_plan,
    get_visible_snapshot,
    replace_background,
    replace_snapshot,
    resolve_floor_plan,
    update_floor_plan,
)

RECT = {"type": "rectangle", "x": 1, "y": 1, "width": 10, "height": 10}


def make_location_status():
    status_obj, _ = Status.objects.get_or_create(name="Active", defaults={"color": "4caf50"})
    status_obj.content_types.add(ContentType.objects.get_for_model(Location), ContentType.objects.get_for_model(Rack))
    return status_obj


class FloorPlanModelTestCase(TestCase):
    """Model constraints and validation."""

    def setUp(self):
        status_obj = make_location_status()
        self.location_type = LocationTypeFactory(nestable=True, parent=None)
        self.location_type.content_types.add(ContentType.objects.get_for_model(Rack))
        self.root = LocationFactory(location_type=self.location_type, parent=None, status=status_obj)
        self.child = LocationFactory(location_type=self.location_type, parent=self.root, status=status_obj)
        self.grandchild = LocationFactory(location_type=self.location_type, parent=self.child, status=status_obj)
        self.other = LocationFactory(location_type=self.location_type, parent=None, status=status_obj)

    def test_location_placement_requires_strict_descendant(self):
        floor_plan = FloorPlan.objects.create(location=self.root, logical_width=100, logical_height=100)
        placement = LocationPlacement(floor_plan=floor_plan, location=self.root, geometry=RECT)
        with self.assertRaises(ValidationError):
            placement.full_clean()
        placement.location = self.child
        placement.full_clean()

    def test_exact_uniqueness_per_map_allows_same_target_on_different_maps(self):
        root_map = FloorPlan.objects.create(location=self.root, logical_width=100, logical_height=100)
        child_map = FloorPlan.objects.create(location=self.child, logical_width=100, logical_height=100)
        LocationPlacement.objects.create(floor_plan=root_map, location=self.grandchild, geometry=RECT)
        LocationPlacement.objects.create(floor_plan=child_map, location=self.grandchild, geometry=RECT)
        duplicate = LocationPlacement(floor_plan=root_map, location=self.grandchild, geometry=RECT)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_one_map_per_location(self):
        FloorPlan.objects.create(location=self.root, logical_width=100, logical_height=100)
        duplicate = FloorPlan(location=self.root, logical_width=100, logical_height=100)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_rack_placement_requires_owner_or_descendant_location(self):
        floor_plan = FloorPlan.objects.create(location=self.root, logical_width=100, logical_height=100)
        owner_rack = RackFactory(location=self.root, status=self.root.status)
        child_rack = RackFactory(location=self.child, status=self.root.status)
        RackPlacement(floor_plan=floor_plan, rack=owner_rack, x=1, y=1, width=10, height=10).full_clean()
        RackPlacement(floor_plan=floor_plan, rack=child_rack, x=1, y=1, width=10, height=10).full_clean()
        outside_rack = RackFactory(location=self.other, status=self.root.status)
        placement = RackPlacement(floor_plan=floor_plan, rack=outside_rack, x=1, y=1, width=10, height=10)
        with self.assertRaises(ValidationError):
            placement.full_clean()

    def test_geometry_polygon_validation_cases(self):
        floor_plan = FloorPlan.objects.create(location=self.root, logical_width=100, logical_height=100)
        valid = {"type": "polygon", "points": [[0, 0], [10, 0], [10, 10], [0, 10]]}
        LocationPlacement(floor_plan=floor_plan, location=self.child, geometry=valid).full_clean()
        invalid_geometries = [
            {"type": "polygon", "points": [[0, 0], [0, 0], [1, 1]]},
            {"type": "polygon", "points": [[0, 0], [1, 1], [2, 2]]},
            {"type": "polygon", "points": [[0, 0], [10, 10], [0, 10], [10, 0]]},
            {"type": "polygon", "points": [[0, 0], [10, 0], [5, 0], [5, 10]]},
            {"type": "polygon", "points": [[0, 0], [10, 0], [10, 10], [5, 0], [0, 10]]},
            {"type": "polygon", "points": [[0, 0], [101, 0], [0, 1]]},
            {"type": "polygon", "points": [[0, 0], [1, 0], [0, 1]], "extra": True},
            {"type": "rectangle", "x": 0, "y": 0, "width": 0, "height": 1},
        ]
        for geometry in invalid_geometries:
            with self.subTest(geometry=geometry), self.assertRaises(ValidationError):
                LocationPlacement(floor_plan=floor_plan, location=self.child, geometry=geometry).full_clean()

    def test_map_max_constraints_are_validated(self):
        too_large = FloorPlan(location=self.root, logical_width=1_000_001, logical_height=100)
        with self.assertRaises(ValidationError):
            too_large.full_clean()


class FloorPlanResolverTestCase(TestCase):
    """Resolver inheritance behavior."""

    def setUp(self):
        location_type = LocationTypeFactory(nestable=True, parent=None)
        status_obj = make_location_status()
        self.l1 = LocationFactory(location_type=location_type, parent=None, status=status_obj)
        self.l2 = LocationFactory(location_type=location_type, parent=self.l1, status=status_obj)
        self.l3 = LocationFactory(location_type=location_type, parent=self.l2, status=status_obj)
        self.l4 = LocationFactory(location_type=location_type, parent=self.l3, status=status_obj)

    def test_own_map_wins(self):
        own = FloorPlan.objects.create(location=self.l4, logical_width=100, logical_height=100)
        parent = FloorPlan.objects.create(location=self.l3, logical_width=100, logical_height=100)
        LocationPlacement.objects.create(floor_plan=parent, location=self.l4, geometry=RECT)
        result = resolve_floor_plan(self.l4)
        self.assertEqual(result.floor_plan, own)
        self.assertEqual(result.source, "own")

    def test_mandatory_inheritance_cases_and_stale_skip(self):
        l1_map = FloorPlan.objects.create(location=self.l1, logical_width=100, logical_height=100)
        l2_map = FloorPlan.objects.create(location=self.l2, logical_width=100, logical_height=100)
        FloorPlan.objects.create(location=self.l3, logical_width=100, logical_height=100)
        LocationPlacement.objects.create(floor_plan=l1_map, location=self.l4, geometry=RECT)
        LocationPlacement.objects.create(floor_plan=l2_map, location=self.l4, geometry=RECT)
        self.assertEqual(resolve_floor_plan(self.l4).floor_plan, l2_map)
        self.l4.parent = self.l1
        self.l4.validated_save()
        self.assertEqual(resolve_floor_plan(self.l4).floor_plan, l1_map)

    def test_nearest_ancestor_with_exact_placement_skips_intermediate_map(self):
        distant = FloorPlan.objects.create(location=self.l1, logical_width=100, logical_height=100)
        FloorPlan.objects.create(location=self.l3, logical_width=100, logical_height=100)
        LocationPlacement.objects.create(floor_plan=distant, location=self.l4, geometry=RECT)
        result = resolve_floor_plan(self.l4)
        self.assertEqual(result.floor_plan, distant)
        self.assertEqual(result.source, "ancestor")

    def test_no_implicit_focus(self):
        FloorPlan.objects.create(location=self.l1, logical_width=100, logical_height=100)
        result = resolve_floor_plan(self.l4)
        self.assertIsNone(result.floor_plan)
        self.assertEqual(result.source, "none")

    def test_direct_l1_to_l4_and_constant_query_count(self):
        floor_plan = FloorPlan.objects.create(location=self.l1, logical_width=100, logical_height=100)
        LocationPlacement.objects.create(floor_plan=floor_plan, location=self.l4, geometry=RECT)
        self.l4.refresh_from_db()
        self.l2.refresh_from_db()
        with self.assertNumQueries(5):
            self.assertEqual(resolve_floor_plan(self.l4).floor_plan, floor_plan)
        with self.assertNumQueries(5):
            self.assertEqual(resolve_floor_plan(self.l2).source, "none")


class FloorPlanMutationServiceTestCase(TestCase):
    """Revision and permission basics."""

    def setUp(self):
        location_type = LocationTypeFactory(nestable=True, parent=None)
        self.location = LocationFactory(location_type=location_type, parent=None, status=make_location_status())
        self.user = get_user_model().objects.create_user(username="phase2")

    def _superuser(self):
        return get_user_model().objects.create_superuser(username="phase2-root")

    def test_permission_is_enforced(self):
        with self.assertRaises(PermissionDenied):
            create_floor_plan(
                user=self.user,
                location=self.location,
                logical_width=100,
                logical_height=100,
                expected_revision=0,
            )

    def test_revision_conflict_rolls_back(self):
        floor_plan = FloorPlan.objects.create(location=self.location, logical_width=100, logical_height=100)
        self.user.is_superuser = True
        self.user.save()
        with self.assertRaises(ValidationError):
            update_floor_plan(user=self.user, floor_plan=floor_plan, expected_revision=99, logical_width=200)
        floor_plan.refresh_from_db()
        self.assertEqual(floor_plan.revision, 1)
        self.assertEqual(floor_plan.logical_width, 100)

    def test_snapshot_stale_retained_explicit_delete_duplicate_replace_rollback_and_revision(self):
        user = self._superuser()
        child = LocationFactory(
            location_type=self.location.location_type, parent=self.location, status=self.location.status
        )
        other = LocationFactory(location_type=self.location.location_type, parent=None, status=self.location.status)
        floor_plan = FloorPlan.objects.create(location=self.location, logical_width=100, logical_height=100)
        stale = LocationPlacement.objects.create(floor_plan=floor_plan, location=child, geometry=RECT)
        child.parent = other
        child.validated_save()
        snapshot = get_visible_snapshot(user=user, floor_plan=floor_plan)
        self.assertEqual(snapshot["location_placements"], [])
        self.assertEqual(snapshot["stale_location_placements"], [stale])
        replace_snapshot(
            user=user, floor_plan=floor_plan, expected_revision=1, location_placements=[], rack_placements=[]
        )
        self.assertTrue(LocationPlacement.objects.filter(pk=stale.pk).exists())
        floor_plan.refresh_from_db()
        self.assertEqual(floor_plan.revision, 2)
        with self.assertRaises(RevisionConflict):
            replace_snapshot(
                user=user, floor_plan=floor_plan, expected_revision=1, location_placements=[], rack_placements=[]
            )
        replace_snapshot(
            user=user,
            floor_plan=floor_plan,
            expected_revision=2,
            location_placements=[],
            rack_placements=[],
            delete_stale_ids=[stale.pk],
        )
        self.assertFalse(LocationPlacement.objects.filter(pk=stale.pk).exists())
        floor_plan.refresh_from_db()
        child.parent = self.location
        child.validated_save()
        with self.assertRaises(ValidationError):
            replace_snapshot(
                user=user,
                floor_plan=floor_plan,
                expected_revision=3,
                location_placements=[{"location": child, "geometry": RECT}, {"location": child, "geometry": RECT}],
                rack_placements=[],
            )
        before = floor_plan.revision
        with self.assertRaises(ValidationError):
            replace_snapshot(
                user=user,
                floor_plan=floor_plan,
                expected_revision=before,
                location_placements=[
                    {"location": child, "geometry": {"type": "rectangle", "x": 99, "y": 0, "width": 2, "height": 1}}
                ],
                rack_placements=[],
            )
        floor_plan.refresh_from_db()
        self.assertEqual(floor_plan.revision, before)
        replace_snapshot(
            user=user,
            floor_plan=floor_plan,
            expected_revision=before,
            location_placements=[{"location": child, "geometry": RECT}],
            rack_placements=[],
        )
        floor_plan.refresh_from_db()
        self.assertEqual(floor_plan.revision, before + 1)

    def test_shrink_rejection(self):
        user = self._superuser()
        child = LocationFactory(
            location_type=self.location.location_type, parent=self.location, status=self.location.status
        )
        floor_plan = FloorPlan.objects.create(location=self.location, logical_width=100, logical_height=100)
        LocationPlacement.objects.create(
            floor_plan=floor_plan,
            location=child,
            geometry={"type": "rectangle", "x": 90, "y": 1, "width": 10, "height": 10},
        )
        with self.assertRaises(ValidationError):
            update_floor_plan(user=user, floor_plan=floor_plan, expected_revision=1, logical_width=95)

    def test_available_descendants_filters_tree_placements_racks_and_permissions(self):
        user = self._superuser()
        child = LocationFactory(
            location_type=self.location.location_type, parent=self.location, status=self.location.status
        )
        placed_child = LocationFactory(
            location_type=self.location.location_type, parent=self.location, status=self.location.status
        )
        outside = LocationFactory(location_type=self.location.location_type, parent=None, status=self.location.status)
        floor_plan = FloorPlan.objects.create(location=self.location, logical_width=100, logical_height=100)
        LocationPlacement.objects.create(
            floor_plan=floor_plan,
            location=placed_child,
            geometry=RECT,
        )
        owner_rack = RackFactory(location=self.location, status=self.location.status)
        child_rack = RackFactory(location=child, status=self.location.status)
        placed_rack = RackFactory(location=child, status=self.location.status)
        outside_rack = RackFactory(location=outside, status=self.location.status)
        RackPlacement.objects.create(
            floor_plan=floor_plan,
            rack=placed_rack,
            x=1,
            y=1,
            width=10,
            height=10,
        )

        locations, racks = available_descendants(floor_plan, user=user)
        self.assertIn(child, locations)
        self.assertNotIn(self.location, locations)
        self.assertNotIn(placed_child, locations)
        self.assertNotIn(outside, locations)
        self.assertIn(owner_rack, racks)
        self.assertIn(child_rack, racks)
        self.assertNotIn(placed_rack, racks)
        self.assertNotIn(outside_rack, racks)

        constrained = get_user_model().objects.create_user(username="available-constrained")
        location_permission = ObjectPermission.objects.create(
            name="View available child",
            actions=["view"],
            constraints={"pk": str(child.pk)},
        )
        location_permission.object_types.add(ContentType.objects.get_for_model(Location))
        location_permission.users.add(constrained)
        rack_permission = ObjectPermission.objects.create(
            name="View available child rack",
            actions=["view"],
            constraints={"pk": str(child_rack.pk)},
        )
        rack_permission.object_types.add(ContentType.objects.get_for_model(Rack))
        rack_permission.users.add(constrained)
        restricted_locations, restricted_racks = available_descendants(floor_plan, user=constrained)
        self.assertEqual(list(restricted_locations), [child])
        self.assertEqual(list(restricted_racks), [child_rack])


class Phase2ConcurrencyTestCase(TransactionTestCase):
    reset_sequences = True

    def test_two_writes_from_same_revision_cannot_both_succeed(self):
        location_type = LocationTypeFactory(nestable=True, parent=None)
        location = LocationFactory(location_type=location_type, parent=None, status=make_location_status())
        user = get_user_model().objects.create_superuser(username="concurrency-root")
        floor_plan = FloorPlan.objects.create(location=location, logical_width=100, logical_height=100)
        barrier = threading.Barrier(2)
        results = []

        def worker(width):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                update_floor_plan(user=user, floor_plan=floor_plan, expected_revision=1, logical_width=width)
                results.append("ok")
            except RevisionConflict:
                results.append("conflict")
            finally:
                close_old_connections()

        threads = [threading.Thread(target=worker, args=(200,)), threading.Thread(target=worker, args=(300,))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertCountEqual(results, ["ok", "conflict"])
        floor_plan.refresh_from_db()
        self.assertEqual(floor_plan.revision, 2)
        self.assertIn(floor_plan.logical_width, {200, 300})


class ReplaceBackgroundServiceTestCase(TestCase):
    """Background replacement rescales map dimensions and placements."""

    def setUp(self):
        location_type = LocationTypeFactory(nestable=True, parent=None)
        self.location = LocationFactory(location_type=location_type, parent=None, status=make_location_status())
        self.child = LocationFactory(location_type=location_type, parent=self.location, status=self.location.status)
        self.rack = RackFactory(location=self.location, status=self.location.status)
        self.user = get_user_model().objects.create_superuser(username="replace-bg-root")

    def _png_upload(self, width, height):
        image = Image.new("RGBA", (width, height), (255, 255, 255, 255))
        out = BytesIO()
        image.save(out, format="PNG")
        return SimpleUploadedFile("bg.png", out.getvalue(), content_type="image/png")

    def test_replace_background_scales_rectangles_racks_non_uniformly(self):
        floor_plan = FloorPlan.objects.create(location=self.location, logical_width=100, logical_height=100)
        loc = LocationPlacement.objects.create(
            floor_plan=floor_plan,
            location=self.child,
            geometry={"type": "rectangle", "x": 10, "y": 20, "width": 30, "height": 40},
        )
        rack = RackPlacement.objects.create(floor_plan=floor_plan, rack=self.rack, x=5, y=6, width=20, height=30)

        replace_background(
            user=self.user,
            floor_plan=floor_plan,
            expected_revision=1,
            upload=self._png_upload(200, 50),
        )

        floor_plan.refresh_from_db()
        self.assertEqual(floor_plan.logical_width, 200)
        self.assertEqual(floor_plan.logical_height, 50)
        self.assertEqual(floor_plan.revision, 2)

        loc.refresh_from_db()
        self.assertEqual(
            loc.geometry,
            {"type": "rectangle", "x": 20, "y": 10, "width": 60, "height": 20},
        )

        rack.refresh_from_db()
        self.assertEqual(rack.x, 10)
        self.assertEqual(rack.y, 3)
        self.assertEqual(rack.width, 40)
        self.assertEqual(rack.height, 15)
        self.assertLessEqual(rack.x + rack.width, floor_plan.logical_width)
        self.assertLessEqual(rack.y + rack.height, floor_plan.logical_height)

    def test_replace_background_scales_polygon_and_clamps_to_bounds(self):
        floor_plan = FloorPlan.objects.create(location=self.location, logical_width=100, logical_height=100)
        LocationPlacement.objects.create(
            floor_plan=floor_plan,
            location=self.child,
            geometry={"type": "polygon", "points": [[0, 0], [50, 0], [50, 50], [0, 50]]},
        )
        rack = RackPlacement.objects.create(floor_plan=floor_plan, rack=self.rack, x=90, y=90, width=10, height=10)

        replace_background(
            user=self.user,
            floor_plan=floor_plan,
            expected_revision=1,
            upload=self._png_upload(50, 30),
        )

        floor_plan.refresh_from_db()
        self.assertEqual(floor_plan.logical_width, 50)
        self.assertEqual(floor_plan.logical_height, 30)

        loc = LocationPlacement.objects.get(floor_plan=floor_plan, location=self.child)
        self.assertEqual(loc.geometry["type"], "polygon")
        self.assertEqual(loc.geometry["points"], [[0, 0], [25, 0], [25, 15], [0, 15]])

        rack.refresh_from_db()
        self.assertLessEqual(rack.x + rack.width, floor_plan.logical_width)
        self.assertLessEqual(rack.y + rack.height, floor_plan.logical_height)

    def test_replace_background_clamps_rack_when_shrinking_below_bounds(self):
        floor_plan = FloorPlan.objects.create(location=self.location, logical_width=100, logical_height=100)
        rack = RackPlacement.objects.create(floor_plan=floor_plan, rack=self.rack, x=95, y=95, width=5, height=5)

        replace_background(
            user=self.user,
            floor_plan=floor_plan,
            expected_revision=1,
            upload=self._png_upload(10, 10),
        )

        floor_plan.refresh_from_db()
        self.assertEqual(floor_plan.logical_width, 10)
        self.assertEqual(floor_plan.logical_height, 10)

        rack.refresh_from_db()
        self.assertGreaterEqual(rack.width, 1)
        self.assertGreaterEqual(rack.height, 1)
        self.assertLessEqual(rack.x + rack.width, floor_plan.logical_width)
        self.assertLessEqual(rack.y + rack.height, floor_plan.logical_height)

    def test_replace_background_revision_conflict_rolls_back(self):
        floor_plan = FloorPlan.objects.create(location=self.location, logical_width=100, logical_height=100)
        LocationPlacement.objects.create(floor_plan=floor_plan, location=self.child, geometry=RECT)
        RackPlacement.objects.create(floor_plan=floor_plan, rack=self.rack, x=1, y=1, width=10, height=10)

        with self.assertRaises(RevisionConflict):
            replace_background(
                user=self.user,
                floor_plan=floor_plan,
                expected_revision=99,
                upload=self._png_upload(200, 200),
            )

        floor_plan.refresh_from_db()
        self.assertEqual(floor_plan.logical_width, 100)
        self.assertEqual(floor_plan.logical_height, 100)
        self.assertEqual(floor_plan.revision, 1)
        self.assertEqual(LocationPlacement.objects.filter(floor_plan=floor_plan).count(), 1)
        self.assertEqual(RackPlacement.objects.filter(floor_plan=floor_plan).count(), 1)
