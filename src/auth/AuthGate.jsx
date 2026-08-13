import React, { useEffect, useState } from "react";
import { LockKeyhole, LogOut, ShieldCheck, WalletCards } from "lucide-react";
import { authApi, clearSession, readSessionRole, readSessionToken, storeSession } from "./session.js";
import "./auth.css";

const ROLES = ["OWNER", "MAJA", "CEMPLANG"];

function LoginScreen({ onAuthenticated }) {
  const [role, setRole] = useState("OWNER");
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
          <p>Masuk dengan akun operasional. Akun ChatGPT tidak diperlukan.</p>
        </div>

        <label>
          Akun
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((item) => <option key={item} value={item}>{item}</option>)}
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

function SessionBar({ role, onLogout }) {
  const operations = () => { window.location.href = "/operations"; };
  const accountant = () => { window.location.href = "/"; };
  return (
    <div className="sppg-session-bar">
      <span>{role}</span>
      <button type="button" onClick={operations}>Pusat Operasional</button>
      {role === "OWNER" && <button type="button" onClick={accountant}><WalletCards size={14} /> Akuntan</button>}
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

        // Failsafe: until Railway has all four secrets, preserve the current app
        // so configuration cannot accidentally lock the owner out.
        if (!cfg?.enabled) {
          setRole("OWNER");
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
        // Backend unavailable must not turn into an insecure implicit login once
        // auth has been configured. Show login and let its error explain failure.
        setConfig({ enabled: true, backendUnavailable: true });
        clearSession();
        setRole("");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    boot();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return <main className="sppg-auth-loading">Memeriksa akses SPPG…</main>;
  }

  if (config?.enabled && !role) {
    return <LoginScreen onAuthenticated={setRole} />;
  }

  const logout = async () => {
    await authApi.logout();
    clearSession();
    setRole("");
  };

  return (
    <>
      {config?.enabled && <SessionBar role={role} onLogout={logout} />}
      {children({ role: role || "OWNER", authEnabled: Boolean(config?.enabled) })}
    </>
  );
}
