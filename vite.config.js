import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  preview: {
    host: "0.0.0.0",
    allowedHosts: [
      "sppg-finance-gpt-site-production.up.railway.app"
    ]
  },
  server: {
    host: "0.0.0.0",
    allowedHosts: [
      "sppg-finance-gpt-site-production.up.railway.app"
    ]
  }
});
