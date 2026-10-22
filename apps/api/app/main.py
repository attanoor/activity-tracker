from fastapi import FastAPI

from app.routers import (admin, admin_manage, admin_settings, auth, clients, days, devices, downloads, ingest,
                         integrations, reports, team)

app = FastAPI(title="Activity Tracker API", version="0.2.0")
for r in (auth.router, admin.router, admin_manage.router, admin_settings.router, devices.router, ingest.router,
          days.router, downloads.router, reports.router, team.router, integrations.router, clients.router):
    app.include_router(r)


@app.get("/health")
def health():
    return {"ok": True}
