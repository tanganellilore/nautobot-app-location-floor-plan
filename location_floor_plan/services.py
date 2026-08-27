# ruff: noqa: D103
# pylint: disable=missing-function-docstring,too-many-arguments,too-many-boolean-expressions
"""Transactional backend services for Location Floor Plan."""

from dataclasses import dataclass
from io import BytesIO
from uuid import uuid4

from defusedxml import ElementTree
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.urls import reverse
from nautobot.dcim.models import Device, Location, Rack
from PIL import Image, UnidentifiedImageError

from location_floor_plan.models import FloorPlan, LocationPlacement, RackPlacement, _is_descendant

SAFE_SVG_ELEMENTS = {
    "svg",
    "g",
    "path",
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "defs",
    "title",
    "desc",
}
SAFE_SVG_ATTR_PREFIXES = (
    "d",
    "x",
    "y",
    "x1",
    "y1",
    "x2",
    "y2",
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "width",
    "height",
    "viewBox",
    "fill",
    "stroke",
    "stroke-width",
    "points",
    "transform",
    "opacity",
    "xmlns",
)


class RevisionConflict(ValidationError):
    """Raised when a caller supplies a stale revision."""


@dataclass(frozen=True)
class ResolvedMap:
    """Result returned by the map resolver."""

    requested_location: Location
    floor_plan: FloorPlan | None
    qualifier: LocationPlacement | None
    source: str


def resolve_floor_plan(location: Location, *, user=None) -> ResolvedMap:
    """Resolve the map that should render for location without implicit focus."""
    location = Location.objects.with_tree_fields().get(pk=location.pk)
    own = FloorPlan.objects.filter(location=location).select_related("location").first()
    if own and _can(user, "location_floor_plan.view_floorplan", own) and _can(user, "dcim.view_location", own.location):
        return ResolvedMap(location, own, None, "own")

    ancestors = list(location.ancestors(include_self=False).values_list("pk", flat=True))
    ancestor_ids = list(reversed(ancestors))
    maps = {
        m.location_id: m for m in FloorPlan.objects.filter(location_id__in=ancestor_ids).select_related("location")
    }
    placements = {}
    for placement in LocationPlacement.objects.filter(
        location=location, floor_plan__location_id__in=ancestor_ids
    ).select_related("floor_plan__location", "location"):
        placements[placement.floor_plan_id] = placement
    for ancestor_id in ancestor_ids:
        candidate = maps.get(ancestor_id)
        if (
            candidate
            and candidate.pk in placements
            and _can(user, "location_floor_plan.view_floorplan", candidate)
            and _can(user, "location_floor_plan.view_locationplacement", placements[candidate.pk])
            and _can(user, "dcim.view_location", candidate.location)
            and _can(user, "dcim.view_location", placements[candidate.pk].location)
        ):
            return ResolvedMap(location, candidate, placements[candidate.pk], "ancestor")
    return ResolvedMap(location, None, None, "none")


def _check(user, permission: str, obj=None) -> None:
    if user is not None and not user.has_perm(permission, obj):
        raise PermissionDenied(f"Missing permission {permission}.")


def _can(user, permission: str, obj=None) -> bool:
    return user is None or user.has_perm(permission, obj)


def _setting(name, default):
    return settings.PLUGINS_CONFIG.get("location_floor_plan", {}).get(name, default)


def _assert_revision(floor_plan: FloorPlan | None, expected_revision: int) -> None:
    if floor_plan is None:
        if expected_revision != 0:
            raise ValidationError("Creation requires expected revision 0.")
    elif floor_plan.revision != expected_revision:
        raise RevisionConflict("Revision conflict.")


def _check_snapshot_view(user, floor_plan: FloorPlan) -> None:
    _check(user, "location_floor_plan.view_floorplan", floor_plan)
    _check(user, "dcim.view_location", floor_plan.location)
    for placement in floor_plan.location_placements.select_related("location"):
        _check(user, "location_floor_plan.view_locationplacement", placement)
        _check(user, "dcim.view_location", placement.location)
    for placement in floor_plan.rack_placements.select_related("rack"):
        _check(user, "location_floor_plan.view_rackplacement", placement)
        _check(user, "dcim.view_rack", placement.rack)


def _assert_restricted(user, action: str, obj) -> None:
    if user is None or getattr(user, "is_superuser", False):
        return
    if not type(obj).objects.restrict(user, action).filter(pk=obj.pk).exists():
        raise PermissionDenied(f"Object is outside constrained {action} permission.")


