import random
from django.db import models
from django.conf import settings
from django.utils.text import slugify
from django.utils import timezone


# Vibrant color palette for article cards (8 colors for cyclic assignment)
POST_BANNER_COLORS = [
    "#93C5FD", # Blue
    "#FDBA74", # Orange
    "#C4B5FD", # Purple
    "#6EE7B7", # Green
    "#FCA5A5", # Pink
    "#FDE68A", # Yellow
    "#67E8F9", # Sky
    "#A5B4FC"  # Indigo
]


class Tag(models.Model):
    name = models.CharField(max_length=50)
    slug = models.SlugField(max_length=70, unique=True)

    class Meta:
        verbose_name = "Tag"
        verbose_name_plural = "Tags"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True)

    class Meta:
        verbose_name = "Catégorie"
        verbose_name_plural = "Catégories"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Post(models.Model):
    DRAFT = "draft"
    PUBLISHED = "published"
    STATUS_CHOICES = [
        (DRAFT, "Brouillon"),
        (PUBLISHED, "Publié"),
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=250, unique=True)
    content = models.TextField()  # Tiptap JSON or HTML
    excerpt = models.TextField(blank=True)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, related_name="posts"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    featured_image = models.ImageField(upload_to="blog/%Y/%m/", blank=True, null=True)
    banner_color = models.CharField(max_length=20, default="#BCC6D0")
    tags = models.ManyToManyField(Tag, blank=True, related_name="posts")
    related_services = models.JSONField(default=list, blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="blog_posts",
    )
    
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Article"
        verbose_name_plural = "Articles"
        ordering = ["-published_at", "-created_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        
        if self.status == self.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()

        # Assign a cyclic color if it's default or empty
        if self.banner_color == "#BCC6D0" or not self.banner_color:
            # Get the number of existing posts to determine the next color in the cycle
            count = Post.objects.count()
            self.banner_color = POST_BANNER_COLORS[count % len(POST_BANNER_COLORS)]
            
        super().save(*args, **kwargs)

        # After saving, check for tags (cannot handle M2M before save)
        # We can't really do this here because it might overwrite user intent on first save
        # So we'll handle this in the management command for existing posts


class PostImage(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="gallery")
    image = models.ImageField(upload_to="blog/gallery/%Y/%m/")
    alt = models.CharField(max_length=255, blank=True)
    caption = models.CharField(max_length=255, blank=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Image de Galerie"
        verbose_name_plural = "Images de Galerie"
        ordering = ["order", "created_at"]

    def __str__(self):
        return f"Image for {self.post.title}"
