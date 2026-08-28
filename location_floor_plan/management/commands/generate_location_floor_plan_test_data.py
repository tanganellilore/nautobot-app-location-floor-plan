"""Generate test data for the Location Floor Plan app."""

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS
from nautobot.dcim.choices import DeviceFaceChoices
from nautobot.dcim.models import Device, DeviceType, Location, LocationType, Manufacturer, PowerPanel, Rack
from nautobot.extras.models import Role, Status

LOCATION_TYPE_TREE = (
    ("Region", None),
    ("Site", "Region"),
    ("Datacenter", "Site"),
    ("Area", "Datacenter"),
    ("Cage", "Area"),
)

LOCATION_TREE = (
    ("Italy", "Region", None),
    ("IT1", "Site", "Italy"),
    ("DCA", "Datacenter", "IT1"),
    ("DATA01", "Area", "DCA"),
    ("CAGE01", "Cage", "DATA01"),
    ("CAGE02", "Cage", "DATA01"),
    ("ROOM01", "Area", "DCA"),
    ("ROOM02", "Area", "DCA"),
)

DEVICE_ROLES = (
    ("Server", "0000ff"),
    ("Switch", "ff00ff"),
)

MANUFACTURERS = ("Dell", "Lenovo", "Cisco")

DEVICE_TYPES = (
    ("R640", "Dell", "Server"),
    ("RS45", "Lenovo", "Server"),
    ("Catalyst 9300", "Cisco", "Switch"),
)

RACK_NAMES = tuple(f"{prefix}{number:02d}" for prefix in ("A", "B") for number in range(1, 6))
DIRECT_RACK_LOCATION_NAMES = ("ROOM01", "ROOM02")
CAGE_NAMES = ("CAGE01", "CAGE02")
RACK_LOCATION_NAMES = CAGE_NAMES + DIRECT_RACK_LOCATION_NAMES
SITE_NAME = "IT1"
DATACENTER_NAME = "DCA"
DEVICE_POSITIONS = (1, 3, 5, 7, 9)
CAGE_PARENT_BY_NAME = {cage_name: "DATA01" for cage_name in CAGE_NAMES}


def _device_count_for_rack(data_center_index, rack_index):
    """Return a deterministic demo device count between 3 and 5 for a rack."""
    return 3 + ((data_center_index + rack_index) % 3)


def _rack_name(rack_location_name, rack_short_name):
    """Return the generated rack name, including site/datacenter/area/cage path."""
    if rack_location_name in CAGE_PARENT_BY_NAME:
        return (
            f"{SITE_NAME}.{DATACENTER_NAME}."
            f"{CAGE_PARENT_BY_NAME[rack_location_name]}.{rack_location_name}.{rack_short_name}"
        )
    return f"{SITE_NAME}.{DATACENTER_NAME}.{rack_location_name}.{rack_short_name}"


def _device_name(role_name, serial):
    """Return the generated demo device name."""
    prefix = "sw" if role_name == "Switch" else "srv"
    return f"{prefix}{serial:03d}"


def _device_serial(rack_location_index, rack_index, slot):
    """Return a stable generated device serial number."""
    return rack_location_index * 100 + rack_index * 10 + slot


