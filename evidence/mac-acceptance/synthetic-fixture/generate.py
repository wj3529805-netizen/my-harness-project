"""Synthetic, non-client DNG compatibility candidates; no existing source edits."""
from pathlib import Path
import json
import hashlib
import numpy as np
import tifffile

root = Path(__file__).parent
height, width = 512, 768
y, x = np.indices((height, width), dtype=np.uint32)
red = 4096 + x * 45000 // (width - 1)
green = 4096 + y * 45000 // (height - 1)
blue = 4096 + (x + y) * 45000 // (width + height - 2)
rgb = np.stack([red + np.zeros_like(y), green + np.zeros_like(x), blue], axis=-1).astype(np.uint16)
cfa = np.empty((height, width), dtype=np.uint16)
cfa[0::2, 0::2] = rgb[0::2, 0::2, 0]
cfa[0::2, 1::2] = rgb[0::2, 1::2, 1]
cfa[1::2, 0::2] = rgb[1::2, 0::2, 1]
cfa[1::2, 1::2] = rgb[1::2, 1::2, 2]

def tag(code, dtype, count, value):
    return (code, dtype, count, value, False)

matrix = (32406,10000,-15372,10000,-4986,10000,-9689,10000,18758,10000,415,10000,557,10000,-2040,10000,10570,10000)
common = [
    tag(254, 'I', 1, 0),
    tag(271, 's', 0, 'Cetacea Test'),
    tag(272, 's', 0, 'Synthetic DNG v2'),
    tag(274, 'H', 1, 1),
    tag(50706, 'B', 4, (1,1,0,0)),
    tag(50707, 'B', 4, (1,1,0,0)),
    tag(50708, 's', 0, 'Cetacea Synthetic DNG v2 Test'),
    tag(50721, '2i', 9, matrix),
    tag(50727, '2I', 3, (1,1,1,1,1,1)),
    tag(50728, '2I', 3, (1,1,1,1,1,1)),
    tag(50730, '2i', 1, (0,1)),
    tag(50731, '2I', 1, (1,1)),
    tag(50732, '2I', 1, (1,1)),
    tag(50778, 'H', 1, 21),
]
geometry = [
    tag(50713, 'H', 2, (1,1)),
    tag(50714, '2I', 1, (0,1)),
    tag(50717, 'I', 1, 65535),
    tag(50718, '2I', 2, (1,1,1,1)),
    tag(50719, 'I', 2, (0,0)),
    tag(50720, 'I', 2, (width,height)),
    tag(50738, '2I', 1, (1,1)),
    tag(50829, 'I', 4, (0,0,height,width)),
]
cfa_tags = [
    tag(33421, 'H', 2, (2,2)),
    tag(33422, 'B', 4, (0,1,1,2)),
    tag(50710, 'B', 3, (0,1,2)),
    tag(50711, 'H', 1, 1),
]

outputs = []
def record(name):
    p = root / name
    outputs.append({'file': name, 'size': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})

p = root / 'CETACEA_V2_CFA.dng'
assert not p.exists()
tifffile.imwrite(p, cfa, photometric=32803, metadata=None, software='Cetacea test fixture v2', extratags=common+geometry+cfa_tags)
record(p.name)

p = root / 'CETACEA_V2_CFA_SUBIFD.dng'
assert not p.exists()
thumb = (rgb[::4,::4] >> 8).astype(np.uint8)
with tifffile.TiffWriter(p) as tw:
    tw.write(thumb, photometric='rgb', metadata=None, subfiletype=1, subifds=1,
             software='Cetacea test fixture v2', extratags=[t for t in common if t[0] != 254])
    tw.write(cfa, photometric=32803, metadata=None, subfiletype=0,
             extratags=geometry+cfa_tags)
record(p.name)

p = root / 'CETACEA_V2_LINEAR.dng'
assert not p.exists()
tifffile.imwrite(p, rgb, photometric=34892, planarconfig='contig', metadata=None,
                 software='Cetacea test fixture v2', extratags=common+geometry)
record(p.name)
(root / 'manifest.json').write_text(json.dumps({'marker':'SYNTHETIC TEST DATA; not Nikon/NEF acceptance', 'candidates':outputs}, indent=2))
print(json.dumps(outputs, indent=2))
