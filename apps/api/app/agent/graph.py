from langgraph.graph import END, START, StateGraph

from app.agent.state import MealPlanningState


def _mark_node(state: MealPlanningState, name: str) -> MealPlanningState:
    trace = [*state.get("tool_trace", [])]
    trace.append({"tool_name": name, "status": "success", "duration_ms": 0})
    return {**state, "tool_trace": trace}


def parse_request(state: MealPlanningState) -> MealPlanningState:
    return _mark_node(state, "parse_request")


def load_context(state: MealPlanningState) -> MealPlanningState:
    return _mark_node(state, "load_context")


def build_options(state: MealPlanningState) -> MealPlanningState:
    return _mark_node(state, "build_options")


def wait_for_human(state: MealPlanningState) -> MealPlanningState:
    return {**_mark_node(state, "wait_for_human"), "approval_status": "waiting"}


def build_meal_planning_graph():
    graph = StateGraph(MealPlanningState)
    graph.add_node("parse_request", parse_request)
    graph.add_node("load_context", load_context)
    graph.add_node("build_options", build_options)
    graph.add_node("wait_for_human", wait_for_human)
    graph.add_edge(START, "parse_request")
    graph.add_edge("parse_request", "load_context")
    graph.add_edge("load_context", "build_options")
    graph.add_edge("build_options", "wait_for_human")
    graph.add_edge("wait_for_human", END)
    return graph.compile()
