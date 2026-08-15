from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY_DIR = ROOT / "legacy"

DEFAULT_FIREBASE_CONFIG = {
    "apiKey": "AIzaSyB72MVySugfHF_vu11WYv-s9uiQbRpftk4",
    "authDomain": "sppg-finance-gpt.firebaseapp.com",
    "projectId": "sppg-finance-gpt",
    "storageBucket": "sppg-finance-gpt.firebasestorage.app",
    "messagingSenderId": "732611890148",
    "appId": "1:732611890148:web:5dcfab93d1d351b10315f1",
    "measurementId": "G-DZERB61197",
}

UNIT_CONFIG = {
    "maja": {
        "label": "MAJA",
        "app_id_default": "sppg-maja-gpt-site",
        "database_default": "(default)",
    },
    "cemplang": {
        "label": "CEMPLANG",
        "app_id_default": "sppg-cemplang2-gpt-site",
        "database_default": "cemplang2",
    },
}


def _firebase_config() -> dict[str, str]:
    raw = os.getenv("SPPG_FIREBASE_PUBLIC_CONFIG_JSON", "").strip()
    if not raw:
        return DEFAULT_FIREBASE_CONFIG
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return DEFAULT_FIREBASE_CONFIG
    if not isinstance(parsed, dict) or not parsed.get("apiKey") or not parsed.get("projectId"):
        return DEFAULT_FIREBASE_CONFIG
    return {str(key): str(value) for key, value in parsed.items() if value is not None}


def calculator_settings(unit: str) -> dict[str, str]:
    config = UNIT_CONFIG[unit]
    return {
        "label": config["label"],
        # These targets contain the existing calculator data. Do not allow a
        # deployment variable to accidentally point one kitchen at the other.
        "app_id": config["app_id_default"],
        "database_id": config["database_default"],
    }