class Command(BaseCommand):
    """Populate the database with various data as a baseline for testing (automated or manual)."""

    help = __doc__

    def add_arguments(self, parser):
        """Add command line arguments."""
        parser.add_argument(
            "--database",
            default=DEFAULT_DB_ALIAS,
            help='The database to generate the test data in. Defaults to the "default" database.',
        )
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Flush any existing Location Floor Plan test data from the database before generating new data.",
        )

    def _generate_static_data(self, db):
        """Generate static data required for test cases."""
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        # This is an inherently orchestration-style management command that populates
        # a broad set of related demo objects; splitting it would not improve clarity.
        device_content_type = ContentType.objects.db_manager(db).get_for_model(Device)
        rack_content_type = ContentType.objects.db_manager(db).get_for_model(Rack)
        power_panel_content_type = ContentType.objects.db_manager(db).get_for_model(PowerPanel)
        rack_allowed_content_types = (
            device_content_type,
            rack_content_type,
            power_panel_content_type,
        )
        location_types = {}
        for name, parent_name in LOCATION_TYPE_TREE:
            parent = location_types.get(parent_name) if parent_name else None
            location_type, created = LocationType.objects.using(db).get_or_create(
                name=name,
                defaults={"parent": parent, "nestable": True},
            )
            changed = False
            if location_type.parent_id != (parent.pk if parent else None):
                location_type.parent = parent
                changed = True
            if not location_type.nestable:
                location_type.nestable = True
                changed = True
            if created or changed:
                location_type.validated_save(using=db)
            location_types[name] = location_type

        for name in ("Region", "Site", "Datacenter"):
            location_types[name].content_types.remove(*rack_allowed_content_types)
        for name in ("Area", "Cage"):
            location_types[name].content_types.add(*rack_allowed_content_types)

        location_status = Status.objects.get_for_model(Location).using(db).first()
        rack_status = Status.objects.get_for_model(Rack).using(db).first()
        device_status = Status.objects.get_for_model(Device).using(db).first()
        if location_status is None:
            raise RuntimeError("No Status is available for dcim.Location.")
        if rack_status is None:
            raise RuntimeError("No Status is available for dcim.Rack.")
        if device_status is None:
            raise RuntimeError("No Status is available for dcim.Device.")

        locations = {}
        for name, location_type_name, parent_name in LOCATION_TREE:
            parent = locations.get(parent_name) if parent_name else None
            location_type = location_types[location_type_name]
            location, created = Location.objects.using(db).get_or_create(
                name=name,
                parent=parent,
                defaults={"location_type": location_type, "parent": parent, "status": location_status},
            )
            changed = False
            if location.location_type_id != location_type.pk:
                location.location_type = location_type
                changed = True
            if location.parent_id != (parent.pk if parent else None):
                location.parent = parent
                changed = True
            if location.status_id != location_status.pk:
                location.status = location_status
                changed = True
            if created or changed:
                location.validated_save(using=db)
            self.stdout.write(f"{'Created' if created else 'Updated'} location: {name}")
            locations[name] = location

        roles = {}
        for name, color in DEVICE_ROLES:
            role, created = Role.objects.using(db).get_or_create(name=name, defaults={"color": color})
            if role.color != color:
                role.color = color
                role.validated_save(using=db)
            role.content_types.add(device_content_type)
            self.stdout.write(f"{'Created' if created else 'Updated'} device role: {name}")
            roles[name] = role

        manufacturers = {}
        for name in MANUFACTURERS:
            manufacturer, created = Manufacturer.objects.using(db).get_or_create(name=name)
            self.stdout.write(f"{'Created' if created else 'Updated'} manufacturer: {name}")
            manufacturers[name] = manufacturer

        device_types = []
        for model, manufacturer_name, role_name in DEVICE_TYPES:
            device_type, created = DeviceType.objects.using(db).get_or_create(
                model=model,
                manufacturer=manufacturers[manufacturer_name],
            )
            self.stdout.write(f"{'Created' if created else 'Updated'} device type: {model}")
            device_types.append((device_type, roles[role_name]))

        racks = {}
        for rack_location_name in RACK_LOCATION_NAMES:
            rack_location = locations[rack_location_name]
            for rack_short_name in RACK_NAMES:
                rack_name = _rack_name(rack_location_name, rack_short_name)
                rack, created = Rack.objects.using(db).get_or_create(
                    name=rack_name,
                    location=rack_location,
                    defaults={"status": rack_status},
                )
                if rack.status_id != rack_status.pk:
                    rack.status = rack_status
                    rack.validated_save(using=db)
                self.stdout.write(f"{'Created' if created else 'Updated'} rack: {rack_location_name}/{rack_name}")
                racks[(rack_location_name, rack_short_name)] = rack

        for rack_location_index, rack_location_name in enumerate(RACK_LOCATION_NAMES):
            rack_location = locations[rack_location_name]
            for rack_index, rack_short_name in enumerate(RACK_NAMES, start=1):
                for slot in range(1, _device_count_for_rack(rack_location_index, rack_index) + 1):
                    device_type, role = device_types[(rack_index + slot - 2) % len(device_types)]
                    position = DEVICE_POSITIONS[slot - 1]
                    serial = _device_serial(rack_location_index, rack_index, slot)
                    device_name = _device_name(role.name, serial)
                    device, created = Device.objects.using(db).get_or_create(
                        name=device_name,
                        defaults={
                            "device_type": device_type,
                            "role": role,
                            "location": rack_location,
                            "rack": racks[(rack_location_name, rack_short_name)],
                            "position": position,
                            "face": DeviceFaceChoices.FACE_FRONT,
                            "status": device_status,
                        },
                    )
                    changed = False
                    for field_name, value in (
                        ("device_type", device_type),
                        ("role", role),
                        ("location", rack_location),
                        ("rack", racks[(rack_location_name, rack_short_name)]),
                        ("status", device_status),
                    ):
                        if getattr(device, f"{field_name}_id") != value.pk:
                            setattr(device, field_name, value)
                            changed = True
                    if device.position != position:
                        device.position = position
                        changed = True
                    if device.face != DeviceFaceChoices.FACE_FRONT:
                        device.face = DeviceFaceChoices.FACE_FRONT
                        changed = True
                    if created or changed:
                        device.validated_save(using=db)
                    self.stdout.write(f"{'Created' if created else 'Updated'} device: {device_name}")

    def _flush_static_data(self, db):
        """Delete generated data in child-to-parent order."""
        Device.objects.using(db).filter(
            name__in=[
                _device_name(
                    DEVICE_TYPES[(rack_index + slot - 2) % len(DEVICE_TYPES)][2],
                    _device_serial(rack_location_index, rack_index, slot),
                )
                for rack_location_index, _rack_location in enumerate(RACK_LOCATION_NAMES)
                for rack_index, _rack in enumerate(RACK_NAMES, start=1)
                for slot in range(1, _device_count_for_rack(rack_location_index, rack_index) + 1)
            ]
        ).delete()
        Rack.objects.using(db).filter(
            name__in=[_rack_name(rack_location, rack) for rack_location in RACK_LOCATION_NAMES for rack in RACK_NAMES],
            location__name__in=RACK_LOCATION_NAMES,
        ).delete()

        for name, _, _ in reversed(LOCATION_TREE):
            deleted_count, _ = Location.objects.using(db).filter(name=name).delete()
            if deleted_count:
                self.stdout.write(f"Deleted location: {name}")
        for name, _ in reversed(LOCATION_TYPE_TREE):
            deleted_count, _ = LocationType.objects.using(db).filter(name=name).delete()
            if deleted_count:
                self.stdout.write(f"Deleted location type: {name}")

    def handle(self, *args, **options):
        """Entry point to the management command."""
        if options["flush"]:
            self.stdout.write("Flushing existing Location Floor Plan test data...")
            self._flush_static_data(db=options["database"])

        self._generate_static_data(db=options["database"])

        self.stdout.write(self.style.SUCCESS(f"Database {options['database']} populated with app data successfully!"))
