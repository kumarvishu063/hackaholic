"""Standard pagination class used by every list endpoint."""

from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """Page-number pagination with a configurable page size.

    Usage:  ?page=2&page_size=12
    """

    page_size = 9
    page_size_query_param = "page_size"
    max_page_size = 50