@lru_cache(maxsize=8)
def render_calculator_html(unit: str, role: str, app_id: str, database_id: str, firebase_json: str) -> str:
    if unit not in UNIT_CONFIG:
        raise ValueError("invalid calculator unit")
    source = (LEGACY_DIR / f"{unit}.html").read_text(encoding="utf-8")
    owner_control = ""
    if role == "OWNER":
        owner_control = """
        var operationsButton = document.createElement('button');
        operationsButton.type = 'button';
        operationsButton.className = 'railway-app-control';
        operationsButton.innerHTML = '<i class="fas fa-gauge-high"></i><span>Pusat Operasional</span>';
        operationsButton.addEventListener('click', function () { window.location.assign('/operations'); });
        controls.appendChild(operationsButton);
        """

    boot = f"""
    <script>
      var __legacyUnitId = {json.dumps(unit)};
      var __app_id = {json.dumps(app_id)};
      var __firebase_config = JSON.stringify({firebase_json});
      var __siteAccessRole = {json.dumps(role)};
      window.__legacyUnitId = __legacyUnitId;
      window.__firestoreDatabaseId = {json.dumps(database_id)};
      sessionStorage.setItem('isLoggedIn', 'true');
      document.addEventListener('DOMContentLoaded', function () {{
        var heading = Array.from(document.querySelectorAll('h2')).find(function (item) {{
          return item.textContent && item.textContent.trim() === 'Manajemen Data';
        }});
        var panel = heading && heading.parentElement && heading.parentElement.parentElement;
        var headerRow = document.querySelector('header.sticky-header > div') || document.querySelector('header > div');
        if (!headerRow) return;
        var controls = document.createElement('div');
        controls.id = 'railwayAppControls';
        if (panel) {{
          panel.id = 'legacyDataPanel';
          var mainContent = panel.nextElementSibling;
          if (mainContent) mainContent.id = 'legacyMainContent';
          var toggle = document.createElement('button');
          toggle.type = 'button';
          toggle.className = 'railway-app-control';
          controls.appendChild(toggle);
          var storageKey = 'sppg-panel-hidden-{unit}';
          var saved = localStorage.getItem(storageKey);
          var hidden = saved === null ? window.matchMedia('(max-width: 1023px)').matches : saved === '1';
          function applyPanelState() {{
            panel.classList.toggle('legacy-panel-hidden', hidden);
            if (mainContent) mainContent.classList.toggle('legacy-main-expanded', hidden);
            toggle.innerHTML = hidden
              ? '<i class="fas fa-table-columns"></i><span>Tampilkan Panel Kiri</span>'
              : '<i class="fas fa-eye-slash"></i><span>Sembunyikan Panel Kiri</span>';
          }}
          toggle.addEventListener('click', function () {{
            hidden = !hidden;
            localStorage.setItem(storageKey, hidden ? '1' : '0');
            applyPanelState();
          }});
          applyPanelState();
        }}
        {owner_control}
        var logoutButton = document.createElement('button');
        logoutButton.type = 'button';
        logoutButton.className = 'railway-app-control railway-logout';
        logoutButton.innerHTML = '<i class="fas fa-right-from-bracket"></i><span>Keluar / Ganti Akun</span>';
        logoutButton.addEventListener('click', async function () {{
          try {{ await fetch('/v1/auth/logout', {{ method: 'POST' }}); }} catch (error) {{}}
          localStorage.removeItem('sppg_session_token_v1');
          localStorage.removeItem('sppg_session_role_v1');
          sessionStorage.removeItem('sppg_session_token_v1');
          sessionStorage.removeItem('sppg_session_role_v1');
          window.location.assign('/');
        }});
        controls.appendChild(logoutButton);
        headerRow.appendChild(controls);
      }});
    </script>
    <style>
      html, body {{ max-width: 100%; overflow-x: hidden !important; }}
      #loginOverlay, #openAdminSettingsBtn, #adminSettingsModal, #logoutBtn {{ display: none !important; }}
      #legacyDataPanel.legacy-panel-hidden {{ display: none !important; }}
      #legacyMainContent.legacy-main-expanded {{ width: 100% !important; max-width: 100% !important; min-width: 0 !important; flex: 1 1 100% !important; margin-left: 0 !important; }}
      #legacyMainContent.legacy-main-expanded .desktop-wide-tabs {{ margin-left: 0 !important; width: 100% !important; max-width: 100% !important; }}
      #railwayAppControls {{ margin-left: auto; display: flex; flex-wrap: wrap; justify-content: flex-end; gap: .5rem; font-family: inherit; }}
      .railway-app-control {{ min-height: 2.4rem; border: 1px solid rgba(255,255,255,.45); border-radius: .5rem; padding: .5rem .75rem; color: white; background: rgba(255,255,255,.12); display: inline-flex; align-items: center; justify-content: center; gap: .45rem; font-family: inherit; font-size: .875rem; line-height: 1.25rem; font-weight: 600; white-space: nowrap; cursor: pointer; }}
      .railway-app-control:hover {{ background: rgba(255,255,255,.22); }}
      .railway-app-control.railway-logout {{ border-color: #fca5a5; background: #dc2626; }}
      @media (max-width: 639px) {{
        #railwayAppControls {{ width: 100%; margin: .65rem 0 0; justify-content: stretch; }}
        .railway-app-control {{ flex: 1 1 auto; min-height: 2.65rem; font-size: .8rem; }}
      }}
    </style>
    """
    html = source.replace("<head>", f"<head>{boot}", 1)
    html = html.replace(
        "const FIREBASE_CONNECTION_STORAGE_KEY = 'spbg_firebase_connection_v1';",
        f"const FIREBASE_CONNECTION_STORAGE_KEY = 'spbg_firebase_connection_v1-{unit}';",
    )
    html = html.replace(
        "if (!db) db = getFirestore(app);",
        "if (!db) db = (window.__firestoreDatabaseId && window.__firestoreDatabaseId !== '(default)') ? getFirestore(app, window.__firestoreDatabaseId) : getFirestore(app);",
    )
    return html


def calculator_html(unit: str, role: str) -> str:
    settings = calculator_settings(unit)
    return render_calculator_html(
        unit,
        role,
        settings["app_id"],
        settings["database_id"],
        json.dumps(_firebase_config(), ensure_ascii=False, separators=(",", ":")),
    )
