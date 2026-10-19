"""Generate the executable icon from the same artwork as the window and tray."""
import sys
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
from campus_guard import App

target = root / 'assets' / 'campus_guard.ico'
target.parent.mkdir(parents=True, exist_ok=True)
App.icon_image().resize((256, 256), Image.Resampling.LANCZOS).save(
    target, format='ICO', sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
print('Generated', target.name)
