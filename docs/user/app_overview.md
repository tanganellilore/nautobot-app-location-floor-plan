# App Overview

Location Floor Plan adds a Location **Location Floor Plan** tab at `/plugins/location-floor-plan/location/<location-uuid>/location-floor-plan/` and REST APIs under `/api/plugins/location-floor-plan/`.

## Architecture

Nautobot remains the source of truth. Location Floor Plan stores only:

- `FloorPlan`: one map canvas per owning Location.
- `LocationPlacement`: descendant Location geometry on a map.
- `RackPlacement`: Rack rectangle on a map.

There is no `RackMap`. Rack usage is derived live from mounted Nautobot Devices.

## Inheritance

The resolver first uses the requested Location's own map. If there is no own map, it walks ancestors from root to parent and selects the first ancestor map that explicitly places the requested Location. Intermediate hierarchy levels may be skipped, but parent placement is never implied.

Examples: L2 can inherit L1 if L2 is placed on L1; L3 can inherit L1 if L3 is directly placed on L1 even when L2 is skipped; L3 cannot inherit from an L2 placement alone; L4 can inherit L2 if L4 is directly placed on L2 while L3 is skipped.
