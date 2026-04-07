import os
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

        with transaction.atomic():
            # Fix Post featured_image
            posts = Post.objects.exclude(featured_image='')
            for post in posts:
                current_name = post.featured_image.name
                match = find_best_match(current_name)
                if match and match != current_name:
                    self.stdout.write(self.style.SUCCESS(f'Post "{post.title}": {current_name} -> {match}'))
                    post.featured_image.name = match
                    post.save(update_fields=['featured_image'])
                elif not match and current_name not in bucket_keys:
                    self.stdout.write(self.style.WARNING(f'Post "{post.title}": No match found for {current_name}'))

            # Fix PostImage images
            images = PostImage.objects.all()
            for pi in images:
                current_name = pi.image.name
                match = find_best_match(current_name)
                if match and match != current_name:
                    self.stdout.write(self.style.SUCCESS(f'PostImage (Post: {pi.post.title}): {current_name} -> {match}'))
                    pi.image.name = match
                    pi.save(update_fields=['image'])
                elif not match and current_name not in bucket_keys:
                    self.stdout.write(self.style.WARNING(f'PostImage (Post: {pi.post.title}): No match found for {current_name}'))

        self.stdout.write(self.style.SUCCESS('Finished fixing media paths.'))
