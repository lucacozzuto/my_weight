import os
from PIL import Image, ImageDraw

def create_icon():
    sizes = {
        "docs/icon.png": (512, 512),
        "docs/icon-192.png": (192, 192),
        "android/app/src/main/res/mipmap-mdpi/ic_launcher.png": (48, 48),
        "android/app/src/main/res/mipmap-hdpi/ic_launcher.png": (72, 72),
        "android/app/src/main/res/mipmap-xhdpi/ic_launcher.png": (96, 96),
        "android/app/src/main/res/mipmap-xxhdpi/ic_launcher.png": (144, 144),
        "android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png": (192, 192),
    }

    # Generate master 512x512
    dim = 512
    img = Image.new("RGBA", (dim, dim), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded rectangle background
    # Colors: dark surface (#0f172a = 15, 23, 42)
    # Brand indigo border (#6366f1 = 99, 102, 241)
    radius = 110
    draw.rounded_rectangle([(16, 16), (dim - 16, dim - 16)], radius=radius, fill=(15, 23, 42, 255), outline=(99, 102, 241, 255), width=14)

    # Stylized weight scale / analytics icon
    # Scale body: base plate
    draw.rounded_rectangle([(110, 160), (dim - 110, dim - 120)], radius=45, fill=(30, 41, 59, 255), outline=(129, 140, 248, 200), width=8)

    # Display window at the top of the scale
    draw.rounded_rectangle([(180, 200), (dim - 180, 290)], radius=20, fill=(2, 6, 23, 255), outline=(79, 70, 229, 255), width=6)
    
    # Glowing digital display bar / heartrate-like trend
    # Color emerald / cyan (#10b981 / #06b6d4)
    points = [
        (205, 250),
        (230, 250),
        (245, 225),
        (260, 265),
        (275, 235),
        (290, 250),
        (307, 250)
    ]
    draw.line(points, fill=(16, 185, 129, 255), width=6, joint="curve")

    # Lower footpads or subtle decor
    draw.ellipse([(140, 320), (170, 350)], fill=(99, 102, 241, 200))
    draw.ellipse([(dim - 170, 320), (dim - 140, 350)], fill=(99, 102, 241, 200))
    
    # Save across all resolutions
    for path, (w, h) in sizes.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        resized = img.resize((w, h), Image.Resampling.LANCZOS)
        resized.save(path, "PNG")
        print(f"Generated {path} ({w}x{h})")

if __name__ == "__main__":
    create_icon()
