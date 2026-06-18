#!/usr/bin/env python3
"""
convert_timetable.py
Convert an aSc Timetables PDF to the CSV format expected by Smart Relief Allocator.

Usage:
  python convert_timetable.py "time table.pdf"            # prints CSV to stdout
  python convert_timetable.py "time table.pdf" out.csv    # saves to file
  python convert_timetable.py "time table.pdf" --debug    # verbose stderr output
"""

import sys, re, csv, io, os
import fitz
import pytesseract
from PIL import Image, ImageEnhance

pytesseract.pytesseract.tesseract_cmd = r"C:/Program Files/Tesseract-OCR/tesseract.exe"

# ── Period lookup: start-time string → period ID ─────────────────────────────
PERIOD_BY_START = {
    "8:00": 1,  "08:00": 1,
    "8:35": 2,  "08:35": 2,
    "9:10": 3,  "09:10": 3,
    "9:45": 4,  "09:45": 4,
    "10:20": 5, "10:55": 6,
    "11:30": 7, "12:05": 8,
    "12:40": 9, "13:15": 10,
    "13:50": 11,"14:25": 12,
    "15:00": 13,"15:35": 14,
    "16:10": 15,"16:45": 16,
}

TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")

SEL_WORDS = {"care","flourish","resilience","responsibility",
             "curiosity","connect","contribute","respect","adaptability"}

SKIP_TOKENS = {
    "masfti","mas/fti","mas/fti/","ftt","fit","assy","cce","ccf",
    "pd/dept","staffm","hum","rm","meeting","asc","timetables",
    "timetable","generated","yuhua","secondary","school","singapore",
    "smt","smtf","dept","staffmeeting","lab","ssd","tt","tti",
    "assembly","flag-raise","recess","break","cca","ccf",
    "meeti","meetin","contri","contrib",    # truncations
    "social","studies", # "Social Studies" split — neither word alone is a subject
    "new","tchr",       # "New Physics Tchr" fragments
    "sci",              # "Sci" alone (disambiguation wrapper, e.g. "Sci (Chemistry)")
    "lib",              # "Lib Connect" (library period)
    "xin","soh",        # common teacher name fragments
}

# Subject words that can only be the start of a compound subject
COMPOUND_PREFIXES = {"Pure", "Applied", "Integrated"}
# Their valid completions
COMPOUND_COMPLETIONS = {"Mathematics","Chemistry","Physics","Science","Sciences",
                        "Biology","Geography","History","English","Art","Music"}

# OCR typo corrections applied before parsing
OCR_FIXES = [
    (r"\bPere\b", "Pure"),
    (r"\bPare\b", "Pure"),
    (r"\bMing\b(?=\s*Quan\b)", "Ming"),  # already correct, no-op
]

# Template row y-positions (pixels, 5× zoom, after -90° CW rotation).
# These are identical across all pages of the same aSc Timetables PDF.
TEMPLATE_ODD  = [(660, "monday"), (895, "tuesday"), (1130, "wednesday"),
                 (1365, "thursday"), (1600, "friday")]
TEMPLATE_EVEN = [(1830, "monday"), (2066, "tuesday"), (2302, "wednesday"),
                 (2537, "thursday"), (2772, "friday")]
DEFAULT_RH = 235     # row height (pixels)
DIVIDER_Y  = 1715    # boundary between Odd section (above) and Even section (below)


# ── OCR one PDF page ──────────────────────────────────────────────────────────

def ocr_page(page, zoom=5):
    """Render page at zoom×, rotate 90° CW, enhance contrast, OCR.
    Returns ([(text,x,y,conf)], img_width, img_height)."""
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    img = img.rotate(-90, expand=True)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    d = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT,
                                   config="--psm 11 --oem 3")
    words = []
    for i in range(len(d["text"])):
        t = d["text"][i].strip()
        c = int(d["conf"][i])
        if t and c > 30:
            words.append((t, d["left"][i], d["top"][i], c))
    return words, img.width, img.height


# ── Structural element detection ──────────────────────────────────────────────

