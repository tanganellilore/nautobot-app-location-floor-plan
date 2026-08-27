# ruff: noqa: D102
"""Audit Location Floor Plan stale or invalid placements."""

from django.core.management.base import BaseCommand
from django.db import transaction

from location_floor_plan.models import LocationPlacement, RackPlacement, _is_descendant


class Command(BaseCommand):
    """Report stale Location Floor Plan placements and optionally clean them up."""

    help = "Report stale Location Floor Plan placements; pass --cleanup to delete stale placements and bump map revisions."

    def add_arguments(self, parser):
        parser.add_argument("--cleanup", action="store_true", help="Delete stale placements transactionally.")

    def handle(self, *args, **options):
        cleanup = options["cleanup"]
        stale_locations = [
            p
            for p in LocationPlacement.objects.select_related("location", "location_map__location")
            if not _is_descendant(p.location, p.location_map.location)
        ]
        stale_racks = [
            p
            for p in RackPlacement.objects.select_related("rack__location", "location_map__location")
            if p.rack.location_id != p.location_map.location_id
            and not _is_descendant(p.rack.location, p.location_map.location)
        ]
        self.stdout.write(f"stale_location_placements={len(stale_locations)}")
        self.stdout.write(f"stale_rack_placements={len(stale_racks)}")
        for placement in stale_locations + stale_racks:
            self.stdout.write(f"stale {placement._meta.label_lower} {placement.pk} map={placement.location_map_id}")
        if cleanup:
            with transaction.atomic():
                maps = {p.location_map for p in stale_locations + stale_racks}
                for placement in stale_locations + stale_racks:
                    placement.delete()
                for location_map in maps:
                    location_map.revision += 1
                    location_map.save(update_fields=["revision", "last_updated"])
