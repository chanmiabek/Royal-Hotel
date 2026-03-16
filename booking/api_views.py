from django.http import JsonResponse

from .jwt_auth import jwt_required


@jwt_required
def jwt_me(request):
    return JsonResponse({"claims": getattr(request, "jwt_claims", {})})

