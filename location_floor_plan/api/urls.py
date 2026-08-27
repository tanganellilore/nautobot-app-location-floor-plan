"""API URL declarations for Location Floor Plan."""

from django.urls import path
from nautobot.apps.api import OrderedDefaultRouter

from location_floor_plan.api import views

router = OrderedDefaultRouter()
router.register("location-maps", views.LocationMapViewSet)
router.register("location-placements", views.LocationPlacementViewSet)
router.register("rack-placements", views.RackPlacementViewSet)

urlpatterns = [
    path(
        "locations/<uuid:location_id>/resolved-map/",
        views.ResolvedLocationMapView.as_view(),
        name="location-resolved-map",
    )
]
urlpatterns += router.urls
