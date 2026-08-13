from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.db import connection, database_ready

router = APIRouter(tags=["inventory-summary"])


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


@router.get("/inventory/balances")
def inventory_balances(
    site: str = Query(min_length=1),
    search: str = "",
    limit: int = Query(default=300, ge=1, le=1000),
) -> dict[str, Any]:
    """Read-only aggregated inventory balance for one SPPG site."""
    require_db()
    site = site.upper().strip()
    if site not in {"MAJA", "CEMPLANG"}:
        raise HTTPException(400, "site must be MAJA or CEMPLANG")

    sql = """
        select item_name,coalesce(unit,'') as unit,
               sum(case
                     when upper(coalesce(to_location,''))=%s then qty
                     when upper(coalesce(from_location,''))=%s then -qty
                     else 0
                   end) as balance,
               max(coalesce(occurred_at,created_at)) as last_movement_at
        from inventory_movements
        where (upper(coalesce(to_location,''))=%s or upper(coalesce(from_location,''))=%s)
    """
    params: list[Any] = [site, site, site, site]
    if search.strip():
        sql += " and item_name ilike %s"
        params.append(f"%{search.strip()}%")
    sql += " group by item_name,coalesce(unit,'') order by item_name limit %s"
    params.append(limit)

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            items = cur.fetchall()
    return {"site": site, "items": items, "count": len(items)}
