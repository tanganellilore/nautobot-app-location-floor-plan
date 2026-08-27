# Location Floor Plan

Location Floor Plan is a Nautobot App (`location_floor_plan`) for maintaining interactive physical hierarchy maps for Nautobot Locations and Racks. It adds a Location Floor Plan tab to Location pages, map/placement models, a resolver that inherits maps across arbitrary Location depth, REST endpoints for automation, secure background image handling, rack-utilization overlays, and an audit command for stale placements.

## Purpose and source-of-truth principles

Location Floor Plan visualizes Nautobot data; it does not replace it. Nautobot Locations, Racks, Devices, and object permissions remain the source of truth. The app stores only map canvases and placement geometry:

- `FloorPlan`: one canvas owned by one Location.
- `LocationPlacement`: a rectangle or polygon for a strict descendant Location on a map.
- `RackPlacement`: a rack rectangle for a Rack on the map owner's Location or any descendant Location.

There is no `RackMap` model. Rack occupancy is derived live from Nautobot Devices mounted in Racks and is not persisted by this app.

## Prerequisites and supported versions

- Nautobot `>=3.2.3,<3.3` (validated against Nautobot 3.2.3).
- Django 5.2.17 as provided by Nautobot 3.2.3.
- Python `>=3.10,<3.15` (3.10, 3.11, 3.12, 3.13, and 3.14).
- Package name: `nautobot-location-floor-plan`; Python package/app config: `location_floor_plan`.
- Generated from the official `cookiecutter-nautobot-app` tag `nautobot-app-v3.1.4`.
- Front end uses Leaflet 1.9.4 and Geoman Free 2.20.0.

## Installation

### Install with Poetry

```bash
poetry add nautobot-location-floor-plan
```

### Install with pip

```bash
pip install nautobot-location-floor-plan
```

### Enable the app in Nautobot

In `nautobot_config.py`:

```python
PLUGINS = ["location_floor_plan"]

PLUGINS_CONFIG = {
    "location_floor_plan": {
        "rack_utilization_low_threshold": 50,
        "rack_utilization_medium_threshold": 80,
        "rack_utilization_high_threshold": 95,
        "background_max_bytes": 2_000_000,
        "background_max_pixels": 16_000_000,
        "background_max_dimension": 8000,
        "supported_targets": ["dcim.location", "dcim.rack"],
    }
}
```

Then run the standard Nautobot deployment steps:

```bash
nautobot-server migrate location_floor_plan
nautobot-server post_upgrade
nautobot-server collectstatic --no-input
sudo systemctl restart nautobot nautobot-worker nautobot-scheduler
```

Use your service manager/process names if they differ.

## Development commands

This repository keeps the exact Cookiecutter invoke workflow.

```bash
cp development/creds.example.env development/creds.env
poetry install --with dev,docs
poetry run invoke build
poetry run invoke start
poetry run invoke tests
```

Useful checks:

```bash
poetry run invoke ruff
poetry run invoke pylint
poetry run invoke djlint
poetry run invoke yamllint
poetry run invoke markdownlint
poetry run invoke build-and-check-docs
```

## Permissions matrix

| Capability | Required permissions |
| --- | --- |
| Open Location Floor Plan tab for a Location | `dcim.view_location` on the requested Location. |
| View a map | `location_floor_plan.view_floorplan` and `dcim.view_location` on the map owner. |
| View a complete snapshot | View permission on the map, all included `LocationPlacement`/`RackPlacement` objects, target Locations, and target Racks. |
| Create a map | `location_floor_plan.add_floorplan` plus `dcim.view_location` on the owner; constrained permissions are enforced after create. |
| Change/delete a map or background | `location_floor_plan.change_floorplan`/`delete_floorplan` on the map and constrained object permission. |
| Create/change/delete Location placements | Parent `location_floor_plan.change_floorplan`, relevant `add/change/delete_locationplacement`, target `dcim.view_location`, and constrained permission. |
| Create/change/delete Rack placements | Parent `location_floor_plan.change_floorplan`, relevant `add/change/delete_rackplacement`, target `dcim.view_rack`, and constrained permission. |
| Rack utilization data | `dcim.view_rack` for racks included in the resolved payload. |

## Data model definitions

- `FloorPlan(location, logical_width, logical_height, background, revision)`: one-to-one with `dcim.Location`; owner is immutable; logical dimensions are 1 to 1,000,000; revision starts at 1 and increments once per accepted mutation.
- `LocationPlacement(floor_plan, location, geometry)`: unique per map/location; target must be a strict descendant of the map owner; geometry is either `{"type":"rectangle","x":...}` or `{"type":"polygon","points":[[x,y],...]}` within map bounds.
- `RackPlacement(floor_plan, rack, x, y, width, height)`: unique per map/rack; target Rack must belong to the map owner or one of its descendants; rectangle must fit within map bounds.

## Arbitrary-depth inheritance algorithm

When rendering a Location, Location Floor Plan resolves the effective map as follows:

1. If the requested Location owns a visible `FloorPlan`, render that own map with no focus qualifier.
2. Otherwise, walk ancestors from the root toward the immediate parent.
3. The first ancestor that both owns a visible map and has an explicit `LocationPlacement` for the requested Location is selected.
4. The placement geometry becomes `focus` in the resolved payload.
5. If no explicit placement exists, no map is inherited. Intermediate levels may be skipped, but there is no implicit parent focus.

Required examples:

