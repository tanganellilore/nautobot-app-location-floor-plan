"""Focused tests for Location Floor Plan UI forms and view context."""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from nautobot.apps.forms import BootstrapMixin, StaticSelect2

from location_floor_plan.forms import PlacementPickerForm
from location_floor_plan.views import LocationFloorPlanView


class PlacementPickerFormTestCase(SimpleTestCase):
    """Placement picker form behavior."""

    def test_form_uses_official_bootstrap_and_static_select2(self):
        form = PlacementPickerForm()

        self.assertIsInstance(form, BootstrapMixin)
        self.assertIsInstance(form.fields["target"].widget, StaticSelect2)
        self.assertTrue(form.fields["target"].required)
        self.assertEqual(form.fields["target"].choices, [("", "")])
        self.assertEqual(form.fields["target"].widget.attrs["data-placeholder"], "Select a location or rack")


class LocationFloorPlanViewContextTestCase(SimpleTestCase):
    """Location location floor plan view context behavior."""

    def test_context_exposes_fresh_placement_picker_form_for_authorized_user(self):
        request = RequestFactory().get("/location/example/location-floor-plan/")
        request.user = SimpleNamespace(has_perm=lambda *args: True)
        location = SimpleNamespace(pk="00000000-0000-0000-0000-000000000001")

        with patch("location_floor_plan.views.LocationMap.objects.filter") as mock_filter:
            mock_filter.return_value.first.return_value = None
            context = LocationFloorPlanView().get_extra_context(request, location)

        self.assertIsInstance(context["placement_picker_form"], PlacementPickerForm)
        self.assertIsNot(context["placement_picker_form"], PlacementPickerForm())
