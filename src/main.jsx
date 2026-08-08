import React from "react";
import { createRoot } from "react-dom/client";
import SmartCateringAccountant from "./App.jsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <SmartCateringAccountant />
  </React.StrictMode>
);
