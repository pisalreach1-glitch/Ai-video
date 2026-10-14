from pathlib import Path
from zipfile import ZipFile
root = Path(__file__).resolve().parent
archive = root.parent / 'khmer-motion-project.zip'
if not archive.exists():
    raise SystemExit('Download khmer-motion-project.zip from the repository root first.')
with ZipFile(archive) as z:
    for source, destination in [
        ('khmer-motion/public/source.mov', 'public/IMG_5777_small.MOV'),
        ('khmer-motion/public/fonts/NotoSansKhmer-Bold.ttf', 'public/fonts/NotoSansKhmer-Bold.ttf'),
        ('khmer-motion/public/fonts/NotoSansKhmer-Regular.ttf', 'public/fonts/NotoSansKhmer-Regular.ttf'),
    ]:
        target = root / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(z.read(source))
print('Footage and Khmer fonts ready.')
