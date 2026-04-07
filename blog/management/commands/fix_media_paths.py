import os
import re
from django.core.management.base import BaseCommand
from blog.models import Post, PostImage
from django.db import transaction

class Command(BaseCommand):
    help = 'Fixes blog image paths by matching database references with actual S3 keys'

    def handle(self, *args, **options):
        keys_file = '/tmp/bucket_keys.txt'
        if not os.path.exists(keys_file):
            self.stdout.write(self.style.ERROR(f'Keys file {keys_file} not found. Please run the S3 listing script first.'))
            return

        with open(keys_file, 'r') as f:
            bucket_keys = [line.strip() for line in f.readlines() if line.strip()]

        self.stdout.write(f'Loaded {len(bucket_keys)} keys from bucket.')

        def find_best_match(current_path):
            if not current_path:
                return None
            
            # If already correct, return it
            if current_path in bucket_keys:
                return current_path
            
            # Try to find a match with suffix
            # Pattern: blog/gallery/2026/04/name.jpg -> blog/gallery/2026/04/name_SUFFIX.jpg
            base, ext = os.path.splitext(current_path)
            
            # Look for keys that start with "base_" and end with "ext"
            matches = [k for k in bucket_keys if k.startswith(f"{base}_") and k.endswith(ext)]
            
            if matches:
                # Return the shortest match or first one
                return sorted(matches, key=len)[0]
            
            return None

        def fix_html_content(html):
            if not html:
                return html
            
            # Find all image sources that match our proxy pattern
            # Pattern: src="/api/media/path/to/image.jpg"
            pattern = r'src="/api/media/(.+?)"'
            
            new_html = html
            found_matches = re.finditer(pattern, html)
            
            # We use a set of replacements to avoid redundant work and overlapping replacements
            replacements = {}
            
            for match in found_matches:
                path_in_html = match.group(1)
                
                better_path = find_best_match(path_in_html)
                if better_path and better_path != path_in_html:
                    old_url = f'/api/media/{path_in_html}'
                    new_url = f'/api/media/{better_path}'
                    replacements[old_url] = new_url
            
            for old_url, new_url in replacements.items():
                self.stdout.write(self.style.SUCCESS(f'  HTML replacement: {old_url} -> {new_url}'))
                new_html = new_html.replace(old_url, new_url)
            
            return new_html

        with transaction.atomic():
            # Fix Post featured_image and content
            posts = Post.objects.all()
            for post in posts:
                updated = False
                
                # 1. Fix featured_image
                if post.featured_image:
                    current_name = post.featured_image.name
                    match = find_best_match(current_name)
                    if match and match != current_name:
                        self.stdout.write(self.style.SUCCESS(f'Post "{post.title}" (featured): {current_name} -> {match}'))
                        post.featured_image.name = match
                        updated = True
                
                # 2. Fix content HTML
                if post.content:
                    new_content = fix_html_content(post.content)
                    if new_content != post.content:
                        self.stdout.write(self.style.SUCCESS(f'Post "{post.title}" (content updated)'))
                        post.content = new_content
                        updated = True
                
                if updated:
                    post.save()

            # Fix PostImage images
            images = PostImage.objects.all()
            for pi in images:
                current_name = pi.image.name
                match = find_best_match(current_name)
                if match and match != current_name:
                    self.stdout.write(self.style.SUCCESS(f'PostImage (Post: {pi.post.title}): {current_name} -> {match}'))
                    pi.image.name = match
                    pi.save(update_fields=['image'])

        self.stdout.write(self.style.SUCCESS('Finished fixing media paths.'))
