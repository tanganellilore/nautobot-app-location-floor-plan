# Install and Configure

## Requirements

- Nautobot `>=3.1.0,<3.3`.
- Django as provided by the supported Nautobot version.
- Python `>=3.10,<3.15`.

## Install

```bash
poetry add nautobot-location-floor-plan
```

or:

```bash
pip install nautobot-location-floor-plan
```

Enable the app in `nautobot_config.py`:

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
        "location_default_color": "#0d6efd",
        "rack_default_color": "#6c757d",
        "rack_utilization_color_enabled": True,
        "rack_utilization_palette": {
            "empty": "#6c757d",
            "low": "#198754",
            "medium": "#ffc107",
            "high": "#fd7e14",
            "critical": "#dc3545",
        },
    }
}
```

Run deployment commands:

```bash
nautobot-server migrate location_floor_plan
nautobot-server post_upgrade
nautobot-server collectstatic --no-input
sudo systemctl restart nautobot nautobot-worker nautobot-scheduler
```

## Permissions

| Capability | Required permissions |
| --- | --- |
| View tab | `dcim.view_location`. |
| View map/snapshot | `location_floor_plan.view_floorplan`, placement view permissions, and target Location/Rack view permissions. |
| Create map | `location_floor_plan.add_floorplan` plus `dcim.view_location`. |
| Edit/delete map or background | `location_floor_plan.change_floorplan` or `location_floor_plan.delete_floorplan`. |
| Edit placements | Parent map change permission plus placement add/change/delete and target view permission. |

## Secure backgrounds

PNG, JPEG, and SVG uploads are accepted and stored as PNG. Defaults: 2 MB, 16 million pixels, 8,000 px max dimension. SVGs are sanitized with `defusedxml`, constrained to safe shape tags/attributes, rasterized by CairoSVG, and served with `nosniff`, private no-store caching, and restrictive CSP headers.

## Shape colors

Location and Rack placements use a server-side color precedence chain:

1. Placement-specific override (nullable).
2. Persistent target style on the Location or Rack (`/api/plugins/location-floor-plan/location-styles/` and `/rack-styles/`).
3. For racks only: utilization palette color when `rack_utilization_color_enabled` is `True`.
4. Global default (`location_default_color` or `rack_default_color`).

All colors must be strict 6-digit hex (e.g. `#0d6efd`). The editor exposes a native color input for placement overrides; target-level styles can be managed through the REST API.

## Audit stale placements

```bash
nautobot-server audit_location_floor_plan
nautobot-server audit_location_floor_plan --cleanup
```

The first command reports stale Location and Rack placements. `--cleanup` deletes them transactionally and increments affected map revisions.
