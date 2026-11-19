class Image:  # never used: Stage Chart draws no bitmaps
    pass


def open(*a, **k):
    raise RuntimeError("Images are not supported in Stage Chart")
