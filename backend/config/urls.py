from django.db import connections
from django.db.utils import OperationalError
from django.urls import include, path
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    database_ready = True
    try:
        connections["default"].ensure_connection()
    except OperationalError:
        database_ready = False
    response_status = status.HTTP_200_OK if database_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return Response(
        {
            "status": "ok" if database_ready else "not_ready",
            "checks": {
                "application": "ok",
                "database": "ready" if database_ready else "unavailable",
            },
        },
        status=response_status,
    )


urlpatterns = [
    path("api/health/", health, name="health"),
    path("api/auth/", include("backend.accounts.urls")),
    path("api/workspaces/", include("backend.workspaces.urls")),
    path("api/problems/", include("backend.catalogue.urls")),
]
