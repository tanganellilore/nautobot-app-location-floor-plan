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
            for p in LocationPlacement.objects.select_related("location", "floor_plan__location")
            if not _is_descendant(p.location, p.floor_plan.location)
        ]
        stale_racks = [
            p
            for p in RackPlacement.objects.select_related("rack__location", "floor_plan__location")
            if p.rack.location_id != p.floor_plan.location_id
            and not _is_descendant(p.rack.location, p.floor_plan.location)
        ]
        self.stdout.write(f"stale_location_placements={len(stale_locations)}")
        self.stdout.write(f"stale_rack_placements={len(stale_racks)}")
        for placement in stale_locations + stale_racks:
            self.stdout.write(f"stale {placement._meta.label_lower} {placement.pk} map={placement.floor_plan_id}")
        if cleanup:
            with transaction.atomic():
                maps = {p.floor_plan for p in stale_locations + stale_racks}
                for placement in stale_locations + stale_racks:
                    placement.delete()
                for floor_plan in maps:
                    floor_plan.revision += 1
                    floor_plan.save(update_fields=["revision", "last_updated"])
