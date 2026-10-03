export interface PlanningConstraints {
  expected_diners: number | null
  budget_limit_cents: number | null
  dietary_style: string[]
  excluded_ingredients: string[]
  prioritize_expiring: boolean
  time_limit_minutes: number | null
}

export interface ToolTrace {
  tool_name: string
  status: string
  duration_ms: number
  input_summary: string
  output_summary: string
  error_code?: string | null
}

export interface MenuOption {
  strategy: string
  title: string
  items: Array<{ name: string; servings: number; kcal_per_serving: number }>
  estimated_cost_cents: number
  estimated_kcal_per_serving?: number | null
  score_breakdown: Record<string, number>
  procurement_list: Array<Record<string, string>>
  reasons: string[]
  warnings: string[]
}

export interface AgentRun {
  id: string
  status: string
  constraints: PlanningConstraints
  tool_trace: ToolTrace[]
  options: MenuOption[]
  warnings: string[]
  approval_status: string
  provider?: string | null
  model?: string | null
}
