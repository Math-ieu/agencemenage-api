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

    def create(self, validated_data):
        tag_names = validated_data.pop("tag_names", [])
        request = self.context.get("request")
        if request and request.user:
            validated_data["author"] = request.user
        
        post = super().create(validated_data)
        
        # Handle tags
        for name in tag_names:
            tag, _ = Tag.objects.get_or_create(name=name)
            post.tags.add(tag)
            
        # Handle gallery images from request.FILES
        if request and request.FILES:
            gallery_files = request.FILES.getlist('gallery_files')
            for f in gallery_files:
                PostImage.objects.create(post=post, image=f)

        return post

    def update(self, instance, validated_data):
        tag_names = validated_data.pop("tag_names", None)
        request = self.context.get("request")
        
        post = super().update(instance, validated_data)
        
        if tag_names is not None:
            post.tags.clear()
            for name in tag_names:
                tag, _ = Tag.objects.get_or_create(name=name)
                post.tags.add(tag)
        
        # Handle gallery updates (targeted addition and removal)
        if request:
            # 1. Remove specific images if delete_ids provided
            delete_ids = request.data.getlist('delete_gallery_ids')
            if delete_ids:
                instance.gallery.filter(id__in=delete_ids).delete()
            
            # 2. Add new files from gallery_files
            if request.FILES:
                gallery_files = request.FILES.getlist('gallery_files')
                for f in gallery_files:
                    PostImage.objects.create(post=instance, image=f)
                
        return post
