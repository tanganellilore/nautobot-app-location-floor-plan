"""Forms for Location Floor Plan UI components."""

from django import forms
from nautobot.apps.forms import BootstrapMixin, StaticSelect2


class PlacementPickerForm(BootstrapMixin, forms.Form):
    """Shell form for the client-populated placement target picker."""

    # This must remain a static select widget rather than DynamicModelChoiceField:
    # candidates are context/permission-specific and must be merged with locally
    # deleted unsaved placements client-side. Choices come from the existing
    # permission-restricted descendants endpoint.
    target = forms.ChoiceField(
        choices=[("", "")],
        label="Placement target",
        help_text="Select an available location or rack to place on this map.",
        required=True,
        widget=StaticSelect2(attrs={"data-placeholder": "Select a location or rack"}),
    )