def _materialize_snapshot(user, floor_plan: FloorPlan) -> dict:
    _check(user, "location_floor_plan.view_floorplan", floor_plan)
    _check(user, "dcim.view_location", floor_plan.location)
    location_items = list(floor_plan.location_placements.select_related("location", "floor_plan__location"))
    rack_items = list(floor_plan.rack_placements.select_related("rack", "rack__location", "floor_plan__location"))
    for placement in location_items:
        _check(user, "location_floor_plan.view_locationplacement", placement)
        _check(user, "dcim.view_location", placement.location)
    for placement in rack_items:
        _check(user, "location_floor_plan.view_rackplacement", placement)
        _check(user, "dcim.view_rack", placement.rack)
    return _split_snapshot(floor_plan, location_items, rack_items)


def _split_snapshot(floor_plan, location_items, rack_items):
    valid_locations = []
    stale_locations = []
    valid_racks = []
    stale_racks = []
    for placement in location_items:
        (valid_locations if _is_descendant(placement.location, floor_plan.location) else stale_locations).append(
            placement
        )
    for placement in rack_items:
        valid = placement.rack.location_id == floor_plan.location_id or _is_descendant(
            placement.rack.location, floor_plan.location
        )
        (valid_racks if valid else stale_racks).append(placement)
    return {
        "map": floor_plan,
        "location_placements": valid_locations,
        "rack_placements": valid_racks,
        "stale_location_placements": stale_locations,
        "stale_rack_placements": stale_racks,
    }


@transaction.atomic
def create_floor_plan(
    *, user, location, logical_width, logical_height, expected_revision: int, background=None
) -> FloorPlan:
    """Create a map while locking its owner Location."""
    _check(user, "location_floor_plan.add_floorplan")
    _check(user, "dcim.view_location", location)
    Location.objects.select_for_update().get(pk=location.pk)
    _assert_revision(None, expected_revision)
    obj = FloorPlan(
        location=location, logical_width=logical_width, logical_height=logical_height, background=background
    )
    obj.full_clean()
    obj.save()
    _assert_restricted(user, "add", obj)
    return obj


@transaction.atomic
def update_floor_plan(*, user, floor_plan, expected_revision: int, **changes) -> FloorPlan:
    """Update mutable map fields and increment revision exactly once."""
    _check(user, "location_floor_plan.change_floorplan", floor_plan)
    obj = FloorPlan.objects.select_for_update().get(pk=floor_plan.pk)
    _assert_revision(obj, expected_revision)
    retained_location_placements = list(obj.location_placements.select_related("location"))
    retained_rack_placements = list(obj.rack_placements.select_related("rack"))
    for field in ("logical_width", "logical_height"):
        if field in changes:
            setattr(obj, field, changes[field])
    obj.revision += 1
    obj.full_clean()
    for placement in retained_location_placements:
        placement.floor_plan = obj
        placement.full_clean()
    for placement in retained_rack_placements:
        placement.floor_plan = obj
        placement.full_clean()
    obj.save()
    _assert_restricted(user, "change", obj)
    return obj


@transaction.atomic
def delete_floor_plan(*, user, floor_plan, expected_revision: int) -> None:
    """Delete a map with revision guard."""
    _check(user, "location_floor_plan.delete_floorplan", floor_plan)
    obj = FloorPlan.objects.select_for_update().get(pk=floor_plan.pk)
    _assert_revision(obj, expected_revision)
    _assert_restricted(user, "delete", obj)
    obj.delete()


def _bump(parent: FloorPlan) -> None:
    parent.revision += 1
    parent.full_clean()
    parent.save(update_fields=["revision", "last_updated"])


def get_visible_snapshot(*, user, floor_plan: FloorPlan) -> dict:
    """Return a full snapshot only when the user can view all included objects."""
    with transaction.atomic():
        parent = FloorPlan.objects.select_related("location").select_for_update().get(pk=floor_plan.pk)
        return _materialize_snapshot(user, parent)