def find_period_cols(words):
    """
    Return sorted [(x_center, period_id)] for all 16 period columns.

    The PDF header has two rows:
      y ≈ 326 : period START times  (8:00, 8:35, 9:10 … 16:45)
      y ≈ 367 : period END   times  (8:35, 9:10, 9:45 … 17:20)

    Restricting to y < 350 captures only start times, giving exactly 16
    period columns with no duplicates or missing entries.
    """
    buckets = {}   # bx → (min_y_seen, period_id)
    for (t, x, y, c) in words:
        if TIME_RE.match(t) and y < 350:
            pid = PERIOD_BY_START.get(t)
            if pid:
                bx = round(x / 10) * 10
                if bx not in buckets or y < buckets[bx][0]:
                    buckets[bx] = (y, pid)
    return sorted((bx, pid) for bx, (y, pid) in buckets.items())


def col_ranges(period_cols):
    """Build [(x_lo, x_hi, period_id)] half-open column boundaries."""
    if not period_cols:
        return []
    xs = [x for x, _ in period_cols]
    result = []
    for i, (x, pid) in enumerate(period_cols):
        lo = (xs[i-1] + x) / 2 if i > 0         else x - (xs[1] - xs[0]) / 2
        hi = (x + xs[i+1]) / 2 if i < len(xs)-1 else x + (xs[-1] - xs[-2]) / 2
        result.append((lo, hi, pid))
    return result


def find_row_centers(words, col_lo_x):
    """
    Return (odd_rows, even_rows) each as [(y_center, day_full_name)].

    Strategy:
    1. Look for Tue / Thu labels (most reliably OCR'd day names) in the
       left-margin area (x < col_lo_x).
    2. Partition found anchors into Odd section (y < DIVIDER_Y) and Even
       section (y >= DIVIDER_Y).
    3. Derive missing anchors using DEFAULT_RH.
    4. If a section has NO anchors at all, fall back to TEMPLATE positions.
    """
    def get_ys(tags):
        return sorted(y for (t, x, y, c) in words
                      if t in tags and x < col_lo_x and c > 35)

    all_tue = get_ys({"Tue", "Tues"})
    all_thu = get_ys({"Thu", "Thurs"})
    all_mon = get_ys({"Mon"})
    all_wed = get_ys({"Wed"})
    all_fri = get_ys({"Fri"})

    def first_in(ys, pred):
        return next((y for y in ys if pred(y)), None)

    in_odd  = lambda y: y < DIVIDER_Y
    in_even = lambda y: y >= DIVIDER_Y

    # Partition primary anchors by week section
    odd_tue  = first_in(all_tue, in_odd);  even_tue = first_in(all_tue, in_even)
    odd_thu  = first_in(all_thu, in_odd);  even_thu = first_in(all_thu, in_even)
    odd_mon  = first_in(all_mon, in_odd);  even_mon = first_in(all_mon, in_even)
    odd_wed  = first_in(all_wed, in_odd);  even_wed = first_in(all_wed, in_even)
    odd_fri  = first_in(all_fri, in_odd);  even_fri = first_in(all_fri, in_even)

    def make_rows(tue, thu, mh=None, wh=None, fh=None):
        """Derive 5 row y-positions from Tue+Thu anchors (or one of them)."""
        if tue is None and thu is None:
            return None
        rh = DEFAULT_RH
        if tue is not None and thu is not None:
            rh = (thu - tue) / 2
        elif tue is not None:
            thu = tue + 2 * rh
        else:
            tue = thu - 2 * rh
        mon = mh if mh else tue - rh
        wed = wh if wh else tue + rh
        fri = fh if fh else thu + rh
        return [(mon,"monday"),(tue,"tuesday"),(wed,"wednesday"),(thu,"thursday"),(fri,"friday")]

    odd_rows  = make_rows(odd_tue,  odd_thu,  odd_mon,  odd_wed,  odd_fri)
    even_rows = make_rows(even_tue, even_thu, even_mon, even_wed, even_fri)

    # Fall back to template positions when OCR anchors are unavailable
    return (odd_rows  or list(TEMPLATE_ODD)), \
           (even_rows or list(TEMPLATE_EVEN))


def build_row_ranges(odd_rows, even_rows, img_h):
    """Return [(y_lo, y_hi, day_full, week_type)] covering the full image."""
    all_rows = [(y, d, "Odd")  for y, d in odd_rows] + \
               [(y, d, "Even") for y, d in even_rows]
    all_rows.sort()
    result = []
    for i, (y, day, wt) in enumerate(all_rows):
        lo = (all_rows[i-1][0] + y) / 2 if i > 0              else y - 200
        hi = (y + all_rows[i+1][0]) / 2 if i < len(all_rows)-1 else img_h - 50
        result.append((lo, hi, day, wt))
    return result


# ── Word clustering ───────────────────────────────────────────────────────────

