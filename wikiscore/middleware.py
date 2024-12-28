from django.shortcuts import render
import traceback

class GlobalExceptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            response = self.get_response(request)
            return response
        except AttributeError as e:
            tb = traceback.format_exc()
            if "'NoneType' object has no attribute 'settimeout'" in str(e) and "pymysql" in tb:
                # Return a 503 Service Unavailable response
                response = render(request, '503.html', status=503)
            else:
                raise
        return response
