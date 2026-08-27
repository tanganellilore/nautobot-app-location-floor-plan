# pylint: disable=missing-module-docstring
from django.templatetags.static import static
from django.urls import path
from django.views.generic import RedirectView
from nautobot.apps.urls import NautobotUIViewSetRouter

from . import views

app_name = "location_floor_plan"
router = NautobotUIViewSetRouter()

urlpatterns = [
    path("docs/", RedirectView.as_view(url=static("location_floor_plan/docs/index.html")), name="docs"),
    path("floor-plans/", views.FloorPlanListView.as_view(), name="floorplan_list"),
    path("location/<uuid:pk>/location-floor-plan/", views.LocationFloorPlanView.as_view(), name="location_floor_plan"),
]

urlpatterns += router.urls