def cluster_words(content_words):
    """
    Group nearby words into text clusters (same line, left-to-right within 300px).
    Returns [[(text, x, y), ...], ...]
    """
    if not content_words:
        return []
    sw = sorted(content_words, key=lambda w: (w[2], w[1]))
    clusters, cur = [], [sw[0]]
    for w in sw[1:]:
        prev = cur[-1]
        dy = abs(w[2] - prev[2])
        dx = w[1] - prev[1]
        if dy < 25 and 0 <= dx < 300:
            cur.append(w)
        else:
            clusters.append(cur)
            cur = [w]
    clusters.append(cur)
    return clusters


# ── Content filtering ─────────────────────────────────────────────────────────

def is_skip(text):
    tl = text.lower().strip(".,/-")
    if tl in SKIP_TOKENS:
        return True
    # Year / date
    if re.match(r"^\d{4}$", text):
        return True
    if re.match(r"^\d+/\d+/\d{4}$", text):
        return True
    # Role abbreviations: SH/D&T, HOD/Sci, ICT/, etc.
    if re.match(r"^[A-Z]{1,4}/[A-Z&/]{1,6}$", text):
        return True
    # Room codes: ITR3, B101, L4
    if re.match(r"^(ITR|Rm|Lab|B|L)\d+$", text, re.I):
        return True
    # OCR garbage: very short or symbol-only
    if len(text) < 2:
        return True
    return False


def is_sel(text):
    for w in re.split(r"[\s/]+", text.lower()):
        if w in SEL_WORDS:
            return True
    return False


def apply_ocr_fixes(text):
    for pattern, replacement in OCR_FIXES:
        text = re.sub(pattern, replacement, text)
    return text


def _is_teacher_fragment(lt):
    """Return True if the line looks like a teacher-name/role fragment."""
    if re.search(r"\((HOD|SH/|VP|AYH|YH|ICT)\b", lt, re.I):
        return True
    if re.search(r"/(HOD|SH|ICT|VP)\b", lt, re.I):
        return True
    if len(re.findall(r"\b(Mr|Ms|Mdm|Mrs|Dr)\b", lt, re.I)) >= 2:
        return True
    # Unmatched opening paren with role keyword
    if "(" in lt and ")" not in lt and re.search(r"\(HOD|SH/|ICT", lt, re.I):
        return True
    return False


# ── Cell parsing ──────────────────────────────────────────────────────────────

