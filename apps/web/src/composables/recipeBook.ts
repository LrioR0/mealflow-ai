import type { ExtendedRecipeRaw, Recipe } from '../types/recipe'

export type { Recipe } from '../types/recipe'

// 一级分类(规格固定 9 类);数据中不存在的分类由页面按计数自动隐藏
export const CATEGORY_ORDER = ['荤菜', '素菜', '汤', '主食', '早餐', '水产', '甜品', '酱料', '饮品']

export const DIFFICULTY_OPTIONS = ['简单', '中等', '困难']

// Tab2 食材分组(已对照 recipes_extended.json 的 stuff 词表校准;数据中无「鱼/面条/米粉」)
export const INGREDIENT_GROUPS: Array<{ label: string; items: string[] }> = [
  {
    label: '菜菜们',
    items: ['土豆', '胡萝卜', '花菜', '白萝卜', '西葫芦', '番茄', '芹菜', '黄瓜', '洋葱', '莴笋', '菌菇', '茄子', '豆腐', '包菜', '白菜'],
  },
  {
    label: '肉肉们',
    items: ['午餐肉', '香肠', '腊肠', '鸡肉', '猪肉', '鸡蛋', '虾', '牛肉', '骨头'],
  },
  {
    label: '主食(可选)',
    items: ['面食', '面包', '米', '方便面'],
  },
]

// 厨具不参与本地过滤(仅随食材一并传给 Agent);大锅在数据中记作「一口大锅」
export const TOOL_OPTIONS = ['烤箱', '空气炸锅', '微波炉', '电饭煲', '大锅']
export const BIG_POT_HINT = '一口能炒又能煮的大锅'

export type MatchMode = 'fuzzy' | 'strict' | 'survival'
export type SortKey = 'default' | 'likes' | 'collect'

export const MATCH_MODES: Array<{ key: MatchMode; label: string; desc: string }> = [
  { key: 'fuzzy', label: '模糊匹配', desc: '包含任一选中食材就展示' },
  { key: 'strict', label: '严格匹配', desc: '菜谱全部食材都在勾选范围内' },
  { key: 'survival', label: '生存模式', desc: '优先推荐食材数量最少的菜谱' },
]

export const SORT_OPTIONS: Array<{ key: SortKey; label: string }> = [
  { key: 'default', label: '默认排序' },
  { key: 'likes', label: '点赞最多' },
  { key: 'collect', label: '收藏最多' },
]

// 原始字段形态不统一:tags 可能是数组或「、」连接的字符串,stuff 用顿号/逗号分隔
function splitTokens(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean)
  }
  const text = typeof value === 'string' ? value.trim() : ''
  if (!text) return []
  return text
    .split(/[、,，/;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

// bv 字段存的是 BV 号/av 号(或完整链接),统一拼成 B 站视频地址
function toVideoUrl(bv: unknown): string | null {
  const id = String(bv ?? '').trim()
  if (!id) return null
  if (/^https?:\/\//i.test(id)) return id
  return `https://www.bilibili.com/video/${id}`
}

export function normalizeRecipe(raw: ExtendedRecipeRaw, index: number): Recipe {
  const heat = typeof raw.heat === 'number' && Number.isFinite(raw.heat) ? raw.heat : null
  return {
    id: `${index}-${String(raw.name ?? '').trim()}`,
    name: String(raw.name ?? '').trim() || '未命名菜谱',
    ingredients: splitTokens(raw.stuff),
    videoUrl: toVideoUrl(raw.bv),
    difficulty: String(raw.difficulty ?? '').trim(),
    tags: splitTokens(raw.tags),
    methods: splitTokens(raw.methods),
    tools: splitTokens(raw.tools),
    category: String(raw.category ?? '').trim() || '未分类',
    heat,
    likes: Number(raw.likes) || 0,
    collect: Number(raw.collect) || 0,
    image: typeof raw.image === 'string' && raw.image.trim() ? raw.image.trim() : null,
  }
}

export async function loadRecipes(): Promise<Recipe[]> {
  const response = await fetch('/data/recipes_merged.json')
  if (!response.ok) {
    throw new Error(`菜谱数据加载失败 (${response.status})`)
  }
  const raw = (await response.json()) as ExtendedRecipeRaw[] | { recipes?: ExtendedRecipeRaw[] }
  const list = Array.isArray(raw) ? raw : (raw.recipes ?? [])
  return list.map(normalizeRecipe)
}

// 食材命中:双向包含,让「米」能命中「米饭」、「虾」能命中「虾仁」
function ingredientHit(token: string, selected: string[]): boolean {
  return selected.some((item) => token.includes(item) || item.includes(token))
}

export interface CookbookFilters {
  keyword: string
  category: string // '全部' 或具体分类名
  difficulties: string[]
  heatRange: [number, number] | null
  sort: SortKey
}

// Tab1 菜谱大全:分类 + 难度 + 热量区间 + 菜名搜索 + 排序
export function filterCookbook(recipes: Recipe[], filters: CookbookFilters): Recipe[] {
  const keyword = filters.keyword.trim()
  const result = recipes.filter((recipe) => {
    if (filters.category !== '全部' && recipe.category !== filters.category) return false
    if (filters.difficulties.length && !filters.difficulties.includes(recipe.difficulty)) return false
    if (filters.heatRange) {
      if (recipe.heat === null) return false
      if (recipe.heat < filters.heatRange[0] || recipe.heat > filters.heatRange[1]) return false
    }
    if (keyword && !recipe.name.includes(keyword)) return false
    return true
  })
  if (filters.sort === 'likes') return result.sort((a, b) => b.likes - a.likes)
  if (filters.sort === 'collect') return result.sort((a, b) => b.collect - a.collect)
  return result
}

function survivalRank(a: Recipe, b: Recipe): number {
  return a.ingredients.length - b.ingredients.length || b.likes - a.likes
}

// Tab2 按食材找菜:
// 模糊匹配=菜谱含任一选中食材;严格匹配=菜谱全部食材都被勾选项覆盖;
// 生存模式=命中后按食材数量升序(未勾选时展示全部并按食材数排序)
export function matchByIngredients(recipes: Recipe[], selected: string[], mode: MatchMode): Recipe[] {
  if (!selected.length) {
    const all = [...recipes]
    return mode === 'survival' ? all.sort(survivalRank) : all
  }
  const matched = recipes.filter((recipe) => {
    if (!recipe.ingredients.length) return false
    if (mode === 'strict') {
      return recipe.ingredients.every((token) => ingredientHit(token, selected))
    }
    return recipe.ingredients.some((token) => ingredientHit(token, selected))
  })
  if (mode === 'survival') return matched.sort(survivalRank)
  return matched
}