- L1 has a map; L2 is placed on L1. Viewing L2 inherits the L1 map and focuses the L2 geometry.
- L1 has a map; L3 is placed directly on L1; L2 has no map and no placement. Viewing L3 inherits L1 and focuses L3. This is an allowed intermediate skip.
- L1 has a map; only L2 is placed on L1; L3 has no direct placement. Viewing L3 does not inherit L1 from the L2 placement. There is no implicit parent focus.
- L2 has its own map; L4 is placed directly on L2; L3 is skipped. Viewing L4 inherits L2 and focuses L4.

## Minimal first-map procedure

1. Create or choose a Nautobot Location that will own the map.
2. Ensure child Locations/Racks exist under that owner.
3. Grant the permissions listed above.
4. Open the Location and select the **Location Floor Plan** tab.
5. Create the map with a logical width and height, optionally upload a PNG/JPEG/SVG background.
6. Use the picker to add descendant Locations and Racks.
7. Draw/edit shapes with Leaflet/Geoman, save the snapshot, then reload to confirm the revision advanced.

## Editor workflow

The UI is available at `/plugins/location-floor-plan/location/<location-uuid>/location-floor-plan/` as a Location tab. The editor loads the resolved payload, lists available descendants from the picker endpoint, draws Location polygons/rectangles and Rack rectangles, and saves a full snapshot. Concurrent saves are protected with revision headers.

## Rack usage

Rack usage is derived live from Nautobot Devices assigned to placed Racks. The service counts occupied rack units from each Device's `position` and Device Type `u_height`, clamps usage to the Rack `u_height`, and returns `used_ru`, `total_ru`, percentage, level, label, and ARIA text. Defaults are low `<50`, medium `<80`, high `<95`, and critical `>=95`; configure `rack_utilization_low_threshold`, `rack_utilization_medium_threshold`, and `rack_utilization_high_threshold` with `0 < low < medium < high <= 100`.

## API endpoints and revision headers

Base API path: `/api/plugins/location-floor-plan/`.

| Endpoint | Purpose |
| --- | --- |
| `GET/POST /floor-plans/` | List/create maps. Create requires `If-None-Match: *` or `expected_revision: 0`. |
| `GET/PUT/PATCH/DELETE /floor-plans/{id}/` | Manage one map. Writes/deletes require `If-Match: <revision>` or `expected_revision`. |
| `GET/PUT /floor-plans/{id}/snapshot/` | Read or atomically replace all placements. PUT supports `delete_stale_ids`. |
| `GET/PUT /floor-plans/{id}/background/` | Download or replace normalized background image using form file `background` or `file`. |
| `GET /floor-plans/{id}/descendants/` | Picker data: visible unused descendant Locations and Racks. |
| `GET/POST /location-placements/`, `GET/PUT/PATCH/DELETE /location-placements/{id}/` | Placement CRUD with parent map revision guard for writes. |
| `GET/POST /rack-placements/`, `GET/PUT/PATCH/DELETE /rack-placements/{id}/` | Rack placement CRUD with parent map revision guard for writes. |
| `GET /locations/{location_id}/resolved-map/` | Resolver payload for the UI and external consumers. |

Successful writes increment the parent map revision once. Stale writes return HTTP 409. `If-Match` may be quoted; `If-None-Match: *` is accepted for creation.

The background response is always served as `image/png` with `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store`, and a restrictive Content Security Policy.

## Secure upload behavior

Background uploads accept PNG, JPEG, or SVG. Every accepted upload is normalized to a stored PNG. Limits are controlled by `background_max_bytes` (default 2,000,000), `background_max_pixels` (16,000,000), and `background_max_dimension` (8,000). SVG input is parsed with `defusedxml`, restricted to safe shape elements/attributes, blocks scripts/remote/data URLs/event handlers, limits complexity to 1,000 elements, and rasterizes with CairoSVG.

## Stale placement audit and cleanup

If Nautobot hierarchy changes make placements invalid, snapshots separate stale placements from valid placements. Stale placements are not automatically deleted unless requested by a snapshot save with `delete_stale_ids` or by the audit command:

```bash
nautobot-server audit_location_floor_plan
nautobot-server audit_location_floor_plan --cleanup
```

The command prints `stale_location_placements`, `stale_rack_placements`, and each stale object. `--cleanup` deletes stale placements transactionally and bumps affected map revisions.

## Upgrade

```bash
pip install --upgrade location-floor-plan
nautobot-server migrate location_floor_plan
nautobot-server post_upgrade
nautobot-server collectstatic --no-input
sudo systemctl restart nautobot nautobot-worker nautobot-scheduler
nautobot-server audit_location_floor_plan
```

Review `PLUGINS_CONFIG["location_floor_plan"]` after upgrade for new settings and rerun `audit_location_floor_plan --cleanup` only after validating reported stale placements.

## Limitations

- Only Nautobot Locations and Racks are supported targets.
- There is no `RackMap`; rack detail diagrams are out of scope.
- Map inheritance requires an explicit placement of the requested Location on an ancestor map.
- Bulk API create/update/delete is intentionally disabled for app models.
- Backgrounds are normalized to PNG; original uploads are not retained.
- Rack usage reflects mounted Devices only; reservations or planned capacity are not counted unless represented by Devices.

## Troubleshooting

- **Location Floor Plan tab missing**: verify `PLUGINS` contains `location_floor_plan`, static files were collected, and the user can view the Location.
- **403/empty payload**: check Nautobot object permissions for the map owner, placements, target Locations, and Racks.
- **409 conflict**: reload the map and retry with the current revision.
- **Background rejected**: check byte, pixel, dimension, file type, and SVG safety limits.
- **Rack colors look wrong**: verify Device positions, Device Type `u_height`, Rack `u_height`, and utilization thresholds.

## Documentation

Generated documentation lives in `docs/` and can be served locally with:

```bash
poetry run invoke docs
```
