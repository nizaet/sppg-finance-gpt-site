import { getApp, getApps, initializeApp } from "firebase/app";
import { initializeAuth, inMemoryPersistence, signInWithCustomToken } from "firebase/auth";
import { authApi, readSessionToken } from "./session.js";

// Authenticate before importing/mounting App.jsx, whose effects read the ledger.
// Maja previously depended on public, time-limited Firestore test-mode rules.
export async function authenticateMajaFirebase(firebaseConfig) {
  const sessionToken = readSessionToken();
  if (!sessionToken) throw new Error("Sesi OWNER SPPG tidak ditemukan. Silakan login ulang.");
  const payload = await authApi.firebaseMajaToken(sessionToken);
  if (!payload?.token) throw new Error("Custom token Firebase Maja kosong.");
  const app = getApps().some(app => app.name === '[DEFAULT]') ? getApp() : initializeApp(firebaseConfig);
  // Do not restore another kitchen's persisted user or synchronize across tabs.
  const auth = initializeAuth(app, { persistence: inMemoryPersistence });
  const credential = await signInWithCustomToken(auth, payload.token);
  if (!credential?.user) throw new Error("Firebase tidak mengembalikan pengguna setelah login.");
  const { claims } = await credential.user.getIdTokenResult(true);
  if (claims.sppg_site !== 'MAJA' || claims.sppg_role !== 'OWNER') {
    throw new Error("Token Firebase tidak memiliki akses OWNER untuk Akuntan Maja.");
  }
}