@transaction.atomic
def replace_snapshot(
    *,
    user,
    floor_plan: FloorPlan,
    expected_revision: int,
    location_placements,
    rack_placements,
    delete_stale_ids=None,
):  # pylint: disable=too-many-arguments,too-many-locals,too-many-branches,too-many-statements
    """Atomically replace all placements on one map and increment revision once."""
    parent = FloorPlan.objects.select_for_update().get(pk=floor_plan.pk)
    _check(user, "location_floor_plan.change_floorplan", parent)
    _assert_revision(parent, expected_revision)

    existing_location_list = list(parent.location_placements.select_related("location").select_for_update())
    existing_rack_list = list(parent.rack_placements.select_related("rack", "rack__location").select_for_update())
    _split = _split_snapshot(parent, existing_location_list, existing_rack_list)
    for placement in existing_location_list:
        _check(user, "location_floor_plan.view_locationplacement", placement)
        _check(user, "dcim.view_location", placement.location)
    for placement in existing_rack_list:
        _check(user, "location_floor_plan.view_rackplacement", placement)
        _check(user, "dcim.view_rack", placement.rack)
    existing_locations = {str(p.location_id): p for p in existing_location_list}
    existing_racks = {str(p.rack_id): p for p in existing_rack_list}
    location_ids = [str(item["location"].pk) for item in location_placements]
    rack_ids = [str(item["rack"].pk) for item in rack_placements]
    if len(location_ids) != len(set(location_ids)) or len(rack_ids) != len(set(rack_ids)):
        raise ValidationError("Snapshot contains duplicate placement targets.")
    wanted_locations = dict(zip(location_ids, location_placements))
    wanted_racks = dict(zip(rack_ids, rack_placements))
    delete_stale_ids = {str(item) for item in (delete_stale_ids or [])}

    for location_id, placement in existing_locations.items():
        stale = not _is_descendant(placement.location, parent.location)
        if location_id not in wanted_locations and (not stale or str(placement.pk) in delete_stale_ids):
            _check(user, "location_floor_plan.delete_locationplacement", placement)
            _assert_restricted(user, "delete", placement)
            placement.delete()
    for rack_id, placement in existing_racks.items():
        stale = placement.rack.location_id != parent.location_id and not _is_descendant(
            placement.rack.location, parent.location
        )
        if rack_id not in wanted_racks and (not stale or str(placement.pk) in delete_stale_ids):
            _check(user, "location_floor_plan.delete_rackplacement", placement)
            _assert_restricted(user, "delete", placement)
            placement.delete()

    for location_id, item in wanted_locations.items():
        _check(user, "dcim.view_location", item["location"])
        if location_id in existing_locations:
            obj = existing_locations[location_id]
            _check(user, "location_floor_plan.change_locationplacement", obj)
            obj.geometry = item["geometry"]
        else:
            _check(user, "location_floor_plan.add_locationplacement")
            obj = LocationPlacement(floor_plan=parent, location=item["location"], geometry=item["geometry"])
        obj.full_clean()
        obj.save()
        _assert_restricted(user, "change" if location_id in existing_locations else "add", obj)

    for rack_id, item in wanted_racks.items():
        _check(user, "dcim.view_rack", item["rack"])
        fields = {k: item[k] for k in ("x", "y", "width", "height")}
        if rack_id in existing_racks:
            obj = existing_racks[rack_id]
            _check(user, "location_floor_plan.change_rackplacement", obj)
            for key, value in fields.items():
                setattr(obj, key, value)
        else:
            _check(user, "location_floor_plan.add_rackplacement")
            obj = RackPlacement(floor_plan=parent, rack=item["rack"], **fields)
        obj.full_clean()
        obj.save()
        _assert_restricted(user, "change" if rack_id in existing_racks else "add", obj)

    _bump(parent)
    _assert_restricted(user, "change", parent)
    return _materialize_snapshot(user, parent)


@transaction.atomic
def mutate_placement(
    *, user, placement_model, action: str, expected_revision: int, instance=None, floor_plan=None, **data
):  # pylint: disable=too-many-arguments
    """Create, update, or delete one placement on exactly one locked map."""
    perm_base = placement_model._meta.model_name
    if action == "create":
        parent = FloorPlan.objects.select_for_update().get(pk=floor_plan.pk)
        _check(user, "location_floor_plan.change_floorplan", parent)
        _check(user, f"location_floor_plan.add_{perm_base}")
        _assert_revision(parent, expected_revision)
        obj = placement_model(floor_plan=parent, **data)
        target = data.get("location") or data.get("rack")
        if target is not None:
            _check(user, f"dcim.view_{target._meta.model_name}", target)
        obj.full_clean()
        obj.save()
        _assert_restricted(user, "add", obj)
        _bump(parent)
        _assert_restricted(user, "change", parent)
        return obj
    parent_id = placement_model.objects.only("floor_plan_id").get(pk=instance.pk).floor_plan_id
    parent = FloorPlan.objects.select_for_update().get(pk=parent_id)
    obj = (
        placement_model.objects.select_related("floor_plan")
        .select_for_update()
        .get(pk=instance.pk, floor_plan=parent)
    )
    _check(user, "location_floor_plan.change_floorplan", parent)
    _check(user, f"location_floor_plan.{action}_{perm_base}", obj)
    _assert_revision(parent, expected_revision)
    if action == "delete":
        _assert_restricted(user, "delete", obj)
        obj.delete()
        _bump(parent)
        _assert_restricted(user, "change", parent)
        return None
    for key, value in data.items():
        setattr(obj, key, value)
    obj.full_clean()
    obj.save()
    _assert_restricted(user, "change", obj)
    _bump(parent)
    _assert_restricted(user, "change", parent)
    return obj


