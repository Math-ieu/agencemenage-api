import re
from rest_framework import serializers
from django.contrib.auth import get_user_model
from agencemenage.validators import validate_uploaded_image
from .models import Category, Post, Tag, PostImage
from .sanitizer import sanitize_blog_html

User = get_user_model()
HEX_COLOR_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')


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
    
    # Write-only fields for complex related data
    tag_names = serializers.ListField(
        child=serializers.CharField(max_length=50),
        write_only=True,
        required=False
    )

    class Meta:
        model = Post
        fields = "__all__"
        read_only_fields = ["slug", "author", "published_at", "created_at", "updated_at"]

    def validate_content(self, value):
        return sanitize_blog_html(value)

    def validate_featured_image(self, value):
        if value:
            validate_uploaded_image(value)
        return value

    def validate_banner_color(self, value):
        if value and not HEX_COLOR_RE.match(value.strip()):
            raise serializers.ValidationError("La couleur de bannière doit être au format hexadécimal #RRGGBB.")
        return value

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if data.get("content"):
            data["content"] = sanitize_blog_html(data["content"])
        return data

    def _validate_gallery_files(self, request):
        if not request or not request.FILES:
            return []
        gallery_files = request.FILES.getlist('gallery_files')
        if len(gallery_files) > 20:
            raise serializers.ValidationError({"gallery_files": "Maximum 20 images autorisées par envoi."})
        for f in gallery_files:
            validate_uploaded_image(f)
        return gallery_files

    def create(self, validated_data):
        tag_names = validated_data.pop("tag_names", [])
        request = self.context.get("request")
        gallery_files = self._validate_gallery_files(request)
        if request and request.user:
            validated_data["author"] = request.user
        
        post = super().create(validated_data)
        
        # Handle tags
        for name in tag_names:
            tag, _ = Tag.objects.get_or_create(name=name)
            post.tags.add(tag)
            
        # Handle gallery images from request.FILES
        for f in gallery_files:
            PostImage.objects.create(post=post, image=f)

        return post

    def update(self, instance, validated_data):
        tag_names = validated_data.pop("tag_names", None)
        request = self.context.get("request")
        gallery_files = self._validate_gallery_files(request)
        
        post = super().update(instance, validated_data)
        
        if tag_names is not None:
            post.tags.clear()
            for name in tag_names:
                tag, _ = Tag.objects.get_or_create(name=name)
                post.tags.add(tag)
        
        # Handle gallery updates (targeted addition and removal)
        if request:
            # 1. Remove specific images if delete_ids provided
            delete_ids = request.data.getlist('delete_gallery_ids') if hasattr(request.data, 'getlist') else request.data.get('delete_gallery_ids', [])
            if delete_ids:
                instance.gallery.filter(id__in=delete_ids).delete()
            
            # 2. Add new files from gallery_files
            for f in gallery_files:
                PostImage.objects.create(post=instance, image=f)
                
        return post
