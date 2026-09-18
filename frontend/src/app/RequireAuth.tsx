import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { isAuthenticated, getStoredUser } from "../api/client";

/**
 * Route guard for the authenticated app shell. When there is no valid token we
 * redirect to /login. If the user is flagged with must_change_password (e.g.
 * initial seeded admin), we redirect to /change-password before granting access.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation();
  if (!isAuthenticated()) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  const user = getStoredUser();
  if (user?.must_change_password && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }
  return <>{children}</>;
}
