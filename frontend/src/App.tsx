import { useState, useEffect } from "react";
import { AdminApp } from "./AdminApp";
import { ReceiptApp } from "./ReceiptApp";

function isAdminRoute(): boolean {
  return window.location.hash.startsWith("#admin");
}

export default function App() {
  const [showAdmin, setShowAdmin] = useState(isAdminRoute);

  useEffect(() => {
    const onHash = () => setShowAdmin(isAdminRoute());
    window.addEventListener("hashchange", onHash);
    setShowAdmin(isAdminRoute());
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (showAdmin) return <AdminApp />;
  return <ReceiptApp />;
}
