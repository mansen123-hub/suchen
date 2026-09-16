from lieferschein_suche.preview import _ocr_match_rects


def test_ocr_highlight_spans_hyphenated_words() -> None:
    raw = '[{"text":"LS","x":1,"y":2,"width":10,"height":5},{"text":"-","x":12,"y":2,"width":2,"height":5},{"text":"2026","x":15,"y":2,"width":20,"height":5},{"text":"-001","x":36,"y":2,"width":18,"height":5}]'
    rects = _ocr_match_rects(raw, "LS-2026-001")
    assert rects
    assert rects[0].x0 == 1
    assert rects[0].x1 == 54