def create_location_placement(**kwargs):
    return mutate_placement(placement_model=LocationPlacement, action="create", **kwargs)


def create_rack_placement(**kwargs):
    return mutate_placement(placement_model=RackPlacement, action="create", **kwargs)


def update_location_placement(**kwargs):
    return mutate_placement(placement_model=LocationPlacement, action="change", **kwargs)


def delete_location_placement(**kwargs):
    return mutate_placement(placement_model=LocationPlacement, action="delete", **kwargs)


def update_rack_placement(**kwargs):
    return mutate_placement(placement_model=RackPlacement, action="change", **kwargs)


def delete_rack_placement(**kwargs):
    return mutate_placement(placement_model=RackPlacement, action="delete", **kwargs)


def rack_usage_for_racks(racks):
    rack_map = {rack.pk: rack for rack in racks}
    intervals = {rack.pk: [] for rack in racks}
    for device in Device.objects.filter(rack_id__in=rack_map).select_related("device_type"):
        u_height = getattr(device.device_type, "u_height", 0) or 0
        position = getattr(device, "position", None) or 0
        if position < 1 or u_height <= 0:
            continue
        total = rack_map[device.rack_id].u_height or 0
        start = max(1, int(position))
        end = min(total, start + int(u_height) - 1)
        if end >= start:
            intervals[device.rack_id].append((start, end))
    return {rack.pk: _rack_usage(rack, intervals[rack.pk]) for rack in racks}


def _rack_usage(rack, intervals):
    total = rack.u_height or 0
    used = len({unit for start, end in intervals for unit in range(start, end + 1)})
    pct = round((used / total) * 100) if total else 0
    low = _setting("rack_utilization_low_threshold", 50)
    med = _setting("rack_utilization_medium_threshold", 80)
    high = _setting("rack_utilization_high_threshold", 95)
    if not 0 < low < med < high <= 100:
        raise ValidationError("Rack utilization thresholds must be low < medium < high <= 100.")
    level = (
        "empty" if pct == 0 else "low" if pct < low else "medium" if pct < med else "high" if pct < high else "critical"
    )
    label = f"{rack}: {used} of {total} rack units used ({pct}%), {level} utilization"
    return {"used_ru": used, "total_ru": total, "percentage": pct, "level": level, "label": label, "aria": label}


def renderer_payload(location, *, user):
    result = resolve_floor_plan(location, user=user)
    if result.floor_plan is None:
        return {
            "requested_location": str(location.pk),
            "map": None,
            "inherited": False,
            "focus": None,
            "locations": [],
            "racks": [],
        }
    snapshot = get_visible_snapshot(user=user, floor_plan=result.floor_plan)
    racks = [p.rack for p in snapshot["rack_placements"]]
    usage = rack_usage_for_racks(racks)
    return {
        "requested_location": {"id": str(location.pk), "name": str(location)},
        "map": {
            "id": str(result.floor_plan.pk),
            "owner_location": {"id": str(result.floor_plan.location_id), "name": str(result.floor_plan.location)},
            "logical_width": result.floor_plan.logical_width,
            "logical_height": result.floor_plan.logical_height,
            "revision": result.floor_plan.revision,
            "background_url": reverse(
                "plugins-api:location_floor_plan-api:floorplan-background", kwargs={"pk": result.floor_plan.pk}
            )
            if result.floor_plan.background
            else None,
        },
        "inherited": result.source == "ancestor",
        "focus": {
            "location": {"id": str(result.qualifier.location_id), "name": str(result.qualifier.location)},
            "geometry": result.qualifier.geometry,
        }
        if result.qualifier
        else None,
        "locations": [
            {
                "id": str(p.pk),
                "location": {"id": str(p.location_id), "name": str(p.location)},
                "geometry": p.geometry,
                "detail_url": p.location.get_absolute_url(),
            }
            for p in snapshot["location_placements"]
            if _can(user, "dcim.view_location", p.location)
        ],
        "racks": [
            {
                "id": str(p.pk),
                "rack": {"id": str(p.rack_id), "name": str(p.rack)},
                "x": p.x,
                "y": p.y,
                "width": p.width,
                "height": p.height,
                "used_ru": usage[p.rack_id]["used_ru"],
                "total_ru": usage[p.rack_id]["total_ru"],
                "usage_percentage": usage[p.rack_id]["percentage"],
                "usage_level": usage[p.rack_id]["level"],
                "label": usage[p.rack_id]["label"],
                "aria_label": usage[p.rack_id]["aria"],
                "detail_url": p.rack.get_absolute_url(),
            }
            for p in snapshot["rack_placements"]
            if _can(user, "dcim.view_rack", p.rack)
        ],
    }


