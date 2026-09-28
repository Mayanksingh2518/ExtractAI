"""Generate harder, more realistic FAKE documents (no real personal data).

Usage:  python -m scripts.make_realistic_documents
Writes realistic_* files to documents/ (gitignored). Every document is marked SPECIMEN.

Compared with scripts/make_sample_documents.py these have small print, decoy numbers
(file no., VID, enrolment no., masked Aadhaar on the tax return), skewed and sideways
scans, a card scanned on an A4 page, and a multi-page tax return whose totals are not on page 1.
"""

import random
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUTPUT_DIR = Path("documents")
FONTS = Path("/System/Library/Fonts/Supplemental")
SPECIMEN = "SPECIMEN - NOT A REAL DOCUMENT"


def _font(name: str, size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(FONTS / name), size)
    except OSError:
        return ImageFont.load_default(size)


def _mrz_check_digit(text: str) -> str:
    """ICAO 9303 check digit (weights 7, 3, 1)."""
    values = {**{str(d): d for d in range(10)}, **{chr(65 + i): 10 + i for i in range(26)}, "<": 0}
    return str(sum(values[c] * (7, 3, 1)[i % 3] for i, c in enumerate(text)) % 10)


def _mrz(p: dict) -> tuple[str, str]:
    """The two machine-readable lines at the bottom of a passport data page."""
    names = f"{p['surname']}<<{p['given'].replace(' ', '<')}"
    line1 = f"P<IND{names}".ljust(44, "<")[:44]
    dob, exp = (_yymmdd(p["dob"]), _yymmdd(p["expiry"]))
    number = p["number"].ljust(9, "<")
    line2 = (f"{number}{_mrz_check_digit(number)}IND{dob}{_mrz_check_digit(dob)}{p['sex']}"
             f"{exp}{_mrz_check_digit(exp)}").ljust(42, "<") + "<0"
    return line1, line2


def _yymmdd(ddmmyyyy: str) -> str:
    day, month, year = ddmmyyyy.split("/")
    return year[2:] + month + day


def passport_page(p: dict) -> Image.Image:
    """A dense passport data page: bilingual small labels, photo, decoy numbers and an MRZ."""
    img = Image.new("RGB", (1240, 870), (236, 240, 232))
    draw = ImageDraw.Draw(img)
    for y in range(0, 870, 6):  # faint guilloche-like background lines
        draw.line([(0, y), (1240, y + 40)], fill=(226, 232, 222))
    hindi, label, value = _font("Arial Unicode.ttf", 17), _font("Arial.ttf", 15), _font("Arial Bold.ttf", 24)
    draw.text((40, 26), "भारत गणराज्य", font=_font("Arial Unicode.ttf", 22), fill="navy")
    draw.text((230, 28), "REPUBLIC OF INDIA", font=_font("Arial Bold.ttf", 24), fill="navy")
    draw.text((760, 32), SPECIMEN, font=_font("Arial.ttf", 16), fill="firebrick")
    draw.rectangle([40, 90, 320, 450], fill=(200, 205, 210), outline="gray")
    draw.text((140, 260), "PHOTO", font=label, fill="gray")

    def field(x: int, y: int, hi: str, en: str, text: str) -> None:
        draw.text((x, y), hi, font=hindi, fill="dimgray")
        draw.text((x + draw.textlength(hi, font=hindi) + 6, y + 2), f"/ {en}", font=label, fill="dimgray")
        draw.text((x, y + 24), text, font=value, fill="black")

    field(360, 90, "प्रकार", "Type", "P")
    field(520, 90, "कोड", "Country Code", "IND")
    field(800, 90, "पासपोर्ट सं.", "Passport No.", p["number"])
    field(360, 160, "उपनाम", "Surname", p["surname"])
    field(360, 230, "दिया गया नाम", "Given Name(s)", p["given"])
    field(360, 300, "राष्ट्रीयता", "Nationality", "INDIAN")
    field(640, 300, "लिंग", "Sex", p["sex"])
    field(800, 300, "जन्मतिथि", "Date of Birth", p["dob"])
    field(360, 370, "जन्म स्थान", "Place of Birth", p["birthplace"])
    field(360, 440, "जारी करने का स्थान", "Place of Issue", p["issue_place"])
    field(360, 510, "जारी करने की तिथि", "Date of Issue", p["issued"])
    field(800, 510, "समाप्ति की तिथि", "Date of Expiry", p["expiry"])
    field(40, 510, "फ़ाइल सं.", "File No.", p["file_no"])
    mrz = _font("Courier New Bold.ttf", 33)
    line1, line2 = _mrz(p)
    draw.text((40, 700), line1, font=mrz, fill="black")
    draw.text((40, 760), line2, font=mrz, fill="black")
    return img


