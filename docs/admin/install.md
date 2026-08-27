# Install and Configure

## Requirements

- Nautobot `>=3.2.3,<3.3`.
- Django 5.2.17 from Nautobot 3.2.3.
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

## Audit stale placements

```bash
nautobot-server audit_location_floor_plan
nautobot-server audit_location_floor_plan --cleanup
```

The first command reports stale Location and Rack placements. `--cleanup` deletes them transactionally and increments affected map revisions.
