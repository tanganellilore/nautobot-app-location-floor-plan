# Generated migration for custom shape colors.

import re
import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
validate_hex_color = django.core.validators.RegexValidator(HEX_COLOR_RE, "Enter a valid hex color (e.g. #RRGGBB).")


class Migration(migrations.Migration):
    dependencies = [
        ("location_floor_plan", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="locationplacement",
            name="color",
            field=models.CharField(
                blank=True,
                help_text="Optional hex color override (#RRGGBB) for this placement.",
                max_length=7,
                null=True,
                validators=[validate_hex_color],
            ),
        ),
        migrations.AddField(
            model_name="rackplacement",
            name="color",
            field=models.CharField(
                blank=True,
                help_text="Optional hex color override (#RRGGBB) for this placement.",
                max_length=7,
                null=True,
                validators=[validate_hex_color],
            ),
        ),
        migrations.CreateModel(
            name="LocationStyle",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False, unique=True
                    ),
                ),
                (
                    "color",
                    models.CharField(
                        blank=True,
                        help_text="Default hex color (#RRGGBB) for placements of this location.",
                        max_length=7,
                        null=True,
                        validators=[validate_hex_color],
                    ),
                ),
                (
                    "location",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="location_floor_plan_style",
                        to="dcim.location",
                    ),
                ),
            ],
            options={
                "verbose_name": "location style",
                "verbose_name_plural": "location styles",
            },
        ),
        migrations.CreateModel(
            name="RackStyle",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False, unique=True
                    ),
                ),
                (
                    "color",
                    models.CharField(
                        blank=True,
                        help_text="Default hex color (#RRGGBB) for placements of this rack.",
                        max_length=7,
                        null=True,
                        validators=[validate_hex_color],
                    ),
                ),
                (
                    "rack",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="location_floor_plan_style",
                        to="dcim.rack",
                    ),
                ),
            ],
            options={
                "verbose_name": "rack style",
                "verbose_name_plural": "rack styles",
            },
        ),
    ]
