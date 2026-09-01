# ruff: noqa: D102,D105,D106
# pylint: disable=arguments-out-of-order,too-many-ancestors
"""Database models for Location Floor Plan."""

from __future__ import annotations

import math
import re
import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from nautobot.apps.models import PrimaryModel
from nautobot.dcim.models import Location, Rack

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
validate_hex_color = RegexValidator(HEX_COLOR_RE, "Enter a valid hex color (e.g. #RRGGBB).")

MAX_LOGICAL_SIZE = 1_000_000
MAX_VERTICES = 256


def _is_descendant(child: Location, parent: Location) -> bool:
    """Return True when child is a strict descendant of parent."""
    if not child.pk or not parent.pk or child.pk == parent.pk:
        return False
    ancestors = child.ancestors(include_self=False)
    return ancestors.filter(pk=parent.pk).exists()


def _validate_number(value: object, *, upper: int | None = None) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValidationError("Geometry coordinates must be finite numbers.")
    if value < 0 or (upper is not None and value > upper):
        raise ValidationError("Geometry coordinates must be within map bounds.")


def validate_geometry_schema(geometry: object, *, width: int | None = None, height: int | None = None) -> None:  # pylint: disable=too-many-branches
    """Validate Phase 2 rectangle/polygon placement geometry."""
    if not isinstance(geometry, dict):
        raise ValidationError("Geometry must be an object.")
    geometry_type = geometry.get("type")
    if geometry_type == "rectangle":
        if set(geometry) != {"type", "x", "y", "width", "height"}:
            raise ValidationError("Rectangle geometry does not allow extra keys.")
        for key in ("x", "y", "width", "height"):
            if key not in geometry:
                raise ValidationError(f"Rectangle geometry requires {key}.")
        _validate_number(geometry["x"], upper=width)
        _validate_number(geometry["y"], upper=height)
        _validate_number(geometry["width"])
        _validate_number(geometry["height"])
        if geometry["width"] <= 0 or geometry["height"] <= 0:
            raise ValidationError("Rectangle dimensions must be positive.")
        if width is not None and geometry["x"] + geometry["width"] > width:
            raise ValidationError("Rectangle exceeds map width.")
        if height is not None and geometry["y"] + geometry["height"] > height:
            raise ValidationError("Rectangle exceeds map height.")
        return
    if geometry_type == "polygon":
        if set(geometry) != {"type", "points"}:
            raise ValidationError("Polygon geometry does not allow extra keys.")
        points = geometry.get("points")
        if not isinstance(points, list) or not 3 <= len(points) <= MAX_VERTICES:
            raise ValidationError("Polygon requires 3 to 256 points.")
        for point in points:
            if not isinstance(point, list | tuple) or len(point) != 2:
                raise ValidationError("Polygon points must be [x, y].")
            _validate_number(point[0], upper=width)
            _validate_number(point[1], upper=height)
        if len({(p[0], p[1]) for p in points}) != len(points):
            raise ValidationError("Polygon points must not repeat.")
        area = 0
        for index, point in enumerate(points):
            next_point = points[(index + 1) % len(points)]
            area += point[0] * next_point[1] - next_point[0] * point[1]
        if area == 0:
            raise ValidationError("Polygon must have non-zero area.")
        if all(
            _collinear(points[index - 1], points[index], points[(index + 1) % len(points)])
            for index in range(len(points))
        ):
            raise ValidationError("Polygon cannot be a collinear ring.")
        for first, a1 in enumerate(points):
            a2 = points[(first + 1) % len(points)]
            for second in range(first + 1, len(points)):
                if abs(first - second) == 1 or {first, second} == {0, len(points) - 1}:
                    continue
                if _segments_intersect(a1, a2, points[second], points[(second + 1) % len(points)]):
                    raise ValidationError("Polygon edges must not self-intersect.")
        return
    raise ValidationError("Geometry type must be rectangle or polygon.")


def _collinear(a, b, c) -> bool:
    return (b[0] - a[0]) * (c[1] - a[1]) == (b[1] - a[1]) * (c[0] - a[0])


def _orientation(a, b, c):
    value = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
    return (value > 0) - (value < 0)


def _segments_intersect(a, b, c, d) -> bool:
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and _on_segment(a, c, b))
        or (o2 == 0 and _on_segment(a, d, b))
        or (o3 == 0 and _on_segment(c, a, d))
        or (o4 == 0 and _on_segment(c, b, d))
    )


def _on_segment(a, b, c) -> bool:
    return min(a[0], c[0]) <= b[0] <= max(a[0], c[0]) and min(a[1], c[1]) <= b[1] <= max(a[1], c[1])


class FloorPlan(PrimaryModel):
    """A floor/map canvas owned by a Nautobot Location."""

    is_saved_view_model = False

    location = models.OneToOneField(Location, on_delete=models.CASCADE, related_name="location_floor_plan_map")
    logical_width = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(MAX_LOGICAL_SIZE)])
    logical_height = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(MAX_LOGICAL_SIZE)])
    background = models.FileField(upload_to="location_floor_plan/backgrounds/", blank=True, null=True)
    revision = models.PositiveBigIntegerField(default=1, editable=False)

    natural_key_field_names = ["location"]

    class Meta:
        ordering = ["location__name"]
        verbose_name = "floor plan"
        verbose_name_plural = "floor plans"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(logical_width__gte=1), name="location_floor_plan_map_width_gte_1"
            ),
            models.CheckConstraint(
                condition=models.Q(logical_height__gte=1), name="location_floor_plan_map_height_gte_1"
            ),
            models.CheckConstraint(
                condition=models.Q(logical_width__lte=MAX_LOGICAL_SIZE), name="location_floor_plan_map_width_lte_max"
            ),
            models.CheckConstraint(
                condition=models.Q(logical_height__lte=MAX_LOGICAL_SIZE), name="location_floor_plan_map_height_lte_max"
            ),
            models.CheckConstraint(condition=models.Q(revision__gte=1), name="location_floor_plan_map_revision_gte_1"),
        ]

    def __str__(self):
        return f"Map for {self.location}"

    def clean(self):
        super().clean()
        if self.present_in_database:
            old = type(self).objects.only("location_id").get(pk=self.pk)
            if old.location_id != self.location_id:
                raise ValidationError({"location": "Map owner is immutable after creation."})