def available_descendants(floor_plan, *, user):
    owner = Location.objects.with_tree_fields().get(pk=floor_plan.location_id)
    descendant_ids = list(owner.descendants(include_self=False).values_list("pk", flat=True))
    descendants = Location.objects.restrict(user, "view").filter(pk__in=descendant_ids).order_by("name")
    used_locations = floor_plan.location_placements.values("location_id")
    locations = descendants.exclude(pk__in=used_locations)
    used_racks = floor_plan.rack_placements.values("rack_id")
    rack_location_ids = [owner.pk, *descendant_ids]
    racks = (
        Rack.objects.restrict(user, "view")
        .filter(location_id__in=rack_location_ids)
        .exclude(pk__in=used_racks)
        .order_by("name")
    )
    return locations, racks


def normalize_background_upload(upload):
    data = upload.read()
    if len(data) > _setting("background_max_bytes", 2_000_000):
        raise ValidationError("Background exceeds maximum byte size.")
    stripped = data.lstrip()
    if stripped.startswith(b"<"):
        data = _rasterize_svg(data)
    try:
        Image.MAX_IMAGE_PIXELS = _setting("background_max_pixels", 16_000_000)
        with Image.open(BytesIO(data)) as image:
            if image.format not in {"PNG", "JPEG"}:
                raise ValidationError("Background must be PNG, JPEG, or SVG.")
            max_dim = _setting("background_max_dimension", 8000)
            if image.width > max_dim or image.height > max_dim:
                raise ValidationError("Background dimensions exceed maximum.")
            out = BytesIO()
            image.convert("RGBA").save(out, format="PNG")
            return out.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValidationError("Invalid background image.") from exc


def _rasterize_svg(data):
    root = ElementTree.fromstring(data)
    count = 0
    for elem in root.iter():
        count += 1
        if count > 1000:
            raise ValidationError("SVG is too complex.")
        tag = elem.tag.rsplit("}", 1)[-1]
        if tag not in SAFE_SVG_ELEMENTS:
            raise ValidationError("SVG contains a forbidden element.")
        for key, value in elem.attrib.items():
            attr = key.rsplit("}", 1)[-1]
            lower = value.lower()
            if (
                attr.startswith("on")
                or len(value) > 2000
                or "url(" in lower
                or "http:" in lower
                or "https:" in lower
                or "data:" in lower
                or "javascript:" in lower
            ):
                raise ValidationError("SVG contains a forbidden attribute.")
            if attr not in SAFE_SVG_ATTR_PREFIXES:
                raise ValidationError("SVG contains a forbidden attribute.")
    try:
        import cairosvg  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ValidationError("SVG background support requires CairoSVG.") from exc
    return cairosvg.svg2png(bytestring=ElementTree.tostring(root), unsafe=False)


@transaction.atomic
def replace_background(*, user, floor_plan, expected_revision, upload):
    parent = FloorPlan.objects.select_for_update().get(pk=floor_plan.pk)
    _check(user, "location_floor_plan.change_floorplan", parent)
    _assert_revision(parent, expected_revision)
    png = normalize_background_upload(upload)
    old_name = parent.background.name if parent.background else None
    parent.background.save(f"{uuid4().hex}.png", ContentFile(png), save=False)
    _bump(parent)
    _assert_restricted(user, "change", parent)
    parent.save(update_fields=["background", "revision", "last_updated"])
    if old_name:
        transaction.on_commit(lambda: default_storage.delete(old_name))
    return parent
