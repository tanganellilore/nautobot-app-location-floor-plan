# ruff: noqa: D101,D102
# pylint: disable=missing-class-docstring,missing-function-docstring,too-many-ancestors
"""API views for Location Floor Plan."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse
from drf_spectacular.utils import extend_schema
from nautobot.apps.api import NautobotModelViewSet
from nautobot.dcim.models import Location
from rest_framework import decorators, parsers, response, status, views
from rest_framework.exceptions import APIException, MethodNotAllowed, ValidationError

from location_floor_plan.api.filtersets import FloorPlanFilterSet, LocationPlacementFilterSet, RackPlacementFilterSet
from location_floor_plan.api.serializers import (
    FloorPlanSerializer,
    FloorPlanSnapshotSerializer,
    LocationPlacementSerializer,
    RackPlacementSerializer,
    ResolvedFloorPlanSerializer,
    SnapshotWriteSerializer,
)
from location_floor_plan.models import FloorPlan, LocationPlacement, RackPlacement
from location_floor_plan.services import (
    RevisionConflict,
    available_descendants,
    create_floor_plan,
    create_location_placement,
    create_rack_placement,
    delete_floor_plan,
    delete_location_placement,
    delete_rack_placement,
    get_visible_snapshot,
    renderer_payload,
    replace_background,
    replace_snapshot,
    update_floor_plan,
    update_location_placement,
    update_rack_placement,
)


def _expected_revision(request, data=None):
    value = request.headers.get("If-Match")
    if value is None:
        value = request.data.get("expected_revision")
    if value is None:
        value = (data or {}).get("expected_revision")
    if value is None:
        raise ValidationError("If-Match or expected_revision is required.")
    if value == "*":
        return 0
    try:
        return int(str(value).strip('"'))
    except ValueError as exc:
        raise ValidationError("Invalid revision value.") from exc


def _conflict_response(exc):
    return response.Response({"detail": exc.messages}, status=status.HTTP_409_CONFLICT)


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Revision conflict."


def _expected_create_revision(request, data=None):
    value = request.headers.get("If-None-Match")
    if value is None:
        value = request.data.get("expected_revision")
    if value is None:
        value = (data or {}).get("expected_revision")
    if value is None:
        raise ValidationError("If-None-Match: * or expected_revision 0 is required.")
    if value == "*":
        return 0
    try:
        revision = int(str(value).strip('"'))
    except ValueError as exc:
        raise ValidationError("Invalid revision value.") from exc
    if revision != 0:
        raise ValidationError("Creation requires expected revision 0.")
    return revision


class FloorPlanViewSet(NautobotModelViewSet):
    """CRUD adapter for maps delegating writes to the mutation service."""

    queryset = FloorPlan.objects.select_related("location")
    serializer_class = FloorPlanSerializer
    filterset_class = FloorPlanFilterSet
    parser_classes = [parsers.JSONParser, parsers.MultiPartParser, parsers.FormParser]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("location")
        return queryset.restrict(self.request.user, "view").filter(
            location__in=Location.objects.restrict(self.request.user, "view")
        )

    def filter_queryset(self, queryset):
        # The background endpoint serves the raw image file and is commonly requested with a
        # cache-busting query string such as ``?v=<revision>``. ``get_object()`` calls
        # ``filter_queryset()``, which would otherwise reject the unknown ``v`` parameter.
        # Skip filtering for the background action only; list/detail filters remain strict.
        if self.action == "background":
            return queryset
        return super().filter_queryset(queryset)

    def create(self, request, *args, **kwargs):
        if isinstance(request.data, list):
            raise ValidationError("Bulk creation is not supported.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(exclude=True)
    def bulk_update(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)

    @extend_schema(exclude=True)
    def bulk_partial_update(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)

    @extend_schema(exclude=True)
    def bulk_destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        expected_revision = _expected_create_revision(self.request, data)
        data.pop("id", None)
        data.pop("_custom_field_data", None)
        data.pop("expected_revision", None)
        try:
            obj = create_floor_plan(user=self.request.user, expected_revision=expected_revision, **data)
        except RevisionConflict as exc:
            raise Conflict(exc.messages) from exc
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        serializer.instance = obj

    def perform_update(self, serializer):
        data = dict(serializer.validated_data)
        expected_revision = _expected_revision(self.request, data)
        data.pop("expected_revision", None)
        data.pop("location", None)
        try:
            obj = update_floor_plan(
                user=self.request.user,
                floor_plan=self.get_object(),
                expected_revision=expected_revision,
                **data,
            )
        except RevisionConflict as exc:
            raise Conflict(exc.messages) from exc
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        serializer.instance = obj

    def update(self, request, *args, **kwargs):
        try:
            return super().update(request, *args, **kwargs)
        except RevisionConflict as exc:
            return _conflict_response(exc)

    def partial_update(self, request, *args, **kwargs):
        try:
            return super().partial_update(request, *args, **kwargs)
        except RevisionConflict as exc:
            return _conflict_response(exc)

    def destroy(self, request, *args, **kwargs):
        try:
            delete_floor_plan(
                user=request.user, floor_plan=self.get_object(), expected_revision=_expected_revision(request)
            )
        except RevisionConflict as exc:
            return _conflict_response(exc)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        return response.Response(status=status.HTTP_204_NO_CONTENT)

    @decorators.action(detail=True, methods=["get", "put"])
    def snapshot(self, request, pk=None):  # pylint: disable=unused-argument
        floor_plan = self.get_object()
        if request.method == "PUT":
            write_serializer = SnapshotWriteSerializer(data=request.data, context={"request": request})
            write_serializer.is_valid(raise_exception=True)
            try:
                payload = replace_snapshot(
                    user=request.user,
                    floor_plan=floor_plan,
                    expected_revision=_expected_revision(request, write_serializer.validated_data),
                    location_placements=write_serializer.validated_data["location_placements"],
                    rack_placements=write_serializer.validated_data["rack_placements"],
                    delete_stale_ids=write_serializer.validated_data.get("delete_stale_ids", []),
                )
            except RevisionConflict as exc:
                return _conflict_response(exc)
            except DjangoValidationError as exc:
                raise ValidationError(exc.messages) from exc
            return response.Response(FloorPlanSnapshotSerializer(payload, context={"request": request}).data)
        payload = get_visible_snapshot(user=request.user, floor_plan=floor_plan)
        return response.Response(FloorPlanSnapshotSerializer(payload, context={"request": request}).data)

    @decorators.action(detail=True, methods=["get"])
    def descendants(self, request, pk=None):  # pylint: disable=unused-argument
        locations, racks = available_descendants(self.get_object(), user=request.user)
        return response.Response(
            {
                "locations": [{"id": str(obj.pk), "display": str(obj)} for obj in locations],
                "racks": [{"id": str(obj.pk), "display": str(obj)} for obj in racks],
            }
        )

    @decorators.action(detail=True, methods=["get"], url_path="available-locations")
    def available_locations(self, request, pk=None):  # pylint: disable=unused-argument
        locations, _ = available_descendants(self.get_object(), user=request.user)
        return response.Response([{"id": str(obj.pk), "name": str(obj)} for obj in locations])

    @decorators.action(detail=True, methods=["get"], url_path="available-racks")
    def available_racks(self, request, pk=None):  # pylint: disable=unused-argument
        _, racks = available_descendants(self.get_object(), user=request.user)
        return response.Response([{"id": str(obj.pk), "name": str(obj)} for obj in racks])

    @decorators.action(detail=True, methods=["get", "put"])
    def background(self, request, pk=None):  # pylint: disable=unused-argument
        floor_plan = self.get_object()
        if request.method == "PUT":
            upload = request.FILES.get("background") or request.FILES.get("file")
            if upload is None:
                raise ValidationError("Background file is required.")
            try:
                floor_plan = replace_background(
                    user=request.user,
                    floor_plan=floor_plan,
                    expected_revision=_expected_revision(request),
                    upload=upload,
                    logical_width=request.data.get("logical_width") or None,
                    logical_height=request.data.get("logical_height") or None,
                    scale_placements=request.data.get("scale_placements", "true"),
                )
            except RevisionConflict as exc:
                return _conflict_response(exc)
            except DjangoValidationError as exc:
                raise ValidationError(exc.messages) from exc
        if not floor_plan.background:
            raise ValidationError("No background is available.")
        resp = FileResponse(floor_plan.background.open("rb"), content_type="image/png")
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Cache-Control"] = "private, no-store"
        resp["Content-Security-Policy"] = "default-src 'none'; img-src 'self'"
        return resp


class WritablePlacementMixin:
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def create(self, request, *args, **kwargs):
        if isinstance(request.data, list):
            raise MethodNotAllowed(request.method)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(exclude=True)
    def bulk_update(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)

    @extend_schema(exclude=True)
    def bulk_partial_update(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)

    @extend_schema(exclude=True)
    def bulk_destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)


class LocationPlacementViewSet(WritablePlacementMixin, NautobotModelViewSet):
    queryset = LocationPlacement.objects.select_related("floor_plan", "location")
    serializer_class = LocationPlacementSerializer
    filterset_class = LocationPlacementFilterSet

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .restrict(self.request.user, "view")
            .filter(
                floor_plan__in=FloorPlan.objects.restrict(self.request.user, "view"),
                location__in=Location.objects.restrict(self.request.user, "view"),
            )
            .filter(floor_plan__location__in=Location.objects.restrict(self.request.user, "view"))
        )

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        expected = _expected_revision(self.request, data)
        data.pop("expected_revision", None)
        try:
            serializer.instance = create_location_placement(user=self.request.user, expected_revision=expected, **data)
        except RevisionConflict as exc:
            raise Conflict(exc.messages) from exc
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc

    def perform_update(self, serializer):
        data = dict(serializer.validated_data)
        expected = _expected_revision(self.request, data)
        data.pop("expected_revision", None)
        data.pop("floor_plan", None)
        data.pop("location", None)
        try:
            serializer.instance = update_location_placement(
                user=self.request.user, instance=self.get_object(), expected_revision=expected, **data
            )
        except RevisionConflict as exc:
            raise Conflict(exc.messages) from exc
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc

    def destroy(self, request, *args, **kwargs):
        try:
            delete_location_placement(
                user=request.user, instance=self.get_object(), expected_revision=_expected_revision(request)
            )
        except RevisionConflict as exc:
            return _conflict_response(exc)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class RackPlacementViewSet(WritablePlacementMixin, NautobotModelViewSet):
    queryset = RackPlacement.objects.select_related("floor_plan", "rack")
    serializer_class = RackPlacementSerializer
    filterset_class = RackPlacementFilterSet

    def get_queryset(self):
        from nautobot.dcim.models import Rack  # pylint: disable=import-outside-toplevel

        return (
            super()
            .get_queryset()
            .restrict(self.request.user, "view")
            .filter(
                floor_plan__in=FloorPlan.objects.restrict(self.request.user, "view"),
                rack__in=Rack.objects.restrict(self.request.user, "view"),
            )
            .filter(floor_plan__location__in=Location.objects.restrict(self.request.user, "view"))
        )

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        expected = _expected_revision(self.request, data)
        data.pop("expected_revision", None)
        try:
            serializer.instance = create_rack_placement(user=self.request.user, expected_revision=expected, **data)
        except RevisionConflict as exc:
            raise Conflict(exc.messages) from exc
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc

    def perform_update(self, serializer):
        data = dict(serializer.validated_data)
        expected = _expected_revision(self.request, data)
        data.pop("expected_revision", None)
        data.pop("floor_plan", None)
        data.pop("rack", None)
        try:
            serializer.instance = update_rack_placement(
                user=self.request.user, instance=self.get_object(), expected_revision=expected, **data
            )
        except RevisionConflict as exc:
            raise Conflict(exc.messages) from exc
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc

    def destroy(self, request, *args, **kwargs):
        try:
            delete_rack_placement(
                user=request.user, instance=self.get_object(), expected_revision=_expected_revision(request)
            )
        except RevisionConflict as exc:
            return _conflict_response(exc)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class ResolvedFloorPlanView(views.APIView):
    """Resolve the effective map for a Location."""

    queryset = Location.objects.all()
    serializer_class = ResolvedFloorPlanSerializer

    def get(self, request, location_id):
        location = Location.objects.get(pk=location_id)
        if not request.user.has_perm("dcim.view_location", location):
            self.permission_denied(request)
        return response.Response(renderer_payload(location, user=request.user))
