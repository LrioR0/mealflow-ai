#!/usr/bin/env python3
"""HowToCook(md) → MealFlow 懒人宝典 JSON 转换脚本。

数据源: https://github.com/Anduin2017/HowToCook (稀疏克隆, 仅 dishes/**.md)
输出:   apps/web/public/data/recipes_howtocook.json (ExtendedRecipeRaw 结构 + image/steps 扩展)

图片不落盘, 一律改写为 jsDelivr CDN 直链 (浏览器按需加载)。
用法:
    python scripts/howtocook_to_json.py                 # 默认路径
    python scripts/howtocook_to_json.py --repo <路径>   # 指定 HowToCook 克隆目录
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

DEFAULT_IMAGE_BASE = "https://cdn.jsdelivr.net/gh/Anduin2017/HowToCook@master/"

CATEGORY_MAP = {
    "meat_dish": "荤菜",
    "vegetable_dish": "素菜",
    "soup": "汤",
    "staple": "主食",
    "breakfast": "早餐",
    "aquatic": "水产",
    "dessert": "甜品",
    "condiment": "酱料",
    "drink": "饮品",
    "semi-finished": "半成品",
}
CATEGORY_ORDER = ["荤菜", "素菜", "汤", "主食", "早餐", "水产", "甜品", "酱料", "饮品", "半成品"]

TOOL_KEYWORDS = ("烤箱", "空气炸锅", "微波炉", "电饭煲")
TOOL_WORDS = ("水果刀", "菜刀", "剪刀", "碗", "筷子", "工具")

CALORIE_RE = re.compile(r"预估卡路里[:：]\s*([0-9][0-9,，]*)\s*大卡")
DIFFICULTY_RE = re.compile(r"预估烹饪难度[:：]\s*([★☆]+)")


def git_list_files(repo: Path) -> list[str]:
    """从 git 树里拿 dishes 下全部文件 (含被 sparse 排除的图片, 中文不转义)。"""
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", "HEAD", "dishes"],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def section_body(md: str, title: str) -> list[str]:
    """取指定 ## 小节的列表项 (支持 - / * / + / 数字列表)。"""
    match = re.search(rf"^##\s+{re.escape(title)}\s*$(.*?)(?=^##\s+|\Z)", md, re.MULTILINE | re.DOTALL)
    if not match:
        return []
    items = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if re.match(r"^(?:[-*+]|\d+[.、)])\s+", line):
            items.append(re.sub(r"^(?:[-*+]|\d+[.、)])\s+", "", line).strip())
    return items


def clean_ingredient(text: str) -> str:
    """去括注/反引号;剔除注释行与工具条目, 只留食材。"""
    if text.startswith(("注", "工具", "贴士")):
        return ""
    stripped = (
        re.sub(r"[（(](?:别称|推介|推荐)[^）)]*[）)]", "", text).replace("`", "").strip()
    )
    if any(stripped.startswith(w) or stripped == w for w in TOOL_WORDS):
        return ""
    if stripped.endswith(("刀", "勺")) and len(stripped) <= 3:
        return ""
    return stripped


def stars_to_difficulty(md: str, step_count: int) -> str:
    match = DIFFICULTY_RE.search(md)
    if match:
        stars = match.group(1).count("★")
        if stars <= 2:
            return "简单"
        if stars == 3:
            return "中等"
        return "困难"
    if step_count <= 5:
        return "简单"
    if step_count <= 9:
        return "中等"
    return "困难"


def extract_tools(ingredients: list[str]) -> str:
    tools: list[str] = []
    for item in ingredients:
        for kw in TOOL_KEYWORDS:
            if kw in item and kw not in tools:
                tools.append(kw)
        if "锅" in item and not any(kw in item for kw in TOOL_KEYWORDS) and "大锅" not in tools:
            tools.append("大锅")
    return "、".join(tools)


