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

    calculator_favicon = "/favicon-calc-cemplang.svg?v=27" if unit == "cemplang" else "/favicon-calc-maja.svg?v=27"
    calculator_title = "Kalkulator Cemplang | SPPG" if unit == "cemplang" else "Kalkulator Maja | SPPG"
    calculator_dark_styles = (LEGACY_DIR / "theme-dark.css").read_text(encoding="utf-8")
    boot = f"""
    <link rel="icon" type="image/svg+xml" href="{calculator_favicon}" />
    <link rel="shortcut icon" type="image/svg+xml" href="{calculator_favicon}" />
    <script>
      document.title = {json.dumps(calculator_title)};
      var __legacyUnitId = {json.dumps(unit)};
      var __app_id = {json.dumps(app_id)};
      var __firebase_config = JSON.stringify({firebase_json});
      var __siteAccessRole = {json.dumps(role)};
      window.__legacyUnitId = __legacyUnitId;
      window.__firestoreDatabaseId = {json.dumps(database_id)};
      var __appThemeKey = 'sppg_app_theme_v1';
      var __appTheme = localStorage.getItem(__appThemeKey) || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      function applySharedAppTheme(theme) {{
        __appTheme = theme === 'light' ? 'light' : 'dark';
        document.documentElement.dataset.appTheme = __appTheme;
        document.documentElement.style.colorScheme = __appTheme;
        localStorage.setItem(__appThemeKey, __appTheme);
      }}
      applySharedAppTheme(__appTheme);
      window.__railwayFirebaseTokenPromise = (async function () {{
        var sessionToken = sessionStorage.getItem('sppg_session_token_v1') || localStorage.getItem('sppg_session_token_v1') || '';
        if (!sessionToken) throw new Error('Sesi Railway tidak ditemukan. Silakan masuk ulang.');
        var response = await fetch('/v1/firebase/custom-token?site={UNIT_CONFIG[unit]["label"]}', {{
          headers: {{ Authorization: 'Bearer ' + sessionToken }},
          credentials: 'same-origin'
        }});
        var payload = await response.json().catch(function () {{ return {{}}; }});
        if (!response.ok || !payload.token) throw new Error(payload.detail || 'Firebase custom token tidak tersedia.');
        return payload.token;
      }})();
      window.__syncSharedCalculatorMaster = async function (dataType, operation, recordKey, payload) {{
        var sessionToken = sessionStorage.getItem('sppg_session_token_v1') || localStorage.getItem('sppg_session_token_v1') || '';
        if (!sessionToken) throw new Error('Sesi Railway tidak ditemukan untuk sinkronisasi master.');
        var response = await fetch('/v1/calculator-data/shared-master-sync', {{
          method: 'POST',
          headers: {{ 'Authorization': 'Bearer ' + sessionToken, 'Content-Type': 'application/json' }},
          credentials: 'same-origin',
          body: JSON.stringify({{
            source_site: {json.dumps(UNIT_CONFIG[unit]["label"])},
            data_type: dataType,
            operation: operation,
            record_key: recordKey || null,
            payload: payload === undefined ? null : payload,
            actor: 'calculator-' + {json.dumps(unit)}
          }})
        }});
        var result = await response.json().catch(function () {{ return {{}}; }});
        if (!response.ok || result.committed !== true) throw new Error(result.detail || 'Sinkronisasi master Maja + Cemplang gagal.');
        return result;
      }};
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
        var themeButton = document.createElement('button');
        themeButton.type = 'button';
        themeButton.className = 'railway-app-control';
        function renderThemeButton() {{
          themeButton.innerHTML = __appTheme === 'dark'
            ? '<i class="fas fa-sun"></i><span>Tema Terang</span>'
            : '<i class="fas fa-moon"></i><span>Tema Gelap</span>';
        }}
        themeButton.addEventListener('click', function () {{
          applySharedAppTheme(__appTheme === 'dark' ? 'light' : 'dark');
          renderThemeButton();
        }});
        renderThemeButton();
        controls.appendChild(themeButton);
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
      {calculator_dark_styles}
      @media (max-width: 639px) {{
        #railwayAppControls {{ width: 100%; margin: .65rem 0 0; justify-content: stretch; }}
        .railway-app-control {{ flex: 1 1 auto; min-height: 2.65rem; font-size: .8rem; }}
      }}
    </style>
    """
    html = source.replace("<head>", f"<head>{boot}", 1)
    # A default Auth instance persists across tabs on this origin. Signing into
    # Cemplang (including its accountant page) can replace Maja's user after the
    # claim check and invalidate active Firestore reads/listeners. Keep calculator
    # Auth entirely in this page; Railway supplies a fresh token on every reload.
    html = html.replace(
        "            getAuth,",
        "            getAuth, initializeAuth, inMemoryPersistence,",
    )
    html = html.replace(
        "if (!app) app = initializeApp(firebaseConfig);",
        f"if (!app) app = initializeApp(firebaseConfig, 'sppg-calculator-{unit}');",
    )
    html = html.replace(
        "if (!auth) auth = getAuth(app);",
        "if (!auth) auth = initializeAuth(app, { persistence: inMemoryPersistence });",
    )
    html = html.replace(
        "const FIREBASE_CONNECTION_STORAGE_KEY = 'spbg_firebase_connection_v1';",
        f"const FIREBASE_CONNECTION_STORAGE_KEY = 'spbg_firebase_connection_v1-{unit}';",
    )
    html = html.replace(
        "        function formatFirebasePermissionError(err, authMode, parsed) {",
        """        async function getInitialFirebaseAuthToken() {
            const embedded = getInitialFirebaseAuthTokenSafe();
            if (embedded) return embedded;
            if (window.__railwayFirebaseTokenPromise) {
                return String(await window.__railwayFirebaseTokenPromise || '');
            }
            return '';
        }

        function formatFirebasePermissionError(err, authMode, parsed) {""",
    )
    html = html.replace(
        "            const token = getInitialFirebaseAuthTokenSafe();",
        "            const token = await getInitialFirebaseAuthToken();",
    )
    html = html.replace(
        """                        if (typeof __initial_auth_token !== 'undefined' && __initial_auth_token) {
                            await signInWithCustomToken(auth, __initial_auth_token);
                        } else {
                            await signInAnonymously(auth);
                        }""",
        """                        const firebaseToken = await getInitialFirebaseAuthToken();
                        if (firebaseToken) {
                            await signInWithCustomToken(auth, firebaseToken);
                        } else {
                            await signInAnonymously(auth);
                        }""",
    )
    legacy_main_auth = (
        "                        if (typeof __initial_auth_token !== 'undefined') { \n"
        "                            logActivity(\"Mencoba login dengan Custom Token...\"); \n"
        "                            await signInWithCustomToken(auth, __initial_auth_token); \n"
        "                        } else { \n"
        "                            logActivity(\"Mencoba login secara anonim...\"); \n"
        "                            await signInAnonymously(auth); \n"
        "                        }"
    )
    html = html.replace(
        legacy_main_auth,
        """                        const firebaseToken = await getInitialFirebaseAuthToken();
                        if (firebaseToken) {
                            logActivity(\"Mencoba login dengan Custom Token...\");
                            await signInWithCustomToken(auth, firebaseToken);
                        } else {
                            logActivity(\"Mencoba login secara anonim...\");
                            await signInAnonymously(auth);
                        }""",
    )
    auth_start_marker = "        async function authWithFirebase() {"
    auth_end_marker = "        function enableUI() {"
    auth_start = html.find(auth_start_marker)
    auth_end = html.find(auth_end_marker, auth_start)
    if auth_start < 0 or auth_end < 0:
        raise RuntimeError(f"legacy Firebase auth block was not found for {unit}")
    secure_auth = """        async function authWithFirebase() {
            logActivity("Mencoba otentikasi...");
            const firebaseToken = await getInitialFirebaseAuthToken();
            if (!firebaseToken) {
                throw new Error("Custom Token Railway tidak tersedia. Silakan keluar lalu masuk kembali.");
            }

            // Finish sign-in on this page's isolated Auth instance before any
            // reads. Never use a previously cached user to skip this claim check.
            logActivity("Mencoba login dengan Custom Token...");
            const credential = await signInWithCustomToken(auth, firebaseToken);
            const user = credential && credential.user;
            if (!user) throw new Error("Firebase tidak mengembalikan pengguna setelah login.");

            const tokenResult = await user.getIdTokenResult(true);
            const claims = tokenResult && tokenResult.claims ? tokenResult.claims : {};
            const expectedSite = String(window.__legacyUnitId || '').toUpperCase();
            const actualSite = String(claims.sppg_site || '').toUpperCase();
            const actualRole = String(claims.sppg_role || '').toUpperCase();
            if (actualSite !== expectedSite) {
                throw new Error(`Token Firebase salah dapur: diterima ${actualSite || '-'}, seharusnya ${expectedSite}.`);
            }
            if (actualRole !== 'OWNER' && actualRole !== expectedSite) {
                throw new Error(`Role Firebase ${actualRole || '-'} tidak boleh membuka ${expectedSite}.`);
            }

            userId = user.uid;
            logActivity(`Listener: Otentikasi berhasil. Site token: ${actualSite}.`);
            return user;
        }

"""
    html = html[:auth_start] + secure_auth + html[auth_end:]
    load_start = html.find("        async function loadAllData() {")
    load_end = html.find("        function setupAllListeners() {", load_start)
    if load_start < 0 or load_end < 0:
        raise RuntimeError(f"legacy Firebase data loader was not found for {unit}")
    diagnostic_loader = """        async function loadAllData() {
            logActivity("Memuat data awal...");
            const load = async (path, loader) => {
                try {
                    await loader();
                } catch (error) {
                    const databaseId = window.__firestoreDatabaseId || '(default)';
                    const code = error.code || 'unknown';
                    const location = `${firebaseConfig.projectId}/${databaseId}/artifacts/${appId}/public/data/${path}`;
                    logActivity(`ERROR baca ${location} [${code}]: ${error.message}`, true);
                    if (code === 'permission-denied' || code === 'firestore/permission-denied') {
                        const denied = new Error(`Akses data ${path} ditolak di database ${databaseId}. Periksa aturan Firestore untuk dapur ${String(window.__legacyUnitId).toUpperCase()}.`);
                        denied.code = code;
                        throw denied;
                    }
                    throw error;
                }
            };
            try {
                await Promise.all([
                    load('recipes', loadRecipes),
                    load('masterData/priceList', loadMasterPriceList),
                    load('customGramasi', loadCustomGramasi),
                    load('dailyPlans', loadSavedPlans),
                    load('bumbuList/default', loadBumbuList)
                ]);
                logActivity("Semua data awal berhasil dimuat.");
            } catch (error) {
                logActivity(`ERROR saat memuat data awal: ${error.message}`, true);
                throw error;
            }
        }

"""
    html = html[:load_start] + diagnostic_loader + html[load_end:]
    html = html.replace(
        "if (!db) db = getFirestore(app);",
        "if (!db) db = (window.__firestoreDatabaseId && window.__firestoreDatabaseId !== '(default)') ? getFirestore(app, window.__firestoreDatabaseId) : getFirestore(app);",
    )
    shared_master_replacements = [
        (
            '                showMessage("Resep berhasil disimpan.", "success");',
            '                await window.__syncSharedCalculatorMaster("RECIPES", "UPSERT", recipeId, { id: recipeId, ...recipeData });\n                showMessage("Resep tersimpan dan tersinkron ke Maja + Cemplang.", "success");',
        ),
        (
            '                await deleteDoc(doc(db, `artifacts/${appId}/public/data/recipes`, recipeId));',
            '                await deleteDoc(doc(db, `artifacts/${appId}/public/data/recipes`, recipeId));\n                await window.__syncSharedCalculatorMaster("RECIPES", "DELETE", recipeId, null);',
        ),
        (
            '                await setDoc(doc(db, `artifacts/${appId}/public/data/masterData`, \'priceList\'), masterPriceList);',
            '                await setDoc(doc(db, `artifacts/${appId}/public/data/masterData`, \'priceList\'), masterPriceList);\n                await window.__syncSharedCalculatorMaster("PRICES", "REPLACE", null, masterPriceList);',
        ),
        (
            '                await setDoc(doc(db, `artifacts/${appId}/public/data/masterData`, \'priceList\'), { [name]: exData }, { merge: true });',
            '                await setDoc(doc(db, `artifacts/${appId}/public/data/masterData`, \'priceList\'), { [name]: exData }, { merge: true });\n                await window.__syncSharedCalculatorMaster("PRICES", "UPSERT", name, exData);',
        ),
        (
            '                await setDoc(doc(db, `artifacts/${appId}/public/data/masterData`, \'priceList\'), { [key]: masterPriceList[key] }, { merge: true });',
            # The price-save icon in Daftar Belanja must not depend on browser
            # Firestore write permissions. It writes both calculator masters
            # through Railway first. The local write is retained only as a
            # recoverable fallback so a temporary sync outage never loses the
            # price the operator just entered.
            '''                try {
                    await window.__syncSharedCalculatorMaster("PRICES", "UPSERT", key, masterPriceList[key]);
                } catch (syncError) {
                    await setDoc(doc(db, `artifacts/${appId}/public/data/masterData`, 'priceList'), { [key]: masterPriceList[key] }, { merge: true });
                    console.warn('Sinkronisasi Master Harga dua dapur tertunda:', syncError);
                    showMessage(`Harga ${name} tersimpan di Master Harga dapur ini. Sinkronisasi dapur lain akan dicoba lagi saat koneksi pulih.`, 'warning');
                    return;
                }''',
        ),
        (
            '                await setDoc(doc(db, `artifacts/${appId}/public/data/customGramasi`, id), { id, name, kecil, besar });',
            '                await setDoc(doc(db, `artifacts/${appId}/public/data/customGramasi`, id), { id, name, kecil, besar });\n                await window.__syncSharedCalculatorMaster("GRAMASI", "UPSERT", id, { id, name, kecil, besar });',
        ),
        (
            '                await deleteDoc(doc(db, `artifacts/${appId}/public/data/customGramasi`, id));',
            '                await deleteDoc(doc(db, `artifacts/${appId}/public/data/customGramasi`, id));\n                await window.__syncSharedCalculatorMaster("GRAMASI", "DELETE", id, null);',
        ),
        (
            '                await setDoc(doc(db, `artifacts/${appId}/public/data/bumbuList`, \'default\'), { list: Array.from(bumbuList), rules: bumbuGramasiRules });',
            '                await setDoc(doc(db, `artifacts/${appId}/public/data/bumbuList`, \'default\'), { list: Array.from(bumbuList), rules: bumbuGramasiRules });\n                await window.__syncSharedCalculatorMaster("BUMBU", "REPLACE", null, { list: Array.from(bumbuList), rules: bumbuGramasiRules });',
        ),
        (
            '                            await setDoc(docRef, { ...aturan, id: id });',
            '                            await setDoc(docRef, { ...aturan, id: id });\n                            await window.__syncSharedCalculatorMaster("GRAMASI", "UPSERT", id, { ...aturan, id: id });',
        ),
        (
            '                        await setDoc(doc(db, `artifacts/${appId}/public/data/recipes`, recipeId), mergedRecipe, { merge: true });',
            '                        await setDoc(doc(db, `artifacts/${appId}/public/data/recipes`, recipeId), mergedRecipe, { merge: true });\n                        await window.__syncSharedCalculatorMaster("RECIPES", "UPSERT", recipeId, { id: recipeId, ...mergedRecipe });',
        ),
        (
            '                    await setDoc(docRef, currentPrices);',
            '                    await setDoc(docRef, currentPrices);\n                    await window.__syncSharedCalculatorMaster("PRICES", "REPLACE", null, currentPrices);',
        ),
        (
            '                    await setDoc(doc(db, `artifacts/${appId}/public/data/bumbuList`, \'default\'), { list: normalized });',
            '                    await setDoc(doc(db, `artifacts/${appId}/public/data/bumbuList`, \'default\'), { list: normalized });\n                    await window.__syncSharedCalculatorMaster("BUMBU", "REPLACE", null, { list: normalized, rules: {} });',
        ),
    ]
    for original, replacement in shared_master_replacements:
        if original not in html:
            raise RuntimeError(f"legacy shared-master hook was not found for {unit}: {original[:80]}")
        html = html.replace(original, replacement)
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
