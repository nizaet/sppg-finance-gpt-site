import { readSessionToken } from "../auth/session.js";
import { operationsBackendUrl } from "./apiClient.js";

export async function confirmPoShortageStock(payload) {
  const token = readSessionToken();
  const response = await fetch(`${operationsBackendUrl}/v1/po-reminders/stock-confirmation`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let detail = "";
    try { detail = await response.text(); } catch {}
    throw new Error(`SPPG Core API ${response.status}: ${detail || response.statusText}`);
  }
  return response.json();
}