def parse_class(line_texts, teacher_name_parts=None):
    """
    Given text lines in a cell, return {level, subject, stream} or None.

    Handles patterns:
      "Sci (Chemistry) G3"    → subject=Chemistry, stream=G3
      "Social Studies (G3)"   → subject=Social Studies, stream=G3
      "Pure Physics G3"       → subject=Pure Physics, stream=G3
      "(Chemistry)"           → subject=Chemistry  (outer parens stripped)
      "LSS (Sec 2)"           → level=Sec 2, subject=LSS
    """
    line_texts = [apply_ocr_fixes(lt) for lt in line_texts]
    teacher_name_parts = teacher_name_parts or set()

    # ── Level extraction from SEL lines ("/N" suffix or leading digit) ────────
    level = ""
    for lt in line_texts:
        if is_sel(lt):
            m = re.match(r"^(\d)", lt) or re.search(r"/(\d)\b", lt)
            if m and not level:
                level = f"Sec {m.group(1)}"

    # ── Collect standalone stream codes for stream-only cells ─────────────────
    stream_from_code = ""
    for lt in line_texts:
        if re.match(r"^[A-Z]\d$", lt) and not stream_from_code:
            stream_from_code = lt

    # ── Build candidate line list ──────────────────────────────────────────────
    def _bad_line(lt):
        if not lt or len(lt) < 3:                  return True
        if is_skip(lt) or is_sel(lt):              return True
        if re.match(r"^\d+$", lt):                 return True
        if re.search(r"\(\d{3,}\)", lt):           return True   # admin code
        if re.match(r"^(Mr|Ms|Mrs|Dr|Mdm)\s", lt, re.I): return True
        if re.match(r"^\([A-Z]\d\)$", lt):         return True   # (G1)
        if re.match(r"^\([AB]\)(/\d+)?$", lt):     return True   # (A), (B)/4
        if re.match(r"^[A-Z]\d$", lt):             return True   # G2 alone
        if re.search(r"[\x80-\xff]", lt):              return True   # non-ASCII garbage
        if re.match(r"^[a-z]", lt):                return True   # starts lowercase
        if lt.endswith(")") and "(" not in lt:     return True   # "Sci)" fragment
        if re.search(r"^[^\w\s(]", lt):            return True   # starts with symbol
        if _is_teacher_fragment(lt):               return True
        if lt.endswith("/") or lt.endswith("\\"):  return True
        # 2-char lowercase words that are not common prepositions → OCR noise
        COMMON_LOWER_2 = {"of","in","at","to","is","or","as","by","do","so","on"}
        lc2 = [w for w in lt.split() if len(w) == 2 and w.islower()]
        if any(w not in COMMON_LOWER_2 for w in lc2):
            return True
        # 4+ capitalised alpha words in a row → teacher full name leaked in
        cap_alpha = [w for w in lt.split() if w and w[0].isupper() and w.isalpha() and len(w) >= 3]
        if len(cap_alpha) >= 4 and len(lt.split()) >= 4:
            return True
        # Skip lines where any long word matches a teacher name part
        for w in lt.split():
            w_lc = w.lower().strip("(),.-/")
            if len(w_lc) < 4:
                continue
            for tp in teacher_name_parts:
                if len(tp) >= 4 and (tp.startswith(w_lc) or w_lc.startswith(tp)):
                    return True
        return False

    candidates = [lt for lt in line_texts if not _bad_line(lt)]

    # ── Parse subject from candidates ─────────────────────────────────────────
    subject = stream = ""
    i = 0
    while i < len(candidates):
        lt = candidates[i]

        # Pattern: "(Chemistry)" alone — strip outer parens
        m_paren = re.match(r"^\(([A-Za-z][^)]{2,})\)$", lt)
        if m_paren:
            inner = m_paren.group(1).strip()
            if (not is_skip(inner) and len(inner) >= 3
                    and not re.match(r"^[A-Z]\d$", inner)
                    and not re.match(r"^[AB]$", inner)
                    and not re.match(r"^Sec\s*\d$", inner, re.I)):
                subject = inner
                break
            i += 1
            continue

        # Pattern: "Sci (Chemistry) G3" or "Social Studies (G3)"
        m = re.match(r"^(.+?)\s*\(([^)]+)\)\s*([A-Z]\d)?\s*$", lt)
        if m:
            prefix = m.group(1).strip()
            inner  = m.group(2).strip()
            suffix = m.group(3)
            if re.match(r"^[A-Z]\d$", inner):
                # "Something (G3)" — subject=prefix, stream=inner
                if prefix and not is_skip(prefix) and len(prefix) >= 3:
                    subject, stream = prefix, inner
            elif re.match(r"^Sec\s*\d$", inner, re.I):
                # "LSS (Sec 2)" — level from inner, subject=prefix
                if not level:
                    level = f"Sec {inner.strip()[-1]}"
                if prefix and not is_skip(prefix) and len(prefix) >= 2:
                    subject = prefix
            else:
                # "Sci (Chemistry) G3" — subject=inner
                if inner and not is_skip(inner) and len(inner) >= 3:
                    subject = inner
                    stream  = suffix or ""
                    if not stream:
                        trail = re.search(r"\)\s+([A-Z]\d)$", lt)
                        if trail:
                            stream = trail.group(1)
            if subject:
                break
            i += 1
            continue   # parenMatch found but content invalid — try next

        # Pattern: "Pure Physics G3" or "Social Studies G3" or "(Biology) G3"
        m = re.match(r"^(.+?)\s+([A-Z]\d)\s*$", lt)
        if m:
            candidate = m.group(1).strip()
            if candidate.startswith("(") and candidate.endswith(")"):
                candidate = candidate[1:-1].strip()
            if not is_skip(candidate) and len(candidate) >= 3:
                subject, stream = candidate, m.group(2)
                break

        # Plain subject (may have leading level digit "3 Social Studies")
        plain = lt.strip()
        lv_m = re.match(r"^(\d)\s+(.+)$", plain)
        if lv_m and not level:
            level = f"Sec {lv_m.group(1)}"
            plain = lv_m.group(2).strip()

        if plain and not is_skip(plain) and len(plain) >= 3:
            if plain in COMPOUND_PREFIXES:
                # "Pure" → needs a completion on the next candidate line
                if i + 1 < len(candidates) and candidates[i + 1] in COMPOUND_COMPLETIONS:
                    subject = f"{plain} {candidates[i + 1]}"
                    i += 1
                    break
                # No completion — skip this partial word
                i += 1
                continue
            subject = plain
            break

        i += 1

    if not subject or len(subject) < 3:
        return None
    if re.match(r"^(Mr|Ms|Mrs|Dr|Mdm)\s", subject, re.I):
        return None
    if re.match(r"^[A-Z]{1,4}/", subject):    # role codes like "SH/D&T"
        return None
    if re.search(r"[{}~|�]", subject):   # garbage chars in subject
        return None

    if not stream and stream_from_code:
        stream = stream_from_code

    return {"level": level, "subject": subject, "stream": stream}