class LocationPlacement(PrimaryModel):
    """Placement of a descendant Location on a FloorPlan."""

    floor_plan = models.ForeignKey(FloorPlan, on_delete=models.CASCADE, related_name="location_placements")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="location_floor_plan_placements")
    geometry = models.JSONField()
    color = models.CharField(
        max_length=7,
        blank=True,
        validators=[validate_hex_color],
        help_text="Optional hex color override (#RRGGBB) for this placement.",
    )

    natural_key_field_names = ["floor_plan", "location"]

    class Meta:
        ordering = ["location__name"]
        verbose_name = "location placement"
        verbose_name_plural = "location placements"
        constraints = [
            models.UniqueConstraint(
                fields=["floor_plan", "location"], name="location_floor_plan_unique_location_placement"
            )
        ]

    def __str__(self):
        return f"{self.location} on {self.floor_plan}"

    def clean(self):
        super().clean()
        if self.present_in_database:
            old = type(self).objects.only("floor_plan_id", "location_id").get(pk=self.pk)
            if old.floor_plan_id != self.floor_plan_id:
                raise ValidationError({"floor_plan": "Placement map is immutable after creation."})
            if old.location_id != self.location_id:
                raise ValidationError({"location": "Placement target is immutable after creation."})
        if self.floor_plan_id and self.location_id and not _is_descendant(self.location, self.floor_plan.location):
            raise ValidationError({"location": "Placed location must be a strict descendant of the map owner."})
        if self.floor_plan_id:
            validate_geometry_schema(
                self.geometry, width=self.floor_plan.logical_width, height=self.floor_plan.logical_height
            )


class RackPlacement(PrimaryModel):
    """Placement of a Rack on a FloorPlan."""

    floor_plan = models.ForeignKey(FloorPlan, on_delete=models.CASCADE, related_name="rack_placements")
    rack = models.ForeignKey(Rack, on_delete=models.CASCADE, related_name="location_floor_plan_placements")
    x = models.PositiveIntegerField()
    y = models.PositiveIntegerField()
    width = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    height = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    color = models.CharField(
        max_length=7,
        blank=True,
        validators=[validate_hex_color],
        help_text="Optional hex color override (#RRGGBB) for this placement.",
    )

    natural_key_field_names = ["floor_plan", "rack"]

    class Meta:
        ordering = ["rack__name"]
        verbose_name = "rack placement"
        verbose_name_plural = "rack placements"
        constraints = [
            models.UniqueConstraint(fields=["floor_plan", "rack"], name="location_floor_plan_unique_rack_placement"),
            models.CheckConstraint(condition=models.Q(width__gte=1), name="location_floor_plan_rack_width_gte_1"),
            models.CheckConstraint(condition=models.Q(height__gte=1), name="location_floor_plan_rack_height_gte_1"),
        ]

    def __str__(self):
        return f"{self.rack} on {self.floor_plan}"

    def clean(self):
        super().clean()
        if self.present_in_database:
            old = type(self).objects.only("floor_plan_id", "rack_id").get(pk=self.pk)
            if old.floor_plan_id != self.floor_plan_id:
                raise ValidationError({"floor_plan": "Placement map is immutable after creation."})
            if old.rack_id != self.rack_id:
                raise ValidationError({"rack": "Placement target is immutable after creation."})
        if (
            self.floor_plan_id
            and self.rack_id
            and self.rack.location_id != self.floor_plan.location_id
            and not _is_descendant(self.rack.location, self.floor_plan.location)
        ):
            raise ValidationError({"rack": "Placed rack must belong to the map owner or one of its descendants."})
        if self.floor_plan_id:
            if (
                self.x + self.width > self.floor_plan.logical_width
                or self.y + self.height > self.floor_plan.logical_height
            ):
                raise ValidationError("Rack placement rectangle exceeds map bounds.")


class LocationStyle(models.Model):
    """Persistent color style for a Location target."""

    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, unique=True)
    location = models.OneToOneField(Location, on_delete=models.CASCADE, related_name="location_floor_plan_style")
    color = models.CharField(
        max_length=7,
        blank=True,
        validators=[validate_hex_color],
        help_text="Default hex color (#RRGGBB) for placements of this location.",
    )

    class Meta:
        verbose_name = "location style"
        verbose_name_plural = "location styles"

    def __str__(self):
        return f"Style for {self.location}"


class RackStyle(models.Model):
    """Persistent color style for a Rack target."""

    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, unique=True)
    rack = models.OneToOneField(Rack, on_delete=models.CASCADE, related_name="location_floor_plan_style")
    color = models.CharField(
        max_length=7,
        blank=True,
        validators=[validate_hex_color],
        help_text="Default hex color (#RRGGBB) for placements of this rack.",
    )

    class Meta:
        verbose_name = "rack style"
        verbose_name_plural = "rack styles"

    def __str__(self):
        return f"Style for {self.rack}"
