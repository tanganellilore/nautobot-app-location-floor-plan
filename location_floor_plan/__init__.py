"""App declaration for location_floor_plan."""

# Metadata is inherited from Nautobot. If not including Nautobot in the environment, this should be added
from importlib import metadata

from nautobot.apps import NautobotAppConfig

__version__ = metadata.version(__name__)


class LocationFloorPlanConfig(NautobotAppConfig):
    """App configuration for the location_floor_plan app."""

    name = "location_floor_plan"
    verbose_name = "Location Floor Plan"
    version = __version__
    author = "Location Floor Plan Contributors"
    description = "Interactive physical hierarchy maps for Nautobot Locations and Racks."
    base_url = "location-floor-plan"
    required_settings = []
    min_version = "3.1.0"
    max_version = "3.3"
    default_settings = {
        "rack_utilization_warning_threshold": 80,
        "rack_utilization_critical_threshold": 95,
        "rack_utilization_low_threshold": 50,
        "rack_utilization_medium_threshold": 80,
        "rack_utilization_high_threshold": 95,
        "background_max_bytes": 2_000_000,
        "background_max_pixels": 16_000_000,
        "background_max_dimension": 8000,
        "supported_targets": ["dcim.location", "dcim.rack"],
    }
    docs_view_name = "plugins:location_floor_plan:docs"
    searchable_models = []


config = LocationFloorPlanConfig  # pylint:disable=invalid-name
