"""
phase_3/__init__.py
-------------------
Phase 3 package init. Exposes the FastAPI router for mounting in the main app.

Usage in main.py (root of the repo):
    from phase_3 import router as phase3_router
    app.include_router(phase3_router)
"""

from phase_3.router import router

__all__ = ["router"]
