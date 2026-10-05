from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Pt
from datetime import datetime
import pandas as pd
from io import BytesIO
import json

# ---------- optional: Pillow helpers (with fallback) ----------
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True

    def _px_from_emu(emu, dpi=96):
        # 1 inch = 914400 EMU; pixels = inches * dpi
        return int((emu / 914400.0) * dpi)

    def _load_font(pt):
        # Try common fonts across OSes; prefer Helvetica Neue. Fall back to bitmap font.
        for candidate in (
            # macOS preferred
            "/System/Library/Fonts/HelveticaNeue.dfont",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/Library/Fonts/HelveticaNeue.ttf",
            "/Library/Fonts/Helvetica.ttf",
            # Windows
            "C:/Windows/Fonts/calibri.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/helvetica.ttf",
            # Linux (common)
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            # macOS
            "/System/Library/Fonts/Supplemental/Calibri.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            # Generic fallbacks if fonts are on PATH
            "HelveticaNeue.ttf", "HelveticaNeue.dfont", "Helvetica.ttf",
            "calibri.ttf", "Calibri.ttf", "Arial.ttf", "DejaVuSans.ttf",
        ):
            try:
                return ImageFont.truetype(candidate, int(pt))
            except Exception:
                pass
        return ImageFont.load_default()

    def _text_size_px(text, font):
        # measure text bounding box in pixels
        img = Image.new("RGB", (1, 1))
        draw = ImageDraw.Draw(img)
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        return w, h

    def _wrap_to_width(text, font, max_width_px):
        # greedy word-wrap by pixel width
        words = text.split()
        lines, line = [], ""
        for w in words:
            test = (line + " " + w).strip()
            if _text_size_px(test, font)[0] <= max_width_px or not line:
                line = test
            else:
                lines.append(line)
                line = w
        if line:
            lines.append(line)
        # also respect existing newlines
        out = []
        for block in "\n".join(lines).split("\n"):
            if not block:
                out.append("")
                continue
            # re-wrap each newline block (in case original text had \n)
            words2, line2 = block.split(), ""
            for w2 in words2:
                test2 = (line2 + " " + w2).strip()
                if _text_size_px(test2, font)[0] <= max_width_px or not line2:
                    line2 = test2
                else:
                    out.append(line2)
                    line2 = w2
            if line2:
                out.append(line2)
        return out

    def shrink_text_to_fit(text_frame, shape, min_pt=10, max_pt=40, line_spacing_ratio=0.15):
        """Binary search a font size that fits within shape (no expanding)."""
        # Build full text (paragraphs joined by \n) to estimate layout
        paras = []
        for p in text_frame.paragraphs:
            paras.append("".join(r.text for r in p.runs))
        full_text = "\n".join(paras).strip()
        if not full_text:
            return

        # Respect text frame margins if available
        try:
            ml = getattr(text_frame, "margin_left", 0) or 0
            mr = getattr(text_frame, "margin_right", 0) or 0
            mt = getattr(text_frame, "margin_top", 0) or 0
            mb = getattr(text_frame, "margin_bottom", 0) or 0
        except Exception:
            ml = mr = mt = mb = 0

        inner_width_emu = max(0, int(shape.width) - int(ml) - int(mr))
        inner_height_emu = max(0, int(shape.height) - int(mt) - int(mb))

        max_w = _px_from_emu(inner_width_emu)
        max_h = _px_from_emu(inner_height_emu)

        lo, hi = min_pt, max_pt
        best = min_pt
        while lo <= hi:
            mid = (lo + hi) // 2
            font = _load_font(mid)

            # wrap each paragraph to width, compute total height
            lines_total = []
            for para in full_text.split("\n"):
                if para.strip():
                    lines_total += _wrap_to_width(para, font, max_w)
                else:
                    lines_total.append("")  # preserve blank line

            # compute height with simple line spacing
            ascent, descent = font.getmetrics() if hasattr(font, "getmetrics") else (mid, int(mid*0.25))
            line_h = ascent + descent
            extra = int(line_h * line_spacing_ratio)
            total_h = len(lines_total) * line_h + max(0, len(lines_total)-1) * extra

            # widest line check
            widest = 0
            for ln in lines_total:
                w, _ = _text_size_px(ln, font)
                widest = max(widest, w)

            if widest <= max_w and total_h <= max_h:
                best = mid
                lo = mid + 1  # try larger
            else:
                hi = mid - 1   # too big → go smaller

        # apply the chosen size to all runs and ensure consistent font name
        for p in text_frame.paragraphs:
            for r in p.runs:
                r.font.size = Pt(best)
                # Prefer Helvetica Neue; if unavailable, PowerPoint will substitute.
                try:
                    r.font.name = "Helvetica Neue"
                except Exception:
                    try:
                        r.font.name = "Helvetica"
                    except Exception:
                        try:
                            r.font.name = "Arial"
                        except Exception:
                            pass

except Exception:
    PIL_AVAILABLE = False

    def shrink_text_to_fit(text_frame, shape, min_pt=10, max_pt=40, *_args, **_kwargs):
        """Heuristic fallback when Pillow isn't installed."""
        text = text_frame.text.strip()
        if not text:
            return
        # crude size guess based on character count vs shape width
        length = max(1, len(text))
        # shrink roughly after ~40 chars
        size = max(min_pt, min(max_pt, int(max_pt - max(0, length-40) * 0.4)))
        for p in text_frame.paragraphs:
            for r in p.runs:
                r.font.size = Pt(size)
