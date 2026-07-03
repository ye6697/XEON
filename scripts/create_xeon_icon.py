from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sizes = [16, 24, 32, 48, 64, 128, 256]
images = []
for size in sizes:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    corner = max(4, int(size * 0.22))
    draw.rounded_rectangle((1, 1, size - 2, size - 2), radius=corner, fill=(9, 5, 8, 255))
    draw.rounded_rectangle(
        (1, 1, size - 2, size - 2),
        radius=corner,
        outline=(255, 63, 86, 150),
        width=max(1, size // 28),
    )

    center = (size * 0.5, size * 0.48)
    max_radius = int(size * 0.38)
    for radius in range(max_radius, 0, -1):
        t = radius / max_radius
        alpha = int(28 + (1 - t) * 150)
        red = int(255 - t * 55)
        green = int(35 + (1 - t) * 35)
        blue = int(58 + (1 - t) * 30)
        draw.ellipse(
            (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius),
            fill=(red, green, blue, alpha),
        )

    draw.arc(
        (size * 0.19, size * 0.18, size * 0.81, size * 0.8),
        start=205,
        end=515,
        fill=(255, 210, 216, 210),
        width=max(1, size // 18),
    )
    draw.line(
        (size * 0.28, size * 0.72, size * 0.72, size * 0.28),
        fill=(255, 238, 241, 235),
        width=max(2, size // 12),
    )
    draw.line(
        (size * 0.31, size * 0.29, size * 0.7, size * 0.7),
        fill=(255, 77, 101, 230),
        width=max(2, size // 14),
    )

    try:
        font = ImageFont.truetype("arialbd.ttf", max(7, int(size * 0.13)))
    except OSError:
        font = ImageFont.load_default()
    text = "XEON"
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text(
        ((size - (bbox[2] - bbox[0])) / 2, size * 0.77),
        text,
        font=font,
        fill=(255, 205, 212, 230),
    )
    images.append(image)

Path("assets").mkdir(exist_ok=True)
images[-1].save("assets/xeon.ico", sizes=[(size, size) for size in sizes], append_images=images[:-1])
print("assets/xeon.ico")
