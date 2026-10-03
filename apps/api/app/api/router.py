from fastapi import APIRouter

from app.api.routes import agent, health, inventory, kiosk

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(agent.router)
api_router.include_router(kiosk.router)
api_router.include_router(inventory.router)
