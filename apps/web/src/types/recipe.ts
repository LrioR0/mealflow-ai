// 懒人宝典:扩展菜谱库的原始结构与前端规范化结构
// 数据来源:apps/web/public/data/recipes_merged.json(B站菜谱库 + HowToCook 合并清洗版,见 scripts/merge_recipes.py)

export interface ExtendedRecipeRaw {
  name?: string
  stuff?: string
  bv?: string
  difficulty?: string
  tags?: string[] | string
  methods?: string
  tools?: string
  category?: string
  heat?: number
  likes?: number
  collect?: number
  image?: string | null
  [key: string]: unknown
}

// 规范化后的菜谱:字段缺失均有兜底,供页面直接渲染
export interface Recipe {
  id: string
  name: string
  ingredients: string[]
  videoUrl: string | null
  difficulty: string
  tags: string[]
  methods: string[]
  tools: string[]
  category: string
  heat: number | null
  likes: number
  collect: number
  image: string | null
}