# ---------- replacement over shapes ----------

def replace_in_text_shape(shape,mapping,replaced_counts):
    """Replace placeholders inside a text shape; then shrink-to-fit."""
    tf = shape.text_frame
    changed_any = False
    date_paragraphs = []  # track paragraphs with [DATE] replacement
    avg_cpm_paragraphs = []  # track paragraphs with [avg_cpm] replacement
    campaign_name_paragraphs = []  # track paragraphs with [campaign_name] replacement

    # Make sure wrapping is enabled so long lines break instead of overflow
    try:
        tf.word_wrap = True
    except Exception:
        pass

    for para in tf.paragraphs:
        full = "".join(run.text for run in para.runs) or ""
        new = full
        date_hit = False
        avg_cpm_hit = False
        campaign_name_hit = False
        campaign_name_value = ""
        for ph, val in mapping.items():
            cnt = new.count(ph)
            if cnt:
                new = new.replace(ph, str(val))
                replaced_counts[ph] += cnt
                changed_any = True
                # Track if this is a date replacement
                if ph.lower() == "[date]":
                    date_hit = True
                # Track if this is an avg_cpm replacement
                if ph.lower() == "[avg_cpm]":
                    avg_cpm_hit = True
                # Track if this is a campaign_name replacement
                if ph.lower() == "[campaign_name]":
                    campaign_name_hit = True
                    campaign_name_value = str(val)
        if new != full:
            if para.runs:
                para.runs[0].text = new
                for r in para.runs[1:]:
                    r.text = ""
            else:
                run = para.add_run()
                run.text = new
            # Remember date paragraphs
            if date_hit:
                date_paragraphs.append(para)
            # Remember avg_cpm paragraphs
            if avg_cpm_hit:
                avg_cpm_paragraphs.append(para)
            # Remember campaign_name paragraphs and value
            if campaign_name_hit:
                campaign_name_paragraphs.append((para, campaign_name_value))

    if changed_any:
        # shrink text to fit the existing box (no expansion)
        shrink_text_to_fit(tf, shape)

        # Re-apply 8pt font size for date paragraphs
        if date_paragraphs:
            for para in date_paragraphs:
                for r in para.runs:
                    r.font.size = Pt(8)

        # Re-apply 22pt font size for avg_cpm paragraphs
        if avg_cpm_paragraphs:
            for para in avg_cpm_paragraphs:
                for r in para.runs:
                    r.font.size = Pt(22)

        # Apply character-based font sizing for campaign_name paragraphs
        if campaign_name_paragraphs:
            for para, campaign_name in campaign_name_paragraphs:
                name_length = len(campaign_name)

                # Determine font size based on character length
                if name_length <= 20:
                    font_size = 32
                elif name_length <= 30:
                    font_size = 30
                elif name_length <= 40:
                    font_size = 28
                elif name_length <= 60:
                    font_size = 26
                elif name_length <= 80:
                    font_size = 24
                else:
                    font_size = 22

                # Apply the calculated font size
                for r in para.runs:
                    r.font.size = Pt(font_size)

# def walk_shapes(shapes):
def walk_shapes(shapes,mapping,replaced_counts):
    """Recursively process all shapes (groups, text boxes, tables)."""
    for shape in shapes:
        # groups
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            # Recurse into grouped shapes
            try:
                walk_shapes(shape.shapes,mapping,replaced_counts)
            except Exception:
                pass
            continue

        # text boxes / placeholders
        if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
            replace_in_text_shape(shape,mapping,replaced_counts)

        # tables: replace only (no shrink here to avoid layout shifts)
        if getattr(shape, "has_table", False) and shape.has_table:
            tbl = shape.table
            for row in tbl.rows:
                for cell in row.cells:
                    tf = cell.text_frame
                    for para in tf.paragraphs:
                        full = "".join(run.text for run in para.runs) or ""
                        new = full
                        changed = False
                        date_hit = False
                        avg_cpm_hit = False
                        for ph, val in mapping.items():
                            cnt = new.count(ph)
                            if cnt:
                                new = new.replace(ph, str(val))
                                replaced_counts[ph] += cnt
                                changed = True
                                # Track if this is a date replacement
                                if ph.lower() == "[date]":
                                    date_hit = True
                                # Track if this is an avg_cpm replacement
                                if ph.lower() == "[avg_cpm]":
                                    avg_cpm_hit = True
                        if changed:
                            if para.runs:
                                para.runs[0].text = new
                                for r in para.runs[1:]:
                                    r.text = ""
                            else:
                                run = para.add_run()
                                run.text = new
                            # Set 8pt font for date cells
                            if date_hit:
                                for r in para.runs:
                                    r.font.size = Pt(8)
                            # Set 22pt font for avg_cpm cells
                            if avg_cpm_hit:
                                for r in para.runs:
                                    r.font.size = Pt(22)
                                

def get_ppt_report(mapping: dict,template: Presentation):
    
    print("inside get_ppt_report")
    
    prs=template
    replaced_counts = {k: 0 for k in mapping}
    for slide in prs.slides:
        walk_shapes(slide.shapes,mapping,replaced_counts)

        # Save to memory buffer
    pptx_buffer = BytesIO()
    prs.save(pptx_buffer)
    pptx_buffer.seek(0)   # reset piointer for reading
    return pptx_buffer