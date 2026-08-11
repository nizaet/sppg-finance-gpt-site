import React from "react";
import { createRoot } from "react-dom/client";
import SmartCateringAccountant from "./App.jsx";
import { OperationsControlTower } from "./operations/index.js";
import "./styles.css";

const pathname = typeof window !== "undefined" ? window.location.pathname : "/";
const isOperationsRoute = pathname === "/operations" || pathname.startsWith("/operations/");
const RootComponent = isOperationsRoute ? OperationsControlTower : SmartCateringAccountant;

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <RootComponent />
  </React.StrictMode>
);
