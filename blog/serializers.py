from rest_framework import serializers
from .models import Category, Post, Tag, PostImage
from django.contrib.auth import get_user_model

User = get_user_model()


class AuthorSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "full_name"]


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug"]


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "slug"]


class PostImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostImage
        fields = ["id", "image", "alt", "caption", "order"]


class PostListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    author_name = serializers.CharField(source="author.full_name", read_only=True)
    tags = TagSerializer(many=True, read_only=True)

    class Meta:
        model = Post
        fields = [
            "id",
            "title",
            "slug",
            "excerpt",
            "category",
            "category_name",
            "status",
            "featured_image",
            "banner_color",
            "tags",
            "author_name",
            "published_at",
            "created_at",
        ]


class PostSerializer(serializers.ModelSerializer):
    category_details = CategorySerializer(source="category", read_only=True)
    author_details = AuthorSerializer(source="author", read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    gallery = PostImageSerializer(many=True, read_only=True)

    class Meta:
        model = Post
        fields = "__all__"
        read_only_fields = ["slug", "author", "published_at", "created_at", "updated_at"]

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user:
            validated_data["author"] = request.user
        return super().create(validated_data)
