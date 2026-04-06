import os
import re
import shutil
import json
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from django.core.files import File
from django.conf import settings
from blog.models import Post, Category, Tag, PostImage
from django.contrib.auth import get_user_model

User = get_user_model()

class Command(BaseCommand):
    help = 'Import blog posts from agence-menage-v2 static data'

    def handle(self, *args, **options):
        # Paths
        base_dir = '/home/mathdev/Works/agencemenage'
        v2_data_path = os.path.join(base_dir, 'agence-menage-v2/src/data/blogData.ts')
        v2_assets_path = os.path.join(base_dir, 'agence-menage-v2/src/assets/blog')
        
        if not os.path.exists(v2_data_path):
            self.stdout.write(self.style.ERROR(f'Data file not found at {v2_data_path}'))
            return

        with open(v2_data_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 1. Parse imports to map variable names to filenames
        image_map = {}
        import_matches = re.finditer(r'import\s+(\w+)\s+from\s+"@/assets/blog/(.*?)"', content)
        for match in import_matches:
            var_name = match.group(1)
            filename = match.group(2)
            image_map[var_name] = filename
            # self.stdout.write(f'Mapped {var_name} -> {filename}')

        # 2. Extract blogPosts array content
        array_match = re.search(r'export const blogPosts: BlogPost\[\] = \[(.*?)\];', content, re.DOTALL)
        if not array_match:
            self.stdout.write(self.style.ERROR('Could not find blogPosts array'))
            return
        
        posts_raw = array_match.group(1)

        # 3. Split into individual post objects
        # Using a more robust regex for objects { ... }
        post_blocks = []
        depth = 0
        current_block = ""
        for char in posts_raw:
            if char == '{':
                depth += 1
            if depth > 0:
                current_block += char
            if char == '}':
                depth -= 1
                if depth == 0:
                    post_blocks.append(current_block)
                    current_block = ""

        self.stdout.write(f'Found {len(post_blocks)} potential posts')

        # Get or create a default author
        author = User.objects.filter(is_superuser=True).first()
        if not author:
            author = User.objects.create_superuser('admin', 'admin@example.com', 'adminpass')

        for block in post_blocks:
            # Helper to extract field value
            def get_field(name, is_string=True):
                if is_string:
                    m = re.search(rf'{name}:\s*"(.*?)"', block)
                    if m: return m.group(1)
                    m = re.search(rf"{name}:\s*'(.*?)'", block) # for single quotes
                    return m.group(1) if m else None
                else:
                    m = re.search(rf'{name}:\s*(\w+)', block)
                    if m: return m.group(1)
                    m = re.search(rf'{name}:\s*`(.*?)`', block, re.DOTALL)
                    if m: return m.group(1)
                    return None

            title = get_field('title')
            slug = get_field('slug')
            excerpt = get_field('excerpt') or get_field('description')
            category_str = get_field('category')
            full_content = get_field('fullContent', is_string=False)
            image_var = get_field('imageUrl', is_string=False)
            banner_color = get_field('bannerColor') or "#BCC6D0"

            if not title or not slug:
                continue

            self.stdout.write(f'Processing: {title}')

            # Category
            cat_name = "Particuliers" if category_str == "particulier" else "Entreprises"
            category, _ = Category.objects.get_or_create(name=cat_name)

            # Create or update Post
            post, created = Post.objects.update_or_create(
                slug=slug,
                defaults={
                    'title': title,
                    'content': full_content or "",
                    'excerpt': excerpt or "",
                    'category': category,
                    'status': Post.PUBLISHED,
                    'author': author,
                    'banner_color': banner_color
                }
            )

            # Tags
            tags_match = re.search(r'tags:\s*\[(.*?)\]', block, re.DOTALL)
            if tags_match:
                tag_list = re.findall(r'"(.*?)"', tags_match.group(1))
                if not tag_list:
                    tag_list = re.findall(r"'(.*?)'", tags_match.group(1))
                
                post.tags.clear()
                for tag_name in tag_list:
                    tag, _ = Tag.objects.get_or_create(name=tag_name)
                    post.tags.add(tag)

            # Services (JSON)
            services_match = re.search(r'services:\s*\[(.*?)\]', block, re.DOTALL)
            if services_match:
                services_raw = services_match.group(1)
                service_items = re.findall(r'\{\s*name:\s*"(.*?)",\s*url:\s*"(.*?)",\s*ctaLabel:\s*"(.*?)"\s*\}', services_raw)
                post.related_services = [
                    {"name": name, "url": url, "ctaLabel": cta} 
                    for name, url, cta in service_items
                ]
                post.save()

            # Handle Main Image
            if image_var in image_map:
                filename = image_map[image_var]
                src_path = os.path.join(v2_assets_path, filename)
                if os.path.exists(src_path):
                    with open(src_path, 'rb') as img_file:
                        post.featured_image.save(filename, File(img_file), save=True)
                else:
                    self.stdout.write(self.style.WARNING(f'  Main image file not found: {src_path}'))

            # Gallery
            gallery_match = re.search(r'gallery:\s*\[(.*?)\]', block, re.DOTALL)
            if gallery_match:
                gallery_raw = gallery_match.group(1)
                # Find all objects { src: ..., alt: ..., caption: ... }
                # Note: src here is a variable name, alt and caption are strings
                gallery_items = re.findall(r'\{\s*src:\s*(\w+),\s*alt:\s*"(.*?)",\s*caption:\s*"(.*?)"\s*\}', gallery_raw)
                
                post.gallery.all().delete() # Clear existing
                for i, (src_var, alt, caption) in enumerate(gallery_items):
                    if src_var in image_map:
                        filename = image_map[src_var]
                        src_path = os.path.join(v2_assets_path, filename)
                        if os.path.exists(src_path):
                            with open(src_path, 'rb') as img_file:
                                img_obj = PostImage(
                                    post=post,
                                    alt=alt,
                                    caption=caption,
                                    order=i
                                )
                                img_obj.image.save(filename, File(img_file), save=True)

        self.stdout.write(self.style.SUCCESS('Import and synchronization completed!'))
