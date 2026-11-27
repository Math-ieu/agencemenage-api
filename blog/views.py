from rest_framework import viewsets, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import Category, Post
from .serializers import CategorySerializer, PostListSerializer, PostSerializer


def _user_blog_perms(user):
    if not user or not user.is_authenticated:
        return set()
    if user.role == "admin":
        return {"rediger_blog", "modifier_articles_blog", "publier_articles_blog", "parametres_globaux"}
    from accounts.models import RolePermission
    from accounts.permissions import AIRBNB_ONLY_ROLES, map_role_to_db_key
    if user.role in AIRBNB_ONLY_ROLES:
        return set()
    rp = RolePermission.objects.filter(role=map_role_to_db_key(user.role)).first()
    return set(rp.permissions if rp else [])


class BlogPermission(permissions.BasePermission):
    """Lecture publique pour les endpoints GET; écriture restreinte aux rôles disposant des droits blog."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.role == "admin":
            return True

        perms = _user_blog_perms(user)
        if not perms:
            return False

        action = getattr(view, "action", None)
        if action == "create" or request.method == "POST":
            if request.data.get("status") == Post.PUBLISHED and "publier_articles_blog" not in perms:
                return False
            return bool(perms & {"rediger_blog", "modifier_articles_blog", "publier_articles_blog"})

        if action in ("update", "partial_update") or request.method in ("PUT", "PATCH"):
            if request.data.get("status") == Post.PUBLISHED and "publier_articles_blog" not in perms:
                return False
            return bool(perms & {"rediger_blog", "modifier_articles_blog", "publier_articles_blog"})

        if action == "destroy" or request.method == "DELETE":
            return bool(perms & {"modifier_articles_blog", "publier_articles_blog", "parametres_globaux"})

        return False


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [BlogPermission]
    lookup_field = "slug"


class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.all()
    permission_classes = [BlogPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "category", "author"]
    search_fields = ["title", "excerpt", "content"]
    ordering_fields = ["created_at", "published_at", "title"]
    lookup_field = "slug"

    def get_serializer_class(self):
        if self.action == "list":
            return PostListSerializer
        return PostSerializer

    def get_queryset(self):
        user = self.request.user
        if user and user.is_authenticated:
            perms = _user_blog_perms(user)
            if (
                user.is_staff
                or user.role == "admin"
                or bool(perms & {"rediger_blog", "modifier_articles_blog", "publier_articles_blog"})
            ):
                return Post.objects.all()
        return Post.objects.filter(status=Post.PUBLISHED)
