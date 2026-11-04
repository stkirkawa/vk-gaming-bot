from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "images"
SIZE = (960, 540)
PALETTES = {
    "old_ghetto": ("#f0a35e", "#40283b", "Old Ghetto Street", "СТАРЫЙ РАЙОН"),
    "business_ghetto": ("#5c9cf5", "#172b52", "Business Ghetto Street", "ДЕЛОВОЙ ЦЕНТР"),
    "new_ghetto": ("#e08045", "#3b3234", "New Ghetto Street", "ПРОМЫШЛЕННЫЙ РАЙОН"),
    "green_ghetto": ("#70c989", "#1b493d", "Green Ghetto Street", "ЗЕЛЁНЫЙ РАЙОН"),
}
TRANSPORTS = {
    "walk": ("#d5a4ff", "ПЕШКОМ", "Прогулка по городу"),
    "bus": ("#72c6e8", "ГОРОДСКОЙ АВТОБУС", "Маршрутный транспорт"),
    "taxi": ("#f4cb56", "ТАКСИ", "Поездка с комфортом"),
    "train": ("#c2b8a8", "ПОЕЗД", "Межрайонное сообщение"),
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    windows = Path("C:/Windows/Fonts")
    candidates = [
        windows / ("arialbd.ttf" if bold else "arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        if bold
        else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    raise FileNotFoundError("Install a Cyrillic-capable system font to generate assets")


def background(top: str, bottom: str) -> Image.Image:
    image = Image.new("RGB", SIZE)
    draw = ImageDraw.Draw(image)
    top_rgb = tuple(bytes.fromhex(top[1:]))
    bottom_rgb = tuple(bytes.fromhex(bottom[1:]))
    for y in range(SIZE[1]):
        blend = y / (SIZE[1] - 1)
        color = tuple(
            round(top_rgb[i] * (1 - blend) + bottom_rgb[i] * blend)
            for i in range(3)
        )
        draw.line((0, y, SIZE[0], y), fill=color)
    return image


def skyline(draw: ImageDraw.ImageDraw, color: str, seed: int) -> None:
    widths = [76, 96, 68, 120, 84, 105, 78, 118, 88, 98]
    x = -20
    for index, width in enumerate(widths):
        height = 115 + ((index * 47 + seed * 31) % 155)
        y = 380 - height
        draw.rounded_rectangle(
            (x, y, x + width, 398),
            radius=7,
            fill=color,
        )
        for wx in range(x + 13, x + width - 9, 21):
            for wy in range(y + 17, 382, 27):
                draw.rounded_rectangle((wx, wy, wx + 8, wy + 11), radius=2, fill="#f3d899")
        x += width + 10


def rounded_label(draw: ImageDraw.ImageDraw, box, title: str, subtitle: str) -> None:
    draw.rounded_rectangle(box, radius=20, fill="#101722")
    x1, y1, _, _ = box
    draw.text((x1 + 28, y1 + 22), title, font=font(34, True), fill="#ffffff")
    draw.text((x1 + 30, y1 + 76), subtitle, font=font(20, True), fill="#a9c5d5")


def city_card(city_id: str) -> None:
    accent, building, title, subtitle = PALETTES[city_id]
    image = background("#182b43", accent)
    draw = ImageDraw.Draw(image)
    draw.ellipse((680, 55, 820, 195), fill="#ffd47a")
    skyline(draw, building, list(PALETTES).index(city_id))
    draw.polygon([(0, 420), (960, 420), (960, 540), (0, 540)], fill="#222b37")
    draw.polygon([(270, 540), (430, 415), (535, 415), (710, 540)], fill="#313b48")
    draw.line((475, 475, 481, 490), fill="#f4d276", width=5)
    draw.line((495, 515, 502, 532), fill="#f4d276", width=5)
    rounded_label(draw, (42, 38, 600, 160), title, subtitle)
    image.save(OUTPUT / f"city_{city_id}.png", optimize=True)


def city_overview() -> None:
    image = background("#192b44", "#31576c")
    draw = ImageDraw.Draw(image)
    skyline(draw, "#233648", 5)
    draw.rectangle((0, 390, 960, 540), fill="#17212d")
    draw.text((45, 28), "GHETTO CITY", font=font(38, True), fill="#ffffff")
    draw.text((48, 82), "ВЫБЕРИТЕ НАПРАВЛЕНИЕ", font=font(21, True), fill="#c6d5e0")
    positions = [(44, 168), (494, 168), (44, 338), (494, 338)]
    for (city_id, (_, _, name, subtitle)), (x, y) in zip(PALETTES.items(), positions):
        accent = PALETTES[city_id][0]
        draw.rounded_rectangle((x, y, x + 420, y + 135), radius=18, fill="#111c29")
        draw.rounded_rectangle((x + 16, y + 17, x + 31, y + 118), radius=7, fill=accent)
        draw.text((x + 52, y + 28), name, font=font(23, True), fill="#ffffff")
        draw.text((x + 54, y + 76), subtitle, font=font(18), fill="#a9bdcb")
    image.save(OUTPUT / "city_overview.png", optimize=True)


def transport_card(key: str, title: str, subtitle: str, color: str) -> None:
    image = background("#162a40", "#41647a")
    draw = ImageDraw.Draw(image)
    skyline(draw, "#20364b", 7)
    draw.rectangle((0, 408, 960, 540), fill="#1d2732")
    draw.line((0, 470, 960, 470), fill="#f2d074", width=5)
    if key == "bus":
        draw.rounded_rectangle((180, 260, 730, 430), radius=28, fill=color)
        draw.rectangle((230, 288, 640, 350), fill="#c4e7ef")
        draw.rectangle((660, 315, 700, 395), fill="#f8e9ae")
        wheel_positions = [270, 640]
    elif key == "train":
        draw.rounded_rectangle((130, 270, 790, 430), radius=35, fill=color)
        draw.rectangle((190, 295, 675, 352), fill="#b9dbe6")
        draw.line((340, 295, 340, 355), fill="#344b5a", width=6)
        draw.line((500, 295, 500, 355), fill="#344b5a", width=6)
        wheel_positions = [240, 680]
    elif key == "taxi":
        draw.polygon([(215, 365), (290, 300), (600, 300), (690, 366)], fill=color)
        draw.rounded_rectangle((170, 350, 750, 425), radius=24, fill=color)
        draw.polygon([(315, 315), (365, 315), (365, 354), (270, 354)], fill="#c9e6ed")
        draw.polygon([(385, 315), (565, 315), (620, 354), (385, 354)], fill="#c9e6ed")
        draw.rounded_rectangle((420, 270, 505, 295), radius=6, fill="#fff1a7")
        wheel_positions = [280, 640]
    else:
        draw.ellipse((380, 250, 580, 450), outline=color, width=20)
        draw.ellipse((430, 300, 530, 400), outline="#f2d5a0", width=8)
        draw.line((480, 290, 480, 405), fill="#ffffff", width=7)
        draw.line((420, 350, 540, 350), fill="#ffffff", width=7)
        wheel_positions = []

    for x in wheel_positions:
        draw.ellipse((x - 37, 395, x + 37, 468), fill="#12171e")
        draw.ellipse((x - 18, 414, x + 18, 450), fill="#96a4ad")
    rounded_label(draw, (38, 28, 590, 150), title, subtitle)
    image.save(OUTPUT / f"transport_{key}.png", optimize=True)


def appearance_card() -> None:
    image = background("#17283c", "#34526b")
    draw = ImageDraw.Draw(image)
    draw.text((42, 28), "ВАШ ПЕРСОНАЖ", font=font(36, True), fill="#ffffff")
    draw.text((45, 80), "Выберите стиль внешнего вида", font=font(22), fill="#bed0dd")
    choices = [
        ("БЕЗ МАСКИ", "#e7b777", None),
        ("ТЁМНАЯ МАСКА", "#6ca9d4", "#202631"),
        ("КРАСНАЯ МАСКА", "#d56b63", "#a52b34"),
    ]
    for index, (label, skin, mask) in enumerate(choices):
        x = 35 + index * 300
        draw.rounded_rectangle((x, 145, x + 275, 495), radius=20, fill="#111c29")
        center = x + 137
        draw.ellipse((center - 58, 205, center + 58, 330), fill=skin)
        draw.rounded_rectangle((center - 72, 320, center + 72, 440), radius=48, fill="#34495f")
        if mask:
            draw.rounded_rectangle(
                (center - 53, 280, center + 53, 315),
                radius=10,
                fill=mask,
            )
        draw.text((x + 25, 452), label, font=font(18, True), fill="#ffffff")
    image.save(OUTPUT / "appearance_choices.png", optimize=True)


def profile_card() -> None:
    image = background("#182b43", "#31576c")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((42, 40, 918, 500), radius=30, fill="#101c29")
    draw.ellipse((95, 116, 330, 351), fill="#f0bd7d")
    draw.rounded_rectangle((78, 322, 348, 455), radius=64, fill="#47627b")
    draw.text((390, 105), "ПРОФИЛЬ ИГРОКА", font=font(35, True), fill="#ffffff")
    draw.text((395, 180), "Ваш путь, имущество и достижения", font=font(22), fill="#bed0dd")
    for index, label in enumerate(("ДОМ", "АВТО", "БИЗНЕС")):
        x = 395 + index * 160
        draw.rounded_rectangle((x, 255, x + 140, 370), radius=18, fill="#1b2c3c")
        draw.text((x + 15, 299), label, font=font(17, True), fill="#f0cf8b")
    draw.text((395, 410), "Ваш город начинает с вас", font=font(20, True), fill="#a9c5d5")
    image.save(OUTPUT / "profile_card.png", optimize=True)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    city_overview()
    appearance_card()
    profile_card()
    for city_id in PALETTES:
        city_card(city_id)
    for key, (color, title, subtitle) in TRANSPORTS.items():
        transport_card(key, title, subtitle, color)


if __name__ == "__main__":
    main()
