import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

ALLOWED_TAGS = {
    'p', 'br', 'strong', 'b', 'em', 'i', 'u', 's',
    'ul', 'ol', 'li',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'blockquote', 'a', 'img', 'span', 'div', 'hr',
    'pre', 'code',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
}

VOID_TAGS = {'br', 'hr', 'img'}

DROP_CONTENT_TAGS = {
    'script', 'style', 'iframe', 'object', 'embed',
    'svg', 'math', 'noscript', 'template', 'form',
}

SAFE_HREF_SCHEMES = {'http', 'https', 'mailto', 'tel'}
SAFE_SRC_SCHEMES = {'http', 'https'}
SAFE_CLASS_RE = re.compile(r'^[A-Za-z0-9 _-]+$')


def _is_safe_url(value: str, allowed_schemes: set) -> bool:
    if not value:
        return False
    cleaned = value.strip()
    if any(ord(c) < 32 for c in cleaned):
        return False
    if cleaned.startswith('/'):
        return not cleaned.startswith('//')
    parsed = urlsplit(cleaned)
    return parsed.scheme.lower() in allowed_schemes


class _BlogHTMLSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._drop_depth = 0
        self._open_tags = []

    def handle_starttag(self, tag, attrs):
        tag_l = tag.lower()
        if tag_l in DROP_CONTENT_TAGS:
            self._drop_depth += 1
            return
        if self._drop_depth > 0 or tag_l not in ALLOWED_TAGS:
            return

        sanitized_attrs = []
        has_blank_target = False
        for k, v in attrs:
            if v is None:
                continue
            attr_l = k.lower().strip()
            val = v.strip()
            if attr_l.startswith('on') or attr_l in {'style', 'srcdoc', 'formaction'}:
                continue

            if tag_l == 'a' and attr_l == 'href':
                if _is_safe_url(val, SAFE_HREF_SCHEMES):
                    sanitized_attrs.append(('href', val))
            elif tag_l == 'a' and attr_l == 'target':
                if val in {'_blank', '_self'}:
                    sanitized_attrs.append(('target', val))
                    if val == '_blank':
                        has_blank_target = True
            elif tag_l == 'img' and attr_l == 'src':
                if _is_safe_url(val, SAFE_SRC_SCHEMES):
                    sanitized_attrs.append(('src', val))
            elif attr_l in {'alt', 'title'}:
                sanitized_attrs.append((attr_l, val))
            elif attr_l == 'class' and SAFE_CLASS_RE.match(val):
                sanitized_attrs.append(('class', val))

        if has_blank_target:
            sanitized_attrs.append(('rel', 'noopener noreferrer'))

        attr_str = ''.join(
            f' {k}="{html.escape(v, quote=True)}"' for k, v in sanitized_attrs
        )
        if tag_l in VOID_TAGS:
            self.parts.append(f'<{tag_l}{attr_str}>')
        else:
            self.parts.append(f'<{tag_l}{attr_str}>')
            self._open_tags.append(tag_l)

    def handle_startendtag(self, tag, attrs):
        tag_l = tag.lower()
        if tag_l in DROP_CONTENT_TAGS:
            return
        if tag_l in VOID_TAGS:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag_l = tag.lower()
        if tag_l in DROP_CONTENT_TAGS:
            if self._drop_depth > 0:
                self._drop_depth -= 1
            return
        if self._drop_depth > 0 or tag_l not in ALLOWED_TAGS or tag_l in VOID_TAGS:
            return
        if tag_l in self._open_tags:
            while self._open_tags:
                top = self._open_tags.pop()
                self.parts.append(f'</{top}>')
                if top == tag_l:
                    break

    def handle_data(self, data):
        if self._drop_depth > 0:
            return
        self.parts.append(html.escape(data, quote=False))

    def get_sanitized(self) -> str:
        while self._open_tags:
            self.parts.append(f'</{self._open_tags.pop()}>')
        return ''.join(self.parts)


def sanitize_blog_html(raw_html: str) -> str:
    """Sanitise le contenu HTML d'un article tout en conservant le texte brut/Markdown intact."""
    if not raw_html or not isinstance(raw_html, str):
        return raw_html or ''
    # Preserve plain-text/Markdown blog mode (used when content doesn't start with '<')
    if not raw_html.lstrip().startswith('<'):
        return raw_html
    parser = _BlogHTMLSanitizer()
    parser.feed(raw_html)
    parser.close()
    return parser.get_sanitized()
