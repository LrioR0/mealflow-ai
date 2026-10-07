#!/usr/bin/env python3
"""合并 B 站菜谱库(recipes_extended.json)与 HowToCook(recipes_howtocook.json)。

清洗与去重:
  - 去垃圾键、食材杂质(反引号/注释行/工具行)
  - 修复 B 站源「几乎全部标成素菜」的分类:按菜名+食材关键词推断(鱼香X 先剥离)
  - 无效记录剔除:空名/名称过短/无食材无步骤无视频无图片的空壳
  - 两级去重:精确同名合并;再按「核心名」合并别名重复
    (简易红烧肉=红烧肉、家常黄焖鸡(多调料版)=黄焖鸡、蒸蛋羹(硬核0失败版)=蒸蛋羹)
  - 分类冲突以 HowToCook 的人工分类为准,但其「半成品」特殊分类不覆盖正常分类
输出: apps/web/public/data/recipes_merged.json (ExtendedRecipeRaw 同构 + image/steps/source)

用法: python scripts/merge_recipes.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "apps/web/public/data"

EXT_PATH = DATA_DIR / "recipes_extended.json"
HTC_PATH = DATA_DIR / "recipes_howtocook.json"
OUT_PATH = DATA_DIR / "recipes_merged.json"

CATEGORY_ORDER = ["荤菜", "素菜", "汤", "主食", "早餐", "水产", "甜品", "酱料", "饮品", "半成品"]
TOOL_WORDS = ("水果刀", "菜刀", "剪刀", "碗", "筷子", "工具")

# 规则按此顺序短路匹配;SAUCE/DRINK 用结尾锚避免误伤菜名(酱牛肉/开水白菜)
RE_SOUP = re.compile(r"汤|羹")
RE_SAUCE = re.compile(r"酱$|酱油$|蘸料|料汁|油泼辣子|凉拌汁|调味汁|^葱油$|^辣椒油$")
RE_DRINK = re.compile(r"茶$|奶茶|奶昔|果汁|豆浆|酸梅汤|咖啡|汽水|柠檬水|椰奶|饮$|酸奶|水$")
RE_DESSERT = re.compile(
    r"蛋糕|布丁|双皮奶|慕斯|曲奇|饼干|蛋挞|冰淇淋|糖水|银耳|桃胶|杨枝甘露|甜品|泡芙|雪媚娘|提拉米苏|华夫|舒芙蕾|甜甜圈|班戟"
)
RE_STAPLE = re.compile(
    r"饭$|炒饭|烩饭|煲饭|焖饭|拌饭|面$|拌面|炒面|焖面|意面|热干面|粉$|炒粉|螺蛳粉|酸辣粉|凉粉|粥|饺|馄饨|包子|馒头|花卷|油条|吐司|三明治|米线|河粉|牛河|方便面|饼$|卷饼|面包|汉堡|披萨"
)
RE_AQUATIC = re.compile(
    r"鱼|虾|蟹|鳕|鲈|鳝|鳗|鱿鱼|墨鱼|贝|蛤|蛏|鲍|海参|田螺|三文鱼|金枪鱼|带鱼|黄鱼|龙利|巴沙"
)
RE_BREAKFAST = re.compile(r"早餐|厚蛋烧|玉子烧|煎蛋|水波蛋|蛋羹|窝蛋")
RE_MEAT = re.compile(
    r"肉|鸡|鸭|鹅|牛|羊|排骨|猪蹄|肘|培根|火腿|腊肠|香肠|午餐肉|蛋|鸡爪|鸡翅|鸡腿|鸡脯|五花肉|牛腩|牛柳"
)


def norm_key(name: str) -> str:
    """一级去重键:去掉全部空白,统一全角/半角标点。"""
    key = re.sub(r"\s+", "", name)
    return key.replace("（", "(").replace("）", ")").replace("：", ":").replace("，", ",").lower()


_CORE_PREFIX = re.compile(r"^(家常|简易|快手|超简单|正宗|改良)")


def core_key(name: str) -> str:
    """二级去重键:再去掉括号备注与修饰词,合并「简易红烧肉」=「红烧肉」类别名重复。"""
    k = re.sub(r"[（(][^()（）]*[)）]", "", norm_key(name))
    k = _CORE_PREFIX.sub("", k)
    return re.sub(r"(版|的做法)$", "", k)


def clean_token(text: str) -> str:
    """食材条目清洗:去括注/反引号,剔除注释行与工具行。"""
    if text.startswith(("注", "工具", "贴士")):
        return ""
    stripped = re.sub(r"[（(](?:别称|推介|推荐)[^）)]*[）)]", "", text).replace("`", "").strip()
    if any(stripped.startswith(w) or stripped == w for w in TOOL_WORDS):
        return ""
    if stripped.endswith(("刀", "勺")) and len(stripped) <= 3:
        return ""
    return stripped


def split_stuff(value: object) -> list[str]:
    """stuff 字段(顿号/逗号分隔或数组)→ 清洗后的食材列表。"""
    if isinstance(value, list):
        tokens = [str(v) for v in value]
    else:
        tokens = re.split(r"[、,，/;；]+", str(value or ""))
    out: list[str] = []
    for token in tokens:
        cleaned = clean_token(token.strip())
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def guess_category(name: str, stuff_tokens: list[str]) -> str:
    """按菜名(优先)再食材推断分类;鱼香X 先剥掉「鱼香」避免误判水产。"""
    text = name.replace("鱼香", "", 1) if name.startswith("鱼香") else name
    for pattern, category in (
        (RE_SOUP, "汤"),
        (RE_SAUCE, "酱料"),
        (RE_DRINK, "饮品"),
        (RE_DESSERT, "甜品"),
        (RE_STAPLE, "主食"),
        (RE_AQUATIC, "水产"),
        (RE_BREAKFAST, "早餐"),
        (RE_MEAT, "荤菜"),
    ):
        if pattern.search(text):
            return category
    joined = "、".join(stuff_tokens)
    if RE_AQUATIC.search(joined):
        return "水产"
    if RE_MEAT.search(joined):
        return "荤菜"
    return "素菜"


def normalize_difficulty(value: object) -> str:
    text = str(value or "").strip()
    return text if text in ("简单", "中等", "困难") else "中等"


def as_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def as_heat(value: object) -> int | None:
    try:
        num = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return int(num) if num == num else None  # 过滤 NaN


def to_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [t.strip() for t in re.split(r"[、,，/;；]+", text) if t.strip()]


def make_record(raw: dict, *, source: str) -> dict | None:
    """两种源数据统一为输出结构;返回 None 表示无效记录。"""
    name = str(raw.get("name") or "").strip()
    stuff = "、".join(split_stuff(raw.get("stuff")))
    image = (str(raw.get("image")).strip() or None) if raw.get("image") else None
    bv = str(raw.get("bv") or "").strip() or None
    steps = [str(s).strip() for s in raw.get("steps") or [] if str(s).strip()]
    # 无效记录:无名称/过短,名称是解析残渣(.md 后缀、以斜杠开头结尾),
    # 或内容全空(无法展示也无法烹饪)。名称中间的「/」是别名分隔(油墩子/腰子饼),保留。
    if len(name) < 2 or re.search(r"\.md$", name) or name.startswith(("/", "\\")) or name.endswith(("/", "\\")):
        return None
    if not stuff and not steps and not bv and not image:
        return None
    return {
        "name": name,
        "stuff": stuff,
        "bv": bv,
        "difficulty": normalize_difficulty(raw.get("difficulty")),
        "tags": to_list(raw.get("tags")),
        "methods": str(raw.get("methods") or "").strip(),
        "tools": str(raw.get("tools") or "").strip(),
        # B站源分类是推断的;HowToCook 分类是人工维护的
        "category": str(raw.get("category") or "").strip(),
        "heat": as_heat(raw.get("heat")),
        "likes": as_int(raw.get("likes")),
        "collect": as_int(raw.get("collect")),
        "image": image,
        "steps": steps,
        "source": str(raw.get("source") or "").strip() or None,
        "_cat": "curated" if source == "howtocook" else "inferred",
    }


def merge_pair(base: dict, extra: dict) -> dict:
    """base 为主(字段全/赞高);extra 补图片/步骤/出处/缺失字段,食材取并集。"""
    extra_tokens = split_stuff(extra["stuff"])
    base_tokens = split_stuff(base["stuff"])
    for token in extra_tokens:
        if not any(token in t or t in token for t in base_tokens):
            base_tokens.append(token)
    base["stuff"] = "、".join(base_tokens)
    # 显示名取更简洁的一方(无括号且更短),如「家常黄焖鸡(多调料版)」→「黄焖鸡」
    extra_name = extra["name"]
    has_paren = "（" in base["name"] or "(" in base["name"]
    if has_paren and "（" not in extra_name and "(" not in extra_name and len(extra_name) < len(base["name"]):
        base["name"] = extra_name
    base["image"] = base.get("image") or extra.get("image")
    base["steps"] = base.get("steps") or extra.get("steps") or []
    base["source"] = base.get("source") or extra.get("source")
    if not base["bv"]:
        base["bv"] = extra.get("bv")
    if base["heat"] is None:
        base["heat"] = extra.get("heat")
    if not base["tools"]:
        base["tools"] = extra["tools"]
    if not base["methods"]:
        base["methods"] = extra["methods"]
    for tag in extra["tags"]:
        if tag not in base["tags"]:
            base["tags"].append(tag)
    # 分类:HowToCook 人工分类优先,但「半成品」不覆盖正常分类
    if extra["_cat"] == "curated" and base["_cat"] != "curated" and extra["category"] not in ("半成品", "未分类", ""):
        base["category"] = extra["category"]
        base["_cat"] = "curated"
    elif base["category"] in ("半成品", "未分类", "") and extra["category"] not in ("半成品", "未分类", ""):
        base["category"] = extra["category"]
        if extra["_cat"] == "curated":
            base["_cat"] = "curated"
    return base


def dedupe(records: list[dict], key_fn) -> tuple[list[dict], int]:
    """按 key_fn 分组合并,返回(结果, 消除的重复数)。"""
    groups: dict[str, list[dict]] = {}
    for record in records:
        groups.setdefault(key_fn(record["name"]), []).append(record)
    merged: list[dict] = []
    collisions = 0
    for group in groups.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        collisions += len(group) - 1
        group.sort(
            key=lambda r: sum(bool(r[f]) for f in ("stuff", "bv", "image", "steps")) * 10 + r["likes"],
            reverse=True,
        )
        head = group[0]
        for other in group[1:]:
            head = merge_pair(head, other)
        merged.append(head)
    return merged, collisions


def main() -> None:
    ext_raw = json.loads(EXT_PATH.read_text(encoding="utf-8"))
    htc_raw = json.loads(HTC_PATH.read_text(encoding="utf-8"))

    ext = [r for r in (make_record(r, source="bilibili") for r in ext_raw) if r]
    htc = [r for r in (make_record(r, source="howtocook") for r in htc_raw) if r]
    dropped_invalid = (len(ext_raw) - len(ext)) + (len(htc_raw) - len(htc))

    # 清洗 B 站源的分类:原数据 585/599 标「素菜」,按菜名+食材重新推断
    for record in ext:
        record["category"] = guess_category(record["name"], split_stuff(record["stuff"]))

    all_records = ext + htc
    all_records, dup_exact = dedupe(all_records, norm_key)
    all_records, dup_alias = dedupe(all_records, core_key)

    all_records.sort(
        key=lambda r: (CATEGORY_ORDER.index(r["category"]) if r["category"] in CATEGORY_ORDER else 99, r["name"])
    )
    for record in all_records:
        record.pop("_cat", None)

    OUT_PATH.write_text(json.dumps(all_records, ensure_ascii=False, indent=1), encoding="utf-8")

    n_image = sum(1 for r in all_records if r["image"])
    n_video = sum(1 for r in all_records if r["bv"])
    n_steps = sum(1 for r in all_records if r["steps"])
    cats: dict[str, int] = {}
    for r in all_records:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    print(f"输出 {len(all_records)} 条 -> {OUT_PATH}")
    print(f"无效剔除 {dropped_invalid} 条;精确重名合并 {dup_exact} 条;别名重名合并 {dup_alias} 条")
    print(f"带图片 {n_image} | 带视频 {n_video} | 带步骤 {n_steps}")
    print("分类分布:", {k: cats[k] for k in CATEGORY_ORDER if k in cats})


if __name__ == "__main__":
    main()
