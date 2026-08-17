import React from "react";
import OperationsPoPlanner from "./OperationsPoPlanner.jsx";
import PoReminderActionCenter from "./PoReminderActionCenter.jsx";

export default function OperationsPoWorkspace(props) {
  return (
    <>
      <OperationsPoPlanner {...props} />
      <PoReminderActionCenter />
    </>
  );
}