# ── Main page parser ──────────────────────────────────────────────────────────

def parse_page(words, img_w, img_h, debug=False):
    """
    Parse one page's OCR output into a teacher timetable dict.
    Returns (teacher_name, {Odd/Even: {day: [{period,level,subject,stream}]}})
    """
    # ── Teacher name: topmost row, right of school-name column ────────────────
    name_words = [(t, x, y, c) for (t, x, y, c) in words
                  if y < 200 and x > img_w * 0.25 and c > 45
                  and t.lower() not in {"yuhua","secondary","school,","school",
                                        "singapore","asc","timetables"}]
    if not name_words:
        return None, {}
    name_words.sort(key=lambda w: w[1])    # left-to-right
    # Strip role suffix: "Mr Soh Ming Quan (HOD/ICT)" → "Mr Soh Ming Quan"
    teacher_name = " ".join(w[0] for w in name_words).strip()
    teacher_name = re.sub(r"\s*\([^)]+\)\s*$", "", teacher_name).strip()
    teacher_name = re.sub(r"\s+", " ", teacher_name)
    teacher_name_parts = {w.lower() for w in teacher_name.split() if len(w) > 2}

    if debug:
        print(f"  Teacher name: '{teacher_name}'", file=sys.stderr)

    # ── Period columns ────────────────────────────────────────────────────────
    period_cols = find_period_cols(words)
    if not period_cols:
        if debug:
            print("  ⚠ No period columns found", file=sys.stderr)
        return teacher_name, {}

    c_ranges   = col_ranges(period_cols)
    col_lo_x   = period_cols[0][0] - 80
    col_hi_x   = period_cols[-1][0] + 80
    col_centers = {pid: (lo + hi) / 2 for lo, hi, pid in c_ranges}
    col_width  = (period_cols[-1][0] - period_cols[0][0]) / max(len(period_cols)-1, 1)

    if debug:
        print(f"  Periods found: {len(period_cols)} "
              f"({period_cols[0][1]}–{period_cols[-1][1]})  "
              f"col_width≈{col_width:.0f}", file=sys.stderr)

    # ── Day rows ──────────────────────────────────────────────────────────────
    odd_rows, even_rows = find_row_centers(words, col_lo_x)
    row_rngs = build_row_ranges(odd_rows, even_rows, img_h)

    if debug:
        print(f"  Odd  rows: {[(d[:3].title(), round(y)) for y, d in odd_rows]}",
              file=sys.stderr)
        print(f"  Even rows: {[(d[:3].title(), round(y)) for y, d in even_rows]}",
              file=sys.stderr)

    # ── Collect content words (below header, within grid x-range) ────────────
    header_y_max = 490
    struct_tags  = {"Mon","Tue","Tues","Wed","Thu","Thurs","Fri","Odd","Even"}

    content_words = [
        (t, x, y) for (t, x, y, c) in words
        if y > header_y_max and y < img_h - 60
        and x >= col_lo_x - 50 and x <= col_hi_x + 50
        and not is_skip(t)
        and t not in struct_tags
        and len(t) > 1
    ]

    # ── Cluster nearby words into phrases ─────────────────────────────────────
    clusters = cluster_words(content_words)

    # ── Assign each cluster to exactly ONE cell ───────────────────────────────
    CHAR_WIDTH = 12   # estimated pixel width per character at 5× zoom
    cells = {}        # (week_type, day, period_id) → [line_text, ...]

    for clus in clusters:
        if not clus:
            continue

        # Cluster bounding box
        x_min = min(w[1] for w in clus)
        x_max = max(w[1] + len(w[0]) * CHAR_WIDTH for w in clus)
        x_ctr = (x_min + x_max) / 2
        y_ctr = sum(w[2] for w in clus) / len(clus)

        # Find day / week-type from y
        day_name = wk_type = None
        for (lo, hi, d, wt) in row_rngs:
            if lo <= y_ctr < hi:
                day_name, wk_type = d, wt
                break
        if not day_name:
            continue

        # Assign to the single nearest column (by center distance)
        best_pid  = None
        best_dist = float("inf")
        for pid, cx in col_centers.items():
            dist = abs(x_ctr - cx)
            if dist < best_dist:
                best_dist = dist
                best_pid  = pid
        if best_pid is None or best_dist > col_width * 0.75:
            continue

        clus_text = " ".join(w[0] for w in clus)
        key = (wk_type, day_name, best_pid)
        cells.setdefault(key, []).append(clus_text)

    # ── Parse each cell ───────────────────────────────────────────────────────
    timetable = {}
    for (wt, day, pid), texts in cells.items():
        result = parse_class(texts, teacher_name_parts=teacher_name_parts)
        if not result:
            continue
        timetable.setdefault(wt, {}).setdefault(day, [])
        existing = timetable[wt][day]
        if not any(e["period"] == pid for e in existing):
            existing.append({"period": pid, **result})
            if debug:
                flag = "" if (result["level"] and result["stream"]) else " ⚠"
                print(f"    [{wt}] {day[:3].title()} P{pid:2d} → "
                      f"{result['level']:5s} {result['subject']:22s} "
                      f"{result['stream']}{flag}", file=sys.stderr)
                if flag:
                    print(f"         raw: {' | '.join(texts)}", file=sys.stderr)

    return teacher_name, timetable


