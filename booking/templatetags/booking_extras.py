from django import template
from django.templatetags.static import static
import re

register = template.Library()

DEMO_ROOM_IMAGE_RE = re.compile(r"(?:^|/)(?:room|hotel)/room-([1-5])(?:_[^.]+)?\.(?:jpe?g|png|jfif|webp)$", re.IGNORECASE)


@register.filter(name="trim")
def trim(value):
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:
        return value


@register.filter(name="media_image_url")
def media_image_url(value):
    if not value:
        return ""

    name = getattr(value, "name", "") or str(value)
    normalized_name = name.replace("\\", "/").strip()

    match = DEMO_ROOM_IMAGE_RE.search(normalized_name)
    if match:
        return static(f"img/room/room-{match.group(1)}.jpg")

    if normalized_name.lower().endswith("/logo.png.jfif") or normalized_name.lower() == "logo.png.jfif":
        return static("img/logo.jpg")

    try:
        return value.url
    except Exception:
        return ""
