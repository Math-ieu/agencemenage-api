import random
from django.core.management.base import BaseCommand
from blog.models import Post, Tag, POST_BANNER_COLORS

class Command(BaseCommand):
    help = 'Assign vibrant colors and default tags to blog posts that are missing them'

    def handle(self, *args, **options):
        # Ordered by creation (ID or published_at)
        posts = Post.objects.all().order_by('id')
        self.stdout.write(f'Scanning {posts.count()} articles for cyclic sync...')

        # Get or create common tags
        menage_tag, _ = Tag.objects.get_or_create(name='Ménage', slug='menage')
        conseils_tag, _ = Tag.objects.get_or_create(name='Conseils', slug='conseils')
        pro_tag, _ = Tag.objects.get_or_create(name='Professionnel', slug='pro')

        updated_count = 0
        for index, post in enumerate(posts):
            changed = False
            
            # 1. Cyclic Colors - assign even if already set, to ensure perfect order
            target_color = POST_BANNER_COLORS[index % len(POST_BANNER_COLORS)]
            if post.banner_color != target_color:
                post.banner_color = target_color
                changed = True
            
            # 2. Tags
            if post.tags.count() == 0:
                if (post.category and post.category.name == "Entreprises"):
                    post.tags.add(pro_tag, conseils_tag)
                else:
                    post.tags.add(menage_tag, conseils_tag)
                changed = True

            if changed:
                post.save()
                updated_count += 1
                self.stdout.write(f'  Updated aesthetics (Cyclic): {post.title} -> {post.banner_color}')

        self.stdout.write(self.style.SUCCESS(f'Successfully synchronized {updated_count} articles cyclically!'))
