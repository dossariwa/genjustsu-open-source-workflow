"""Offline integration smoke test: raw masks preserve exact decoded depth colors."""
import tempfile
from pathlib import Path
import numpy as np
from PIL import Image
from pipeline import writer, put, finish, composite, frames

with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp)
    (p / 'masks').mkdir()
    arrays = {
        'original': np.full((64, 64, 3), (180, 40, 40), dtype=np.uint8),
        'depth': np.full((64, 64, 3), (33, 149, 221), dtype=np.uint8),
    }
    for name, array in arrays.items():
        c, s = writer(p / (name + '.mp4'), 64, 64, lossless=True)
        for index in range(4):
            put(c, s, array, index)
        finish(c, s)
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[16:48, 16:48] = 255
    for index in range(4):
        Image.fromarray(mask).save(p / 'masks' / f'mask_{index:06d}.png')
    assert composite(p / 'original.mp4', p / 'depth.mp4', p / 'masks', p) == 4
    decoded = list(frames(p / 'composite.mp4'))
    assert len(decoded) == 4
    expected = np.where((mask > 0)[:, :, None], arrays['depth'], arrays['original'])
    for array in decoded:
        np.testing.assert_array_equal(array, expected)
    print('PASS: raw masks select exact colored depth pixels, RGB background preserved, four aligned frames exported.')
