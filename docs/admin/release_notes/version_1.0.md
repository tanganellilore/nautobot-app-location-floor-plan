# v1.0.0 Release Notes

This document describes all new features and changes in the release. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Release Overview

This is the initial stable release of the Location Floor Plan app for Nautobot. It introduces interactive physical hierarchy maps owned by Locations, with placement and rack-utilization overlays, a REST API, secure background uploads, and an audit command.

## [v1.0.0] - 2026-08-28

### Added

- Initial release of `nautobot-location-floor-plan`.
- `FloorPlan`, `LocationPlacement`, and `RackPlacement` models.
- Interactive map editor using Leaflet and Geoman, integrated as a Location tab.
- Arbitrary-depth map inheritance based on explicit Location placements.
- Live rack-utilization overlays derived from Nautobot Devices.
- REST API endpoints for maps, snapshots, backgrounds, placements, and resolved maps.
- Secure background image upload with SVG rasterization and size limits.
- `audit_location_floor_plan` management command for stale placement reporting and cleanup.
- Nautobot 3.1.0+ compatibility and support for Python 3.10 through 3.14.
