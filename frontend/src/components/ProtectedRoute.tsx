import React from "react";
import { useAuth } from "../context/AuthContext";

interface ProtectedRouteProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ children, fallback }) => {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <div className="protected-loading">
        <div className="status-spinner" />
        <p>Verifying authentication session...</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      fallback || (
        <div className="protected-unauthenticated alert-box alert-box--error">
          <h3>Authentication Required</h3>
          <p>You must be logged in to view this protected area.</p>
        </div>
      )
    );
  }

  return <>{children}</>;
};
