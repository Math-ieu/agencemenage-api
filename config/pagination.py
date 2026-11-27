from rest_framework.pagination import PageNumberPagination


class CustomPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 1000

    def _is_internal_staff(self, request) -> bool:
        user = getattr(request, 'user', None)
        return bool(
            user
            and getattr(user, 'is_authenticated', False)
            and getattr(user, 'role', None) != 'client_conciergerie'
        )

    def get_page_size(self, request):
        size = super().get_page_size(request)
        if size is not None and not self._is_internal_staff(request):
            return min(size, 100)
        return size

    def paginate_queryset(self, queryset, request, view=None):
        if request.query_params.get('no_page') == 'true' and self._is_internal_staff(request):
            return None
        return super().paginate_queryset(queryset, request, view)
