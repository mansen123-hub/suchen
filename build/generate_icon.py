from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    size = 256
    image = Image.new("RGBA", (size, size), "#14213d")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((18, 18, 238, 238), radius=44, fill="#14213d", outline="#4f8cff", width=9)
    draw.rounded_rectangle((61, 42, 179, 211), radius=12, fill="white")
    draw.polygon([(145, 42), (179, 76), (145, 76)], fill="#cbd5e1")
    for y, width in ((99, 78), (123, 78), (147, 54)):
        draw.rounded_rectangle((81, y, 81 + width, y + 9), radius=4, fill="#94a3b8")
    draw.ellipse((126, 132, 219, 225), fill="#2563eb", outline="white", width=7)
    draw.ellipse((146, 152, 189, 195), outline="white", width=9)
    draw.line((184, 190, 207, 213), fill="white", width=11)
    target = Path(__file__).with_name("app.ico")
    image.save(target, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()