# ── CSV generation ────────────────────────────────────────────────────────────

WEEKS   = ["Odd", "Even"]
DAYS    = [("Mon","monday"),("Tue","tuesday"),("Wed","wednesday"),
           ("Thu","thursday"),("Fri","friday")]
PERIODS = list(range(1, 17))


def generate_csv(teachers):
    """teachers = [{name, timetable}]  →  CSV string"""
    headers = ["Teacher"]
    for wk in WEEKS:
        for (da, _) in DAYS:
            for p in PERIODS:
                headers.append(f"{wk} {da} P{p}")

    out = io.StringIO()
    w = csv.writer(out, quoting=csv.QUOTE_MINIMAL)
    w.writerow(headers)

    for t in teachers:
        row = [t["name"]]
        for wk in WEEKS:
            for (_, df) in DAYS:
                for p in PERIODS:
                    slots = t["timetable"].get(wk, {}).get(df, [])
                    slot  = next((s for s in slots if s["period"] == p), None)
                    if slot:
                        lv   = slot["level"].replace("Sec ", "") if slot["level"] else ""
                        cell = f"{lv} {slot['subject']} {slot['stream']}".strip()
                        row.append(cell)
                    else:
                        row.append("")
        w.writerow(row)

    return out.getvalue()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python convert_timetable.py <timetable.pdf> [output.csv] [--debug]",
              file=sys.stderr)
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        print(f"Error: file not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    debug    = "--debug" in sys.argv
    out_path = next((a for a in sys.argv[2:] if not a.startswith("--")), None)

    doc = fitz.open(pdf_path)
    print(f"Processing {doc.page_count} pages…", file=sys.stderr)

    teachers = []
    for pg in range(doc.page_count):
        print(f"\nPage {pg+1}:", file=sys.stderr)
        words, iw, ih = ocr_page(doc[pg], zoom=5)
        name, timetable = parse_page(words, iw, ih, debug=debug)
        if not name:
            print("  ⚠ Could not determine teacher name — skipping", file=sys.stderr)
            continue

        slot_count = sum(len(s) for wt in timetable.values() for s in wt.values())
        print(f"  → {name}: {slot_count} slots", file=sys.stderr)

        # Merge duplicate pages for same teacher
        existing = next((t for t in teachers if t["name"] == name), None)
        if existing:
            for wt, days in timetable.items():
                for day, slots in days.items():
                    tbl = existing["timetable"].setdefault(wt, {}).setdefault(day, [])
                    for slot in slots:
                        if not any(e["period"] == slot["period"] for e in tbl):
                            tbl.append(slot)
        else:
            teachers.append({"name": name, "timetable": timetable})

    print(f"\nTotal teachers: {len(teachers)}", file=sys.stderr)
    csv_data = generate_csv(teachers)

    if out_path:
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            f.write(csv_data)
        print(f"Saved to {out_path}", file=sys.stderr)
    else:
        print(csv_data)


if __name__ == "__main__":
    main()
