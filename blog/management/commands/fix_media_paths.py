import os
import re
import boto3
from django.core.management.base import BaseCommand
from django.conf import settings
from blog.models import Post, PostImage
from django.db import transaction

class Command(BaseCommand):
    help = 'Fix media paths in Post and PostImage models to match S3'

    def handle(self, *args, **options):
        # 1. Get all keys from S3
        s3 = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            endpoint_url=settings.AWS_S3_ENDPOINT_URL
        )
        
        bucket_name = settings.AWS_STORAGE_BUCKET_NAME
        self.stdout.write(f'Fetching objects from bucket: {bucket_name}')
        
        s3_keys = []
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket_name):
            if 'Contents' in page:
                for obj in page['Contents']:
                    s3_keys.append(obj['Key'])
        
        self.stdout.write(f'Found {len(s3_keys)} objects in S3.')

        def find_best_match(current_path):
            if not current_path:
                return None
            
            # If already in S3, keep it
            if current_path in s3_keys:
                return current_path
            
            # Try to find a match ignoring Django's random suffixes
            # Example: blog/gallery/2026/04/image_X6NGaNQ.jpg -> blog/gallery/2026/04/image.jpg
            # Or vice versa.
            
            # Clean path: remove the suffix before the extension
            # Match pattern: _[7 alphanumeric characters] before extension
            clean_path = re.sub(r'_[a-zA-Z0-9]{7}(\.[a-zA-Z0-9]+)$', r'\1', current_path)
            
            matches = []
            for key in s3_keys:
                # Direct match with cleaned path
                if key == clean_path:
                    matches.append(key)
                # Or key matches if we clean the key too
                elif re.sub(r'_[a-zA-Z0-9]{7}(\.[a-zA-Z0-9]+)$', r'\1', key) == clean_path:
                    matches.append(key)
                # Or key contains the basename and is in same directory
                elif os.path.dirname(key) == os.path.dirname(current_path):
                    base_key = os.path.basename(re.sub(r'_[a-zA-Z0-9]{7}(\.[a-zA-Z0-9]+)$', r'\1', key))
                    base_curr = os.path.basename(clean_path)
                    if base_key == base_curr:
                        matches.append(key)

            if matches:
                # Return the shortest match or most "standard" one
                if clean_path in matches:
                    return clean_path
                return sorted(matches, key=len)[0]
            
            return None

        def fix_html_content(html):
            if not html:
                return html
            
            # Pattern: src="/api/media/path/to/image.jpg"
            pattern = r'src="/api/media/(.+?)"'
            
            new_html = html
            found_matches = re.finditer(pattern, html)
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

        # Fix Post featured_image and content
        posts = Post.objects.all()
        for post in posts:
            updates = {}
            if post.featured_image:
                current_name = post.featured_image.name
                match = find_best_match(current_name)
                if match and match != current_name:
                    self.stdout.write(self.style.SUCCESS(f'Post "{post.title}" (featured): {current_name} -> {match}'))
                    updates['featured_image'] = match

            if post.content:
                new_content = fix_html_content(post.content)
                if new_content != post.content:
                    self.stdout.write(self.style.SUCCESS(f'Post "{post.title}" (content updated)'))
                    updates['content'] = new_content
            
            if updates:
                Post.objects.filter(id=post.id).update(**updates)

        # Fix PostImage images
        images = PostImage.objects.all()
        for pi in images:
            current_name = pi.image.name
            match = find_best_match(current_name)
            if match and match != current_name:
                self.stdout.write(self.style.SUCCESS(f'PostImage (Post: {pi.post.title}): {current_name} -> {match}'))
                PostImage.objects.filter(id=pi.id).update(image=match)

        self.stdout.write(self.style.SUCCESS('Finished fixing media paths.'))