def pick_image(md_rel: Path, images_by_dir: dict[Path, list[str]]) -> str | None:
    """优先 <菜名>.jpg / 成品.jpg, 否则取同目录第一张图。"""
    candidates = images_by_dir.get(md_rel.parent, [])
    if not candidates:
        return None
    stem = md_rel.stem
    for name in (f"{stem}.jpg", f"{stem}.jpeg", f"{stem}.png", "成品.jpg", "成品.jpeg", "成品.png"):
        if name in candidates:
            return name
    return candidates[0]


def convert(repo: Path, out: Path, image_base: str) -> None:
    all_files = git_list_files(repo)
    images = [f for f in all_files if re.search(r"\.(jpg|jpeg|png|webp)$", f, re.IGNORECASE)]
    mds = [f for f in all_files if f.endswith(".md")]

    images_by_dir: dict[Path, list[str]] = {}
    for img in images:
        images_by_dir.setdefault(Path(img).parent, []).append(Path(img).name)

    recipes: list[dict] = []
    skipped = 0
    for md_path in sorted(mds):
        rel = Path(md_path)
        if "template" in rel.parts:
            skipped += 1
            continue
        category = CATEGORY_MAP.get(rel.parts[1])
        if category is None:
            skipped += 1
            continue

        md_text = (repo / md_path).read_text(encoding="utf-8")
        title_match = re.search(r"^#\s+(.+?)\s*$", md_text, re.MULTILINE)
        name = title_match.group(1).strip() if title_match else rel.stem
        name = re.sub(r"的做法$", "", name).strip() or rel.stem

        ingredients_raw = section_body(md_text, "必备原料和工具")
        ingredients = [clean_ingredient(x) for x in ingredients_raw if clean_ingredient(x)]
        steps = [
            re.sub(r"[（(]约?\d+[-~–]\d+分钟[)）]", "", s).strip()
            for s in section_body(md_text, "操作")
            if s.strip()
        ]

        cal_match = CALORIE_RE.search(md_text)
        heat = int(cal_match.group(1).replace(",", "").replace("，", "")) if cal_match else None

        image_name = pick_image(rel, images_by_dir)
        image_url = None
        if image_name:
            full = f"{rel.parent.as_posix()}/{image_name}"
            image_url = image_base + quote(full)

        recipes.append(
            {
                "name": name,
                "stuff": "、".join(ingredients),
                "difficulty": stars_to_difficulty(md_text, len(steps)),
                "tags": [],
                "methods": "",
                "tools": extract_tools(ingredients_raw),
                "category": category,
                "heat": heat,
                "likes": 0,
                "collect": 0,
                "image": image_url,
                "steps": steps,
                "source": f"https://github.com/Anduin2017/HowToCook/blob/master/{rel.parent.as_posix()}/{quote(rel.name)}",
            }
        )

    recipes.sort(key=lambda r: (CATEGORY_ORDER.index(r["category"]), r["name"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(recipes, ensure_ascii=False, indent=1), encoding="utf-8")

    with_image = sum(1 for r in recipes if r["image"])
    by_cat: dict[str, int] = {}
    for r in recipes:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    print(f"完成: {len(recipes)} 道菜谱 -> {out}")
    print(f"带图片: {with_image} / {len(recipes)};跳过(模板等): {skipped}")
    for cat in CATEGORY_ORDER:
        if cat in by_cat:
            print(f"  {cat}: {by_cat[cat]}")


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    default_repo = script_dir.parent.parent / "HowToCook"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=default_repo, help="HowToCook 克隆目录")
    parser.add_argument(
        "--out",
        type=Path,
        default=script_dir.parent / "apps/web/public/data/recipes_howtocook.json",
        help="输出 JSON 路径",
    )
    parser.add_argument("--image-base", default=DEFAULT_IMAGE_BASE, help="图片 CDN 前缀")
    args = parser.parse_args()
    convert(args.repo, args.out, args.image_base)


if __name__ == "__main__":
    main()
