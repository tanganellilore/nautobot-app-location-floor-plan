"""Shared, immutable defaults for location_floor_plan."""

# Stored as an immutable tuple of key/value pairs so callers can build a fresh
# dictionary via ``dict(...)`` and avoid leaking mutable shared state.
RACK_UTILIZATION_PALETTE = (
    ("empty", "#6c757d"),
    ("low", "#198754"),
    ("medium", "#ffc107"),
    ("high", "#fd7e14"),
    ("critical", "#dc3545"),
)
