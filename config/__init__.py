import re
import django.utils.cache

# Django 5.0+ compatibility patch for older djangorestframework versions
if not hasattr(django.utils.cache, 'cc_delim_re'):
    django.utils.cache.cc_delim_re = re.compile(r'\s*,\s*')