def phone_scan(img: Image.Image, angle: float, seed: int) -> Image.Image:
    """Shrink, tilt, blur and add sensor noise, like a quick phone photo on a desk."""
    rng = random.Random(seed)
    small = img.resize((img.width * 3 // 4, img.height * 3 // 4))
    tilted = small.rotate(angle, expand=True, fillcolor=(120, 104, 88), resample=Image.BICUBIC)
    desk = Image.new("RGB", (tilted.width + 120, tilted.height + 120), (120, 104, 88))
    desk.paste(tilted, (60, 60))
    desk = desk.filter(ImageFilter.GaussianBlur(0.8))
    pixels = desk.load()
    for _ in range(desk.width * desk.height // 12):
        x, y = rng.randrange(desk.width), rng.randrange(desk.height)
        r, g, b = pixels[x, y]
        n = rng.randint(-28, 28)
        pixels[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    return desk


def aadhaar_card(side: str, a: dict) -> Image.Image:
    """Front (name, DOB, number) or back (address) of an Aadhaar card, 1012x638 like a 300 dpi scan."""
    img = Image.new("RGB", (1012, 638), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 1011, 90], fill=(255, 153, 51))
    draw.rectangle([0, 548, 1011, 637], fill=(19, 136, 8))
    hindi, small, text, big = (_font("Arial Unicode.ttf", 26), _font("Arial.ttf", 22),
                              _font("Arial.ttf", 28), _font("Arial Bold.ttf", 44))
    if side == "front":
        draw.text((260, 12), "भारत सरकार", font=hindi, fill="black")
        draw.text((260, 48), "GOVERNMENT OF INDIA", font=_font("Arial Bold.ttf", 28), fill="black")
        draw.rectangle([40, 130, 250, 390], fill=(210, 210, 210))
        draw.text((290, 140), a["name"], font=text, fill="black")
        draw.text((290, 190), f"जन्म तिथि / DOB : {a['dob']}", font=_font("Arial Unicode.ttf", 26), fill="black")
        draw.text((290, 240), f"पुरुष / {a['gender']}", font=_font("Arial Unicode.ttf", 26), fill="black")
        draw.text((290, 330), SPECIMEN, font=small, fill="firebrick")
        draw.text((270, 450), a["number"], font=big, fill="black")
        draw.text((330, 510), f"VID : {a['vid']}", font=small, fill="black")
        draw.text((330, 570), "मेरा आधार, मेरी पहचान", font=hindi, fill="white")
    else:
        draw.text((160, 12), "भारतीय विशिष्ट पहचान प्राधिकरण", font=hindi, fill="black")
        draw.text((160, 48), "UNIQUE IDENTIFICATION AUTHORITY OF INDIA", font=_font("Arial Bold.ttf", 26), fill="black")
        draw.text((40, 130), "पता / Address:", font=_font("Arial Unicode.ttf", 26), fill="black")
        for i, line in enumerate(a["address_lines"]):
            draw.text((40, 180 + i * 42), line, font=text, fill="black")
        draw.text((40, 400), SPECIMEN, font=small, fill="firebrick")
        draw.text((270, 450), a["number"], font=big, fill="black")
        draw.text((300, 570), "help@example.test  |  www.example.test", font=small, fill="white")
    return img


def pan_card(p: dict) -> Image.Image:
    """A bilingual PAN card, 1012x638 like a 300 dpi scan. The father's name and the signature are decoys."""
    img = Image.new("RGB", (1012, 638), (214, 233, 244))
    draw = ImageDraw.Draw(img)
    hindi, label, value = _font("Arial Unicode.ttf", 22), _font("Arial Unicode.ttf", 20), _font("Arial Bold.ttf", 30)
    draw.text((40, 20), "आयकर विभाग", font=hindi, fill="black")
    draw.text((40, 50), "INCOME TAX DEPARTMENT", font=_font("Arial Bold.ttf", 26), fill="black")
    draw.text((640, 20), "भारत सरकार", font=hindi, fill="black")
    draw.text((640, 50), "GOVT. OF INDIA", font=_font("Arial Bold.ttf", 26), fill="black")
    draw.text((260, 105), "स्थायी लेखा संख्या कार्ड", font=hindi, fill="black")
    draw.text((200, 135), "Permanent Account Number Card", font=_font("Arial Bold.ttf", 28), fill="black")
    draw.text((330, 180), p["pan"], font=_font("Arial Bold.ttf", 40), fill="black")
    draw.rectangle([40, 240, 220, 450], fill=(190, 200, 210))
    for i, (hi, en, text) in enumerate([("नाम", "Name", p["name"]), ("पिता का नाम", "Father's Name", p["father"]),
                                          ("जन्म की तारीख", "Date of Birth", p["dob"])]):
        draw.text((260, 240 + i * 80), f"{hi} / {en}", font=label, fill="dimgray")
        draw.text((260, 268 + i * 80), text, font=value, fill="black")
    draw.text((260, 500), p["name"].split()[0].title() + " " + p["name"].split()[1][0] + ".",
              font=_font("Times New Roman Italic.ttf", 34), fill="navy")  # signature
    draw.text((260, 540), "हस्ताक्षर / Signature", font=label, fill="dimgray")
    draw.text((640, 590), SPECIMEN, font=_font("Arial.ttf", 16), fill="firebrick")
    return img


def card_on_a4_scan(card: Image.Image, angle: float) -> Image.Image:
    """A card scanned on a flatbed at 200 dpi: a small, slightly tilted card near the top of an A4 page."""
    page = Image.new("RGB", (1654, 2339), (250, 250, 247))
    card = card.resize((674, 425)).rotate(angle, expand=True, fillcolor=(250, 250, 247), resample=Image.BICUBIC)
    page.paste(card, (130, 150))
    return page.filter(ImageFilter.GaussianBlur(0.5))


def image_pdf(path: Path, images: list[Image.Image], rotate: int = 0) -> None:
    """A scanned PDF: one A4 page per image."""
    document = pymupdf.open()
    for i, image in enumerate(images):
        image_path = path.with_name(f"{path.stem}_tmp{i}.png")
        image.save(image_path)
        page = document.new_page(width=595, height=842)
        rect = pymupdf.Rect(30, 30, 565, 812) if image.height > image.width or rotate else pymupdf.Rect(30, 30, 565, 405)
        page.insert_image(rect, filename=str(image_path), rotate=rotate)
        image_path.unlink()
    document.save(path)
    document.close()


def e_aadhaar(path: Path, a: dict) -> None:
    """A digital e-Aadhaar letter in small print, with decoy enrolment and VID numbers."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)

    def text(x: float, y: float, s: str, size: float = 8, font: str = "helv", color=(0, 0, 0)) -> None:
        page.insert_text((x, y), s, fontsize=size, fontname=font, color=color)

    text(40, 40, "Unique Identification Authority of India", 11, "hebo")
    text(40, 54, "Government of India", 9)
    text(380, 40, SPECIMEN, 8, color=(0.7, 0.1, 0.1))
    text(40, 90, f"Enrolment No.: {a['enrolment']}", 8)
    text(40, 115, "To,", 8)
    for i, line in enumerate([a["name"], *a["address_lines"], "Mobile: XXXXXX4821"]):
        text(40, 128 + i * 11, line, 8)
    text(360, 128, "Signature Not Verified", 7)
    text(360, 138, "Digitally signed by DS Unique Identification", 7)
    text(360, 148, "Authority of India  Date: 2024.03.15 10:21:07 IST", 7)
    text(200, 260, "Your Aadhaar No. :", 11, "hebo")
    text(205, 282, a["number"], 16, "hebo")
    text(205, 300, f"VID : {a['vid']}", 8)
    text(200, 330, "Aadhaar - Aam Aadmi ka Adhikar", 10, "heit")
    text(40, 380, "Aadhaar is proof of identity, not of citizenship. Verify identity using Secure QR Code / Offline XML.", 6.5)
    page.draw_line((30, 520), (565, 520), dashes="[3] 0", width=0.5)
    # the cut-out card: front on the left, back on the right
    page.draw_rect(pymupdf.Rect(40, 540, 290, 700), width=0.6)
    page.draw_rect(pymupdf.Rect(305, 540, 555, 700), width=0.6)
    text(110, 556, "Government of India", 8, "hebo")
    page.draw_rect(pymupdf.Rect(48, 566, 98, 626), fill=(0.8, 0.8, 0.8), width=0)
    text(106, 580, a["name"], 7.5)
    text(106, 592, f"DOB: {a['dob']}", 7.5)
    text(106, 604, a["gender"], 7.5)
    text(100, 660, a["number"], 12, "hebo")
    text(110, 675, f"VID : {a['vid']}", 6)
    text(313, 556, "Unique Identification Authority of India", 7.5, "hebo")
    text(313, 572, "Address:", 7, "hebo")
    for i, line in enumerate(a["address_lines"]):
        text(313, 583 + i * 9, line, 6.5)
    text(365, 660, a["number"], 12, "hebo")
    doc.save(path)
    doc.close()


def full_itr(path: Path, t: dict) -> None:
    """A 5-page ITR-1 style return in 8-9 pt print. Total income is on page 2 and the tax
    computation on page 3, so page 1 alone (personal details) has none of the amounts."""
    doc = pymupdf.open()

    def new_page(title: str) -> tuple[pymupdf.Page, list[float]]:
        page = doc.new_page(width=595, height=842)
        page.insert_text((40, 36), f"FORM ITR-1  SAHAJ   |   Assessment Year {t['ay']}   |   {SPECIMEN}", fontsize=7,
                         fontname="helv", color=(0.4, 0.4, 0.4))
        page.insert_text((40, 62), title, fontsize=10, fontname="hebo")
        return page, [84.0]

    def row(page: pymupdf.Page, y: list[float], code: str, label: str, amount: str = "", bold: bool = False) -> None:
        font = "hebo" if bold else "helv"
        page.insert_text((40, y[0]), code, fontsize=8, fontname=font)
        page.insert_text((80, y[0]), label, fontsize=8, fontname=font)
        if amount:
            page.insert_text((470, y[0]), amount.rjust(12), fontsize=8, fontname="cour" if not bold else "cobo")
        page.draw_line((40, y[0] + 4), (555, y[0] + 4), color=(0.8, 0.8, 0.8), width=0.4)
        y[0] += 17

    page, y = new_page("INDIAN INCOME TAX RETURN  [For individuals being a resident having total income up to Rs.50 lakh]")
    for code, label, value in [
        ("", "Assessment Year", t["ay"]), ("A1", "PAN", t["pan"]), ("A2", "Name", t["name"]),
        ("A3", "Date of Birth", t["dob"]), ("A4", "Aadhaar Number", "XXXX XXXX 7731"),
        ("A5", "Mobile No.", "+91 98XXXXXX10"), ("A6", "Email Address", "taxpayer@example.test"),
        ("A7", "Address", t["address"]), ("A8", "Filed u/s", "139(1) - On or before due date"),
        ("A9", "Nature of employment", "Others"), ("A10", "Acknowledgement Number", "4829103761290724"),
        ("A11", "Opting out of new tax regime u/s 115BAC?", "Yes"),
    ]:
        row(page, y, code, f"{label}:  {value}")

    page, y = new_page("PART B - GROSS TOTAL INCOME  /  PART C - DEDUCTIONS AND TAXABLE TOTAL INCOME")
    for args in [
        ("B1", "i   Gross Salary", "12,40,000"), ("", "ii  Less: Allowances exempt u/s 10", "0"),
        ("", "iii Net Salary (i - ii)", "12,40,000"), ("", "iv  Deductions u/s 16 - Standard deduction u/s 16(ia)", "50,000"),
        ("", "v   Income chargeable under the head Salaries (iii - iv)", "11,90,000"),
        ("B2", "Income from One House Property", "0"), ("B3", "Income from Other Sources (interest)", "18,500"),
        ("B4", "Gross Total Income (B1 + B2 + B3)", "12,08,500", True), ("", "", ""),
        ("C1", "Deduction u/s 80C (PPF, LIC, ELSS)", "1,50,000"), ("C2", "Deduction u/s 80D (health insurance)", "25,000"),
        ("C3", "Deduction u/s 80TTA (savings interest)", "10,000"), ("C4", "Total Deductions (C1 + C2 + C3)", "1,85,000"),
        ("C5", "Total Income (B4 - C4)", "10,23,500", True),
    ]:
        row(page, y, *args)

    page, y = new_page("PART D - COMPUTATION OF TAX PAYABLE")
    for args in [
        ("D1", "Tax payable on total income", "1,19,550"), ("D2", "Rebate u/s 87A", "0"),
        ("D3", "Tax payable after rebate (D1 - D2)", "1,19,550"), ("D4", "Health and education cess @ 4% on D3", "4,782"),
        ("D5", "Total Tax and Cess (D3 + D4)", "1,24,332"), ("D6", "Relief u/s 89", "0"),
        ("D7", "Interest u/s 234A / 234B / 234C", "1,240"), ("D8", "Fee u/s 234F", "0"),
        ("D9", "Total Tax, Fee and Interest (D5 - D6 + D7 + D8)", "1,25,572", True),
        ("D10", "Total Taxes Paid (TDS + TCS + Advance tax + Self-assessment tax)", "1,10,000", True),
        ("D11", "Amount payable (D9 - D10, if D9 > D10)", "15,570", True),
        ("D12", "Refund (D10 - D9, if D10 > D9)", "0"),
    ]:
        row(page, y, *args)

    page, y = new_page("SCHEDULE TDS / TAXES PAID")
    for args in [
        ("", "TAN of deductor: PNEX01234C   Employer: TESTLAND WIDGETS PVT LTD", ""),
        ("1", "Income chargeable under Salaries", "11,90,000"), ("2", "Total tax deducted (TDS on salary)", "1,00,000"),
        ("3", "Advance tax paid (BSR 0510308, 15/03/2024)", "10,000"), ("4", "Self-assessment tax paid", "0"),
    ]:
        row(page, y, *args)

    page, y = new_page("VERIFICATION")
    page.insert_textbox(pymupdf.Rect(40, 84, 555, 200),
                        f"I, {t['name']}, son of RAKESH MEHTA, solemnly declare that to the best of my knowledge and "
                        "belief, the information given in the return is correct and complete. Place: PUNE  Date: 28/07/2024",
                        fontsize=8, fontname="helv")
    doc.save(path)
    doc.close()


PASSPORT_A = {"number": "K4821937", "surname": "SHARMA", "given": "PRIYA ANJALI", "sex": "F", "dob": "07/03/1991",
              "birthplace": "PUNE, MAHARASHTRA", "issue_place": "MUMBAI", "issued": "12/08/2019",
              "expiry": "11/08/2029", "file_no": "MU1071234567819"}
PASSPORT_B = {"number": "Z9053318", "surname": "VERMA", "given": "RAHUL", "sex": "M", "dob": "02/11/1979",
              "birthplace": "LUCKNOW, UTTAR PRADESH", "issue_place": "LUCKNOW", "issued": "17/01/2021",
              "expiry": "16/01/2031", "file_no": "LK2079876543210"}
E_AADHAAR = {"name": "Neha Kapoor", "dob": "14/06/1988", "gender": "FEMALE", "number": "4821 7390 5612",
             "vid": "9182 7364 5501 2837", "enrolment": "2189/60417/03521",
             "address_lines": ["D/O: Suresh Kapoor, Flat 12B, Lotus Residency, MG Road,",
                               "Near City Mall, Andheri West, Mumbai, Maharashtra - 400058"]}
AADHAAR_CARD = {"name": "Vikram Singh", "dob": "05/12/1995", "gender": "MALE", "number": "6130 2297 4485",
                "vid": "9876 1234 5566 7788",
                "address_lines": ["S/O: Harpal Singh, House No. 482,", "Sector 21-C, Chandigarh,", "Chandigarh - 160022"]}
PAN = {"pan": "BQTPK7302M", "name": "KAVITA NAIR", "father": "MOHAN NAIR", "dob": "19/04/1993"}
ITR = {"ay": "2024-25", "pan": "AKRPM4821Q", "name": "ARJUN MEHTA", "dob": "22/09/1986",
       "address": "B-204, Green Park Society, Kothrud, Pune, Maharashtra 411038"}


def make_all(out: Path = OUTPUT_DIR) -> list[Path]:
    out.mkdir(exist_ok=True)
    passport_a = passport_page(PASSPORT_A)
    passport_a.save(out / "realistic_passport.png")
    phone_scan(passport_page(PASSPORT_B), angle=4.0, seed=7).save(out / "realistic_passport_photo.jpg", quality=55)
    image_pdf(out / "realistic_passport_sideways.pdf", [passport_a], rotate=90)
    e_aadhaar(out / "realistic_e_aadhaar.pdf", E_AADHAAR)
    image_pdf(out / "realistic_aadhaar_card_scan.pdf",
              [card_on_a4_scan(aadhaar_card("front", AADHAAR_CARD), 1.5),
               card_on_a4_scan(aadhaar_card("back", AADHAAR_CARD), -1.0)])
    full_itr(out / "realistic_itr_full.pdf", ITR)
    pan_card(PAN).save(out / "realistic_pan_card.png")
    return sorted(out.glob("realistic_*"))


if __name__ == "__main__":
    for path in make_all():
        print(f"saved {path}")
