import json
import logging
from django.http import JsonResponse
from django.urls import resolve, Resolver404



logger = logging.getLogger(__name__)



class RequestResponseLoggingMiddleware:
    """
    Middleware that logs incoming requests and outgoing API responses.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._log_request(request)

        response = self.get_response(request)

        self._log_response(request, response)

        return response

    def _log_request(self, request):
        url = request.get_full_path()
        method = request.method

        auth_header = (
            request.headers.get("authorization")
            or request.headers.get("Authorization")
            or request.META.get("HTTP_AUTHORIZATION")
        )
        auth_display = auth_header if auth_header else "No Authorization header"

        # Safely log params (URL route parameters / kwargs)
        params = {}
        try:
            resolver_match = getattr(request, "resolver_match", None) or resolve(request.path_info)
            if resolver_match and resolver_match.kwargs:
                params = resolver_match.kwargs
        except (Resolver404, Exception):
            params = {}

        params_display = (
            json.dumps(params, indent=2, default=str)
            if params and len(params) > 0
            else "No params"
        )

        # Safely log query parameters
        query = request.GET.dict()
        query_display = (
            json.dumps(query, indent=2, default=str)
            if query and len(query) > 0
            else "No query parameters"
        )

        # Log form data specifically if content-type indicates it
        content_type = request.content_type or request.headers.get("Content-Type", "") or request.META.get("CONTENT_TYPE", "")
        content_length = request.headers.get("Content-Length") or request.META.get("CONTENT_LENGTH") or "unknown"

        body_lines = []
        is_form_data = (
            "application/x-www-form-urlencoded" in content_type
            or "multipart/form-data" in content_type
        )

        if is_form_data:
            body_lines.append(f"Content-Length: {content_length}")

            form_data = {}
            if hasattr(request, "POST") and request.POST:
                form_data.update(request.POST.dict())
            if hasattr(request, "FILES") and request.FILES:
                for field_name, file_obj in request.FILES.items():
                    form_data[field_name] = f"[File: {file_obj.name}, size: {file_obj.size} bytes]"

            if form_data:
                form_data_str = json.dumps(form_data, indent=2, default=str)
                body_lines.append(f"Request Form Data (Body): {form_data_str}")
            elif "multipart/form-data" in content_type:
                body_lines.append("Request Form Data (Body): Multipart body not parsed yet (handled by parser on upload routes)")
            else:
                body_lines.append("Request Form Data (Body): No form data received")
        else:
            # Safely log other request body types (like JSON)
            body_content = None
            try:
                if request.body:
                    try:
                        parsed_body = json.loads(request.body.decode("utf-8"))
                        body_content = json.dumps(parsed_body, indent=2, default=str)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        body_content = request.body.decode("utf-8", errors="replace")
            except Exception:
                body_content = None

            if body_content:
                body_lines.append(f"Request Body: {body_content}")
            else:
                body_lines.append("Request Body: No body received")

        # Assemble log block
        log_parts = [
            "\n,"
            "=== Incoming Request ===",
            f"URL: {url}",
            f"Method: {method}",
            f"Authorization: {auth_display}",
            f"Request params: {params_display}",
            f"Request query: {query_display}",
            *body_lines,
            "========================"
        ]

        logger.info("\n".join(log_parts))

    def _log_response(self, request, response):
        url = request.get_full_path()
        status_code = getattr(response, "status_code", "unknown")

        response_display = "Empty response"
        if getattr(response, "streaming", False):
            response_display = "[Streaming response]"
        elif hasattr(response, "content") and response.content:
            try:
                content_text = response.content.decode("utf-8")
                if not content_text.strip():
                    response_display = "Empty response"
                else:
                    try:
                        parsed_json = json.loads(content_text)
                        response_display = json.dumps(parsed_json, indent=2, default=str)
                    except (json.JSONDecodeError, ValueError):
                        content_type = response.get("Content-Type", "")
                        if "application/json" in content_type:
                            response_display = "[Non-serializable data]"
                        else:
                            response_display = (
                                content_text
                                if len(content_text) <= 500
                                else f"{content_text[:500]}... [truncated]"
                            )
            except Exception:
                response_display = "[Non-serializable data]"

        log_parts = [
            "\n,"
            "=== API Response ===",
            f"URL: {url}",
            f"Status: {status_code}",
            f"Response: {response_display}",
            "========================"
        ]

        logger.info("\n".join(log_parts))