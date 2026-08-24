import React, { useEffect, useState } from "react";
import { Calculator, LockKeyhole, LogOut, ShieldAlert, ShieldCheck, WalletCards, Workflow } from "lucide-react";
import { authApi, clearSession, readSessionRole, readSessionToken, storeSession } from "./session.js";
import "./auth.css";

const ALL_ROLES = ["OWNER", "MAJA", "CEMPLANG"];
const ROLE_LABELS = { OWNER: "YAYASAN", MAJA: "MAJA", CEMPLANG: "CEMPLANG" };

function LoginScreen({ onAuthenticated, configuredRoles = ["OWNER"] }) {
  const roles = configuredRoles.length ? configuredRoles : ["OWNER"];
  const [role, setRole] = useState(roles.includes("OWNER") ? "OWNER" : roles[0]);
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const session = await authApi.login({ username: role, password, remember });
      storeSession(session);
      onAuthenticated(session.role);
    } catch (err) {
      setError(err.message || "Login gagal");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="sppg-login-page">
      <form className="sppg-login-card" onSubmit={submit}>
        <div className="sppg-login-icon"><LockKeyhole size={22} /></div>
        <div>
          <div className="sppg-login-kicker">SPPG OPERATIONS</div>
          <h1>Pusat Kontrol SPPG</h1>
        </div>

        <label>
          Akun
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {roles.map((item) => <option key={item} value={item}>{ROLE_LABELS[item] || item}</option>)}
          </select>
        </label>

        <label>
          Password
          <input
            autoFocus
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Masukkan password"
          />
        </label>

        <label className="sppg-login-remember">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          Ingat saya di perangkat ini
        </label>

        {error && <div className="sppg-login-error">{error}</div>}

        <button type="submit" disabled={loading || !password}>
          <ShieldCheck size={17} /> {loading ? "Memeriksa..." : "Masuk"}
        </button>
      </form>
    </main>
  );
}

function ConfigurationLocked({ config }) {
  const missing = config?.missingRoles || ALL_ROLES;
  return (
    <main className="sppg-login-page">
      <section className="sppg-login-card">
        <div className="sppg-login-icon"><ShieldAlert size={22} /></div>
        <div>
          <div className="sppg-login-kicker">AKSES DIKUNCI</div>
          <h1>Konfigurasi login belum aman</h1>
          <p>Aplikasi tidak akan memberikan akses YAYASAN otomatis. Pastikan konfigurasi login pusat tersedia di Railway.</p>
          {missing.length > 0 && <p>Role belum dikonfigurasi: <strong>{missing.join(", ")}</strong>.</p>}
        </div>
      </section>
    </main>
  );
}

function SessionBar({ role, config, onLogout }) {
  const operations = () => { window.location.href = "/operations"; };
  const accountantMaja = () => { window.location.href = config?.accountantUrls?.MAJA || "/accountant/maja"; };
  const accountantCemplang = () => { window.location.href = config?.accountantUrls?.CEMPLANG || "/accountant/cemplang"; };
  const calculatorSites = role === "OWNER" ? ["MAJA", "CEMPLANG"] : [role];

  return (
    <div className="sppg-session-bar">
      <span>{ROLE_LABELS[role] || role}</span>
      {calculatorSites.map((site) => (
        <a key={site} href={config?.calculatorUrls?.[site] || `/dapur/${site.toLowerCase()}`}>
          <Calculator size={14} /> Kalkulator {site === "MAJA" ? "Maja" : "Cemplang"}
        </a>
      ))}
      {role === "OWNER" && <button type="button" onClick={operations}><Workflow size={14} /> Pusat Operasional</button>}
      {role === "OWNER" && <button type="button" onClick={accountantMaja}><WalletCards size={14} /> Akuntan Maja</button>}
      {role === "OWNER" && <button type="button" onClick={accountantCemplang}><WalletCards size={14} /> Akuntan Cemplang</button>}
      <button type="button" className="danger" onClick={onLogout}><LogOut size={14} /> Keluar</button>
    </div>
  );
}

export default function AuthGate({ children }) {
  const [config, setConfig] = useState(null);
  const [role, setRole] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const boot = async () => {
      try {
        const cfg = await authApi.config();
        if (cancelled) return;
        setConfig(cfg);

        if (!cfg?.enabled) {
          clearSession();
          setRole("");
          return;
        }

        const token = readSessionToken();
        if (!token) {
          clearSession();
          setRole("");
          return;
        }
        try {
          const me = await authApi.me(token);
          if (!cancelled) setRole(me.role || readSessionRole());
        } catch {
          clearSession();
          if (!cancelled) setRole("");
        }
      } catch {
        setConfig({ enabled: false, backendUnavailable: true, missingRoles: ALL_ROLES });
        clearSession();
        setRole("");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    boot();
    return () => { cancelled = true; };
  }, []);

  if (loading) return <main className="sppg-auth-loading">Memeriksa akses SPPG…</main>;
  if (!config?.enabled) return <ConfigurationLocked config={config} />;
  if (!role) return <LoginScreen configuredRoles={config?.configuredRoles || ["OWNER"]} onAuthenticated={setRole} />;

  const logout = async () => {
    await authApi.logout();
    clearSession();
    setRole("");
  };

  return (
    <>
      <SessionBar role={role} config={config} onLogout={logout} />
      {children({ role, authEnabled: true, config })}
    </>
  );
}
