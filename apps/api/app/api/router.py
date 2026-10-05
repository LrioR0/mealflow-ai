from fastapi import APIRouter

from app.api.routes import agent, feedback, health, inventory, kiosk, meal_plans

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(agent.router)
api_router.include_router(meal_plans.router)
api_router.include_router(kiosk.router)
api_router.include_router(inventory.router)
api_router.include_router(feedback.router)
