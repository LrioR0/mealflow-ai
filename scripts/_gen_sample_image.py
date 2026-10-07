"""示例:用统一模板为指定菜名生成图片,对比 cogview-3-flash 与 cogview-4。

用法: python scripts/_gen_sample_image.py [菜名]
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
env_text = (ROOT / ".env").read_text(encoding="utf-8")
m = re.search(r"^LLM_API_KEY\s*=\s*(.+?)\s*$", env_text, re.MULTILINE)
if not m:
    sys.exit("LLM_API_KEY not found in .env")
key = m.group(1).strip()
base = (re.search(r"^LLM_BASE_URL\s*=\s*(.+?)\s*$", env_text, re.MULTILINE).group(1).strip()).rstrip("/")

dish = sys.argv[1] if len(sys.argv) > 1 else "番茄炒鸡蛋"
PROMPT = (
    f"一盘家常{dish},盛放在浅米色陶瓷餐盘里,"
    "美食摄影,柔和自然光,干净浅色背景,写实风格,构图居中,高清"
)

out_dir = ROOT / "apps/web/public/data/dish-images"
out_dir.mkdir(parents=True, exist_ok=True)

for model in ("cogview-3-flash", "cogview-4"):
    tag = "flash" if "flash" in model else "cogview4"
    out = out_dir / f"{dish}-{tag}.jpg"
    print(f"--- {model} generating ...")
    try:
        req = urllib.request.Request(
            f"{base}/images/generations",
            data=json.dumps({"model": model, "prompt": PROMPT}).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        url = body["data"][0]["url"]
        with urllib.request.urlopen(url, timeout=60) as img, open(out, "wb") as f:
            f.write(img.read())
        print(f"saved: {out} ({out.stat().st_size / 1024:.0f} KB)")
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED {model}: {exc}")
